# meikipop/ocr/providers/meikiocr/vertical.py
"""Read vertical Japanese with meikiocr's horizontal recognizer.

meikiocr's vertical recognition model is far less accurate than its horizontal one (~17% vs ~1% character
errors on the same sentences). Vertical text sits on a fixed grid of one-em cells, so a column can be cut
into its character cells and laid out as a horizontal line instead:
- small kana and 、。 sit top-right in a vertical cell but low / bottom-left in a horizontal one, so they're moved
- vertical-only forms (ー, brackets, ～, …, arrows) are the horizontal ones rotated 90°; cells that look like them
  get a second, upright read, accepted only if it gives one of those symbols
Measured on 80 subtitle sentences in three fonts at two sizes: 1.1% character errors (vs 19% before)."""
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DETECT_THRESHOLD = 0.5
VERTICAL_DETECT_THRESHOLD = 0.3  # the detector is less sure of vertical text; horizontal boxes keep 0.5
SMALL_AREA = 0.7  # small kana / punctuation: at most this share of a full-size glyph's area
SMALL_DROP = 0.16  # horizontal small kana sit this much (of the cell) lower than full-size ones
GAP = 0.05  # space between characters in the rebuilt line, of the line height
EDGE_MARGIN = 0.06  # above/below the rebuilt line
SIDE_MARGIN = 0.3  # left/right of the rebuilt line (a character right at the edge tends to get lost)

VERTICAL_FORMS = {'I': 'ー', '1': 'ー', '|': 'ー', '｜': 'ー', 'l': 'ー', '丨': 'ー', ':': '…', '︙': '…', '⋮': '…'}
FLAT_STROKES = set('一ー―－-─')
ROTATED_OK = set('ー―～〜…‥「」『』（）()《》〈〉【】［］｛｝＝<>＜＞→←↑↓')
BRACKETS = set('「」『』（）()《》〈〉【】［］｛｝')
NO_ROTATE = set('!！?？')
SUSPECT = set('ンく~!トリTJしr・一」「|I1l')  # what vertical-only forms tend to be misread as


def detect(client, image):
    """meikiocr's detection, keeping vertical boxes down to a lower confidence. Returns (horizontal, vertical)
    box lists, vertical boxes of the same column merged."""
    det_input, scale = client._preprocess_for_detection(image)
    _, boxes, scores = client._run_detection_inference(det_input, scale)
    height, width = image.shape[:2]
    horizontal, vertical = [], []
    for box, score in zip(boxes[0], scores[0]):
        x1, y1, x2, y2 = np.clip(box, 0, [width, height, width, height]).astype(int).tolist()
        if x2 <= x1 or y2 <= y1:
            continue
        if y2 - y1 > x2 - x1:
            if score > VERTICAL_DETECT_THRESHOLD:
                vertical.append([x1, y1, x2, y2])
        elif score > DETECT_THRESHOLD:
            horizontal.append([x1, y1, x2, y2])
    return horizontal, merge_columns(vertical)


def merge_columns(boxes):
    """Union boxes that cover the same column (side by side by at least half the narrower one, overlapping
    vertically) - the detector often returns a column twice."""
    boxes = [list(b) for b in boxes]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                x_overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) / max(1, min(a[2] - a[0], b[2] - b[0]))
                if x_overlap >= 0.5 and min(a[3], b[3]) > max(a[1], b[1]):
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


def ink_mask(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = bw == 0
    return dark if dark.mean() < 0.5 else ~dark  # text is the minority colour (dark-on-light or light-on-dark)


def _grid(rows, first, last, width):
    """Pitch and phase of the character grid whose cut lines land in the gaps between characters."""
    csum = np.concatenate([[0], np.cumsum(rows)])

    def cost(p, o):
        band = max(1, int(0.08 * p))
        cuts = np.round(np.arange(o, last + p, p)).astype(int)
        lo, hi = np.clip(cuts - band, 0, len(rows)), np.clip(cuts + band + 1, 0, len(rows))
        return ((csum[hi] - csum[lo]) / (hi - lo).clip(1)).mean()

    best = None
    for p in np.arange(0.85 * width, 1.45 * width, 1.0):  # coarse
        for o in np.arange(first - p, first + 0.01, 1.0):
            c = cost(p, o)
            if best is None or c < best[0] - 1e-9:
                best = (c, p, o)
    _, p0, o0 = best
    for p in np.arange(p0 - 1, p0 + 1.01, 0.25):  # fine
        for o in np.arange(o0 - 1, o0 + 1.01, 0.25):
            c = cost(p, o)
            if c < best[0] - 1e-9:
                best = (c, p, o)
    return best[1], best[2]


def cells_for_column(image, box):
    """Cut a vertical column into its character cells: [(y1, y2)], (x1, x2), in image coordinates."""
    height = image.shape[0]
    x1, y1, x2, y2 = box
    width = x2 - x1
    ya, yb = max(0, y1 - int(0.6 * width)), min(height, y2 + int(0.6 * width))  # boxes often cut the ends short
    rows = ink_mask(image[ya:yb, x1:x2]).sum(axis=1).astype(float)
    ink_rows = np.nonzero(rows)[0]
    if len(ink_rows) == 0:
        return [], (x1, x2)
    first, last = ink_rows[0], ink_rows[-1]
    pitch, offset = _grid(rows, first, last, width)
    cells = []
    for k in range(int((last - offset) / pitch) + 1):
        a, b = int(max(0, round(offset + k * pitch))), int(min(len(rows), round(offset + (k + 1) * pitch)))
        if b > a and rows[a:b].sum() > 0:
            cells.append((ya + a, ya + b))
    return cells, (x1, x2)


def rebuild_line(image, cells, x_range, rotate=()):
    """Lay a column's cells side by side as one horizontal line. Returns (line image, x span of each cell,
    [(cell index, shape)] of cells that might be rotated vertical-only forms)."""
    xa, xb = x_range
    cell_width = xb - xa
    if not cells:
        return None, [], []
    line_height = int(np.median([c2 - c1 for c1, c2 in cells]))
    info = []
    for c1, c2 in cells:
        cell = image[c1:c2, xa:xb].copy()
        ys, xs = np.nonzero(ink_mask(cell))
        info.append((cell, c2 - c1, (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1) if len(ys) else None))
    # reference size: the larger glyphs (small kana can be half of a kana-heavy line)
    sizes = [(b[1] - b[0], b[3] - b[2]) for _, _, b in info if b]
    ref_h = np.percentile([h for h, _ in sizes], 80) if sizes else line_height
    ref_w = np.percentile([w for _, w in sizes], 80) if sizes else cell_width

    def is_small(b):
        gh, gw = b[1] - b[0], b[3] - b[2]
        return gh <= 0.9 * ref_h and gw <= 0.9 * ref_w and gh * gw <= SMALL_AREA * ref_h * ref_w

    full = [((b[2] + b[3]) / 2 / cell_width, (b[0] + b[1]) / 2 / h) for _, h, b in info if b and not is_small(b)]
    full_x, full_y = (np.median([f[0] for f in full]), np.median([f[1] for f in full])) if full else (0.5, 0.5)

    pieces, spans, candidates, x = [], [], [], 0
    for k, (cell, cell_height, b) in enumerate(info):
        background = np.median(np.concatenate([cell[0], cell[-1], cell[:, 0], cell[:, -1]]), axis=0).astype(np.uint8)
        if b:
            gh, gw = b[1] - b[0], b[3] - b[2]
            centre_y = (b[0] + b[1]) / 2 / cell_height
            if gw <= 0.4 * ref_w and gh >= 0.45 * ref_h:
                candidates.append((k, 'tall'))
            elif gh <= 0.55 * ref_h and gw >= 0.45 * ref_w:
                candidates.append((k, 'flat_edge' if centre_y < 0.35 or centre_y > 0.65 else 'flat_mid'))
        if k in rotate and b:
            glyph = np.rot90(cell[b[0]:b[1], b[2]:b[3]], 1).copy()  # counter-clockwise: vertical form -> horizontal
            gh, gw = glyph.shape[:2]
            f = min(1.0, 0.9 * cell_height / gh, 0.9 * cell_width / gw)
            if f < 1.0:
                glyph = cv2.resize(glyph, (max(1, int(gw * f)), max(1, int(gh * f))))
                gh, gw = glyph.shape[:2]
            cell = np.empty_like(cell)
            cell[:] = background
            ty, tx = (cell_height - gh) // 2, (cell_width - gw) // 2
            cell[ty:ty + gh, tx:tx + gw] = glyph
        elif b and is_small(b):
            gy1, gy2, gx1, gx2 = b
            gh, gw = gy2 - gy1, gx2 - gx1
            glyph = cell[gy1:gy2, gx1:gx2].copy()
            if (gy1 + gy2) / 2 / cell_height < 0.3 and gh < 0.45 * ref_h:
                # 、。 sit at the top(-right) of a vertical cell and at the bottom-left of a horizontal one
                ty, tx = cell_height - gh - int(0.08 * cell_height), int(0.08 * cell_width)
            elif gh > 0.35 * ref_h:
                # small kana: under the full-size characters' centre line, lower in the cell
                ty = int(min(cell_height - gh, (full_y + SMALL_DROP) * cell_height - gh / 2))
                tx = int(full_x * cell_width - gw / 2)
            else:
                ty, tx = gy1, gx1
            cell[:] = background
            ty, tx = max(0, min(cell_height - gh, ty)), max(0, min(cell_width - gw, tx))
            cell[ty:ty + gh, tx:tx + gw] = glyph
        if cell_height != line_height:
            cell = cv2.resize(cell, (cell_width, line_height))
        pieces.append(cell)
        spans.append((x, x + cell_width))
        x += cell_width
        gap = int(round(GAP * line_height))
        if gap > 0:
            filler = np.empty((line_height, gap, 3), np.uint8)
            filler[:] = background
            pieces.append(filler)
            x += gap
    line = np.concatenate(pieces, axis=1)
    rows = np.nonzero(ink_mask(line).any(axis=1))[0]
    if len(rows):  # tight to the ink, like a detection box
        line = line[rows[0]:rows[-1] + 1]
    h = line.shape[0]
    edge, side = max(1, int(h * EDGE_MARGIN)), max(2, int(h * SIDE_MARGIN))
    out = np.empty((h + 2 * edge, line.shape[1] + 2 * side, 3), np.uint8)
    out[:] = np.median(line[0], axis=0)
    out[edge:edge + h, side:side + line.shape[1]] = line
    return out, [(a + side, b + side) for a, b in spans], candidates


def _read_cells(client, line, spans, rec_threshold):
    # one character per cell by construction: keep the most confident read in each
    result = client.run_recognition([line], conf_threshold=rec_threshold, punct_conf_factor=1.0)[0]
    best = {}
    for char in result['chars']:
        cx = (char['bbox'][0] + char['bbox'][2]) / 2
        k = min(range(len(spans)), key=lambda i: 0 if spans[i][0] <= cx < spans[i][1]
                else min(abs(cx - spans[i][0]), abs(cx - spans[i][1])))
        if k not in best or char['conf'] > best[k]['conf']:
            best[k] = char
    return best


def read_column(client, image, box, rec_threshold=0.1):
    """Read one vertical column. Returns a meikiocr-style result: {'text', 'chars': [{'char', 'bbox', 'conf'}],
    'is_vertical': True} with character boxes in image coordinates."""
    cells, x_range = cells_for_column(image, box)
    line, spans, candidates = rebuild_line(image, cells, x_range)
    if line is None:
        return {'text': '', 'chars': [], 'is_vertical': True}
    best = _read_cells(client, line, spans, rec_threshold)

    shapes = dict(candidates)
    rotate = {k for k in range(len(cells))
              if (k in shapes or k not in best or best[k]['char'] in SUSPECT)
              and best.get(k, {}).get('char') not in NO_ROTATE}
    if rotate:
        line2, spans2, _ = rebuild_line(image, cells, x_range, rotate=rotate)
        upright = _read_cells(client, line2, spans2, rec_threshold)
        for k in rotate:
            new, old = upright.get(k), best.get(k)
            if not new or new['char'] not in ROTATED_OK:
                continue
            if new['char'] in BRACKETS and shapes.get(k) == 'flat_mid':
                continue  # a flat stroke in the middle of the cell is 一, not a bracket
            if old is None or new['conf'] > old['conf']:
                best[k] = new

    chars = []
    for k in sorted(best):
        c1, c2 = cells[k]
        char = VERTICAL_FORMS.get(best[k]['char'], best[k]['char'])
        if char in FLAT_STROKES and char not in ('ー', '―'):
            ys = np.nonzero(ink_mask(image[c1:c2, x_range[0]:x_range[1]]))[0]
            if len(ys) and ys.max() - ys.min() + 1 <= 0.45 * (c2 - c1):
                centre = (ys.min() + ys.max()) / 2 / (c2 - c1)
                if centre > 0.62:
                    char = '「'  # vertical 「 is a flat stroke at the bottom of its cell
                elif centre < 0.38:
                    char = '」'  # and 」 one at the top
        chars.append({'char': char, 'bbox': [x_range[0], c1, x_range[1], c2], 'conf': best[k]['conf']})
    return {'text': ''.join(c['char'] for c in chars), 'chars': chars, 'is_vertical': True}
