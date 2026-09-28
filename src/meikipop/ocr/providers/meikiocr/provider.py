import logging
import re
from typing import List, Optional

import numpy as np
from PIL import Image

# Import the MeikiOCR library
from meikiocr import MeikiOCR
from meikiocr import ocr as meikiocr_module

# Import the "contract" classes from your application's interface
from meikipop.ocr.interface import BoundingBox, OcrProvider, Paragraph, Word
from meikipop.ocr.providers.postprocessing import group_lines_into_paragraphs

logger = logging.getLogger(__name__)

# --- pipeline configuration ---
# These thresholds are passed to the library's run_ocr method.
DET_CONFIDENCE_THRESHOLD = 0.5
REC_CONFIDENCE_THRESHOLD = 0.1

JAPANESE_REGEX = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]')

# the recognition model reads some bound compounds (characters that almost only occur together) in reverse;
# meikiocr fixes the ones it knows about in SWAPPED_PAIRS, these are ones found since
EXTRA_SWAPPED_PAIRS = {
    "髏髑": "髑髏",
}
meikiocr_module.SWAPPED_PAIRS.update(EXTRA_SWAPPED_PAIRS)

# vertical text: the detector sometimes returns two overlapping boxes for one column, each read a bit
# differently (padding the boxes to catch cut-off first characters was tried and made accuracy worse)
SAME_COLUMN_X_OVERLAP = 0.5  # boxes this much side by side (of the narrower one) that also overlap vertically
CHAR_OVERLAP = 0.3  # chars overlapping more than this (of the shorter one) are the same char read twice


class MeikiOcrProvider(OcrProvider):
    """
    An OCR provider that uses the high-performance meikiocr library.
    This provider is specifically optimized for recognizing Japanese text from video games.
    """
    NAME = "meikiocr (local)"

    def __init__(self):
        """
        Initializes the provider by creating an instance of the MeikiOCR client.
        The library handles the model downloading and session management internally.
        """
        logger.info(f"initializing {self.NAME} provider...")
        self.ocr_client = None
        try:
            self.ocr_client = MeikiOCR()
            logger.info(f"{self.NAME} initialized successfully, running on: {self.ocr_client.active_provider}")

        except Exception as e:
            logger.error(f"failed to initialize {self.NAME}: {e}", exc_info=True)

    def scan(self, image: Image.Image) -> Optional[List[Paragraph]]:
        """
        Performs OCR on the given image by calling the meikiocr library.
        """
        if not self.ocr_client:
            logger.error(f"{self.NAME} was not initialized correctly. Cannot perform scan.")
            return None

        try:
            image_np_rgb = np.array(image.convert("RGB"))
            img_height, img_width = image_np_rgb.shape[:2]

            if img_width == 0 or img_height == 0:
                logger.error("invalid image dimensions received.")
                return None

            # --- 1. Run the entire OCR pipeline with a single library call ---
            ocr_results = self.ocr_client.run_ocr(
                image_np_rgb,
                det_threshold=DET_CONFIDENCE_THRESHOLD,
                rec_threshold=REC_CONFIDENCE_THRESHOLD,
                punct_conf_factor=0.2
            )

            # --- 2. Transform the library's output to MeikiPop's format ---
            return self._to_meikipop_paragraphs(ocr_results, img_width, img_height)

        except Exception as e:
            logger.error(f"an error occurred in {self.NAME}: {e}", exc_info=True)
            return None  # returning none indicates a failure.

    @staticmethod
    def _chars_box(chars):
        return (min(c['bbox'][0] for c in chars), min(c['bbox'][1] for c in chars),
                max(c['bbox'][2] for c in chars), max(c['bbox'][3] for c in chars))

    @staticmethod
    def _overlap(a1, a2, b1, b2):
        return max(0, min(a2, b2) - max(a1, b1)) / max(1e-6, min(a2 - a1, b2 - b1))

    def _merge_overlapping_columns(self, ocr_results: list) -> list:
        """Combine vertical lines that are two reads of the same column into one, keeping the more
        confident read of each character."""
        columns = [r for r in ocr_results if r.get('is_vertical') and r.get('chars')]
        others = [r for r in ocr_results if not (r.get('is_vertical') and r.get('chars'))]

        groups = []  # each: list of lines, merged transitively
        for line in columns:
            box = self._chars_box(line['chars'])
            touching = [g for g in groups if any(
                self._overlap(box[0], box[2], b[0], b[2]) >= SAME_COLUMN_X_OVERLAP
                and self._overlap(box[1], box[3], b[1], b[3]) > 0
                for b in (self._chars_box(other['chars']) for other in g))]
            merged_group = [line] + [l for g in touching for l in g]
            groups = [g for g in groups if g not in touching] + [merged_group]

        merged = []
        for group in groups:
            if len(group) == 1:
                merged.append(group[0])
                continue
            accepted = []
            for char in sorted((c for line in group for c in line['chars']), key=lambda c: c.get('conf', 0),
                               reverse=True):
                y1, y2 = char['bbox'][1], char['bbox'][3]
                if all(self._overlap(y1, y2, a['bbox'][1], a['bbox'][3]) <= CHAR_OVERLAP for a in accepted):
                    accepted.append(char)
            accepted.sort(key=lambda c: c['bbox'][1])
            merged.append({'text': ''.join(c['char'] for c in accepted), 'chars': accepted, 'is_vertical': True})
        return others + merged

    def _to_normalized_bbox(self, bbox_pixels: list, img_width: int, img_height: int) -> BoundingBox:
        """converts an [x1, y1, x2, y2] pixel bbox to a normalized meikipop BoundingBox."""
        x1, y1, x2, y2 = bbox_pixels
        box_w, box_h = x2 - x1, y2 - y1

        center_x = (x1 + box_w / 2) / img_width
        center_y = (y1 + box_h / 2) / img_height
        norm_w = box_w / img_width
        norm_h = box_h / img_height

        return BoundingBox(center_x, center_y, norm_w, norm_h)

    def _to_meikipop_paragraphs(self, ocr_results: list, img_width: int, img_height: int) -> List[Paragraph]:
        """converts the final meikiocr result list into meikipop's Paragraph format."""
        lines: List[Paragraph] = []
        for line_result in self._merge_overlapping_columns(ocr_results):
            full_text = line_result.get("text", "").strip()
            chars = line_result.get("chars", [])
            if not full_text or not chars or not JAPANESE_REGEX.search(full_text):
                continue

            # create word objects for each character (best for precise lookups).
            words_in_line: List[Word] = []
            for char_info in chars:
                char_box = self._to_normalized_bbox(char_info['bbox'], img_width, img_height)
                words_in_line.append(Word(text=char_info['char'], separator="", box=char_box))

            # meikiocr doesn't provide a line-level box, so we must compute it
            # by finding the union of all character boxes in the line.
            min_x = min(c['bbox'][0] for c in chars)
            min_y = min(c['bbox'][1] for c in chars)
            max_x = max(c['bbox'][2] for c in chars)
            max_y = max(c['bbox'][3] for c in chars)
            line_box = self._to_normalized_bbox([min_x, min_y, max_x, max_y], img_width, img_height)

            line = Paragraph(
                full_text=full_text,
                words=words_in_line,
                box=line_box,
                # meikiocr says which model read the line; fall back to the shape for older versions
                is_vertical=line_result.get('is_vertical', line_box.width * 1.5 < line_box.height)
            )
            lines.append(line)

        return group_lines_into_paragraphs(lines)
