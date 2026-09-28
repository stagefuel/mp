# meikipop/texthooker/feed.py
import logging
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from typing import Callable, List, Optional

from meikipop.config.config import config
from meikipop.ocr.interface import Paragraph
from meikipop.texthooker.server import TexthookerServer

logger = logging.getLogger(__name__)

JAPANESE_REGEX = re.compile(r'[぀-ゟ゠-ヿ一-龯]')
WHITESPACE_REGEX = re.compile(r'\s+')

GONE_AFTER_SCANS = 2  # a sent line must be missing this many scans in a row before its text counts as new again
SIMILAR_RATIO = 0.8  # ocr of the same line varies a little between scans (one char off in 6 is 0.83)
RESTART_CHECK_SECONDS = 30
RECENT_LINES = 3  # guards against a line flickering out of the ocr for a few scans and coming back


class TextFeed:
    """Turns the stream of OCR scans into a stream of new lines for a texthooker page.

    - a line is sent once it has read the same in `texthooker_stable_scans` scans in a row, so text that is
      still being typed out isn't sent half-finished
    - a sent line is not sent again while it stays on screen, even if the ocr of it wobbles a little
    - it must be gone for a couple of scans before the same text counts as a new line (a character saying
      はい twice), but near-copies of the last 3 sent lines are dropped anyway
    - if a sent line later grows (slow text reveal), only the added part is sent
    - nothing is ever replayed, so reloading the page never resends what was already read"""

    def __init__(self, fix_text: Optional[Callable[[str], str]] = None):
        self.server = TexthookerServer()
        self.fix_text = fix_text
        self._lock = threading.Lock()
        self._candidates = {}  # line -> scans in a row it has been seen
        self._visible = {}  # sent line still on screen -> scans in a row it has been missing
        self._recent = deque(maxlen=RECENT_LINES)
        self._last_lines: List[str] = []
        self._last_restart_check = 0.0
        self.reapply_settings()
        # the watchdog runs on its own timer so it also covers pauses and screens with nothing to scan
        self._watchdog_stop = threading.Event()
        threading.Thread(target=self._watchdog, daemon=True, name="TexthookerWatchdog").start()

    def _watchdog(self):
        while not self._watchdog_stop.wait(RESTART_CHECK_SECONDS):
            try:
                self._keep_server_alive()
            except Exception:
                logger.exception("Texthooker: watchdog error")

    def reapply_settings(self):
        if config.texthooker_enabled:
            if not self.server.running or self.server.port != config.texthooker_port:
                self.server.start(config.texthooker_port)
        elif self.server.running:
            self.server.stop()

    @property
    def active(self):
        return config.texthooker_enabled and self.server.running

    def _keep_server_alive(self):
        # if the server thread ever dies, start it again (at most every 30s)
        now = time.monotonic()
        if (config.texthooker_enabled and not self.server.running
                and now - self._last_restart_check >= RESTART_CHECK_SECONDS):
            self._last_restart_check = now
            logger.warning("Texthooker: server isn't running, restarting it.")
            self.server.start(config.texthooker_port)

    def process_scan(self, paragraphs: Optional[List[Paragraph]]):
        if not self.active:
            return
        lines = []
        for paragraph in self._reading_order(paragraphs or []):
            line = WHITESPACE_REGEX.sub('', paragraph.full_text)
            if len(line) < 2 or not JAPANESE_REGEX.search(line):
                continue
            if self.fix_text:
                line = self.fix_text(line)
            if line not in lines:
                lines.append(line)
        with self._lock:
            self._last_lines = lines
            self._update(lines)

    @staticmethod
    def _reading_order(paragraphs: List[Paragraph]) -> List[Paragraph]:
        """Text boxes in reading order: top to bottom for horizontal text, right to left for vertical text
        (decided by the majority, so a stray horizontal name tag doesn't flip a vertical page)."""
        vertical = sum(p.is_vertical for p in paragraphs) > len(paragraphs) / 2
        if vertical:
            return sorted(paragraphs, key=lambda p: (-round(p.box.center_x, 2),
                                                     p.box.center_y - p.box.height / 2))
        return sorted(paragraphs, key=lambda p: (round(p.box.center_y - p.box.height / 2, 2), p.box.center_x))

    def screen_unchanged(self):
        """The screen didn't change since the last scan, which the screenshot loop skips ocr for;
        it still counts as seeing the same lines again."""
        if not self.active:
            return
        with self._lock:
            self._update(self._last_lines)

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        return a == b or SequenceMatcher(None, a, b).ratio() >= SIMILAR_RATIO

    def _update(self, lines: List[str]):
        # lines sent earlier: still there (possibly partly, or grown), or gone?
        for sent in list(self._visible):
            if any(self._similar(sent, line) or sent in line or line in sent for line in lines):
                self._visible[sent] = 0
            else:
                self._visible[sent] += 1
                if self._visible[sent] >= GONE_AFTER_SCANS:
                    del self._visible[sent]

        candidates = {}
        for line in lines:
            grown_from = next((sent for sent in self._visible if line != sent and line.startswith(sent)), None)
            # already sent and still on screen (or a partial read of it)
            if not grown_from and any(self._similar(line, sent) or line in sent for sent in self._visible):
                continue
            seen = self._candidates.get(line, 0) + 1
            if seen < config.texthooker_stable_scans:
                candidates[line] = seen
                continue
            if grown_from:
                # the line kept being revealed after it was sent: send just the new part
                # (a single extra character is more likely the ocr picking up a stray mark)
                del self._visible[grown_from]
                if len(line) - len(grown_from) >= 2:
                    self._send(line[len(grown_from):], line)
            elif not any(self._similar(line, recent) for recent in self._recent):
                self._send(line, line)
            self._visible[line] = 0
        self._candidates = candidates

    def _send(self, text: str, full_line: str):
        self._recent.append(full_line)
        logger.info(f"Texthooker: {text}")
        self.server.broadcast(text)

    def stop(self):
        self._watchdog_stop.set()
        self.server.stop()
