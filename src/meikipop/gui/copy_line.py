# meikipop/gui/copy_line.py
"""The "copy line" hotkey: copies the ocr'd text under the mouse (or the whole scan area's text) to the
clipboard, with the same fixes the popup and texthooker use. A global hotkey through pynput, so it works while the
game is focused (on wayland: over X11/XWayland windows only)."""
import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QToolTip
from pynput import keyboard as pynput_keyboard

from meikipop.config.config import config

logger = logging.getLogger(__name__)

_MODIFIERS = {'ctrl', 'alt', 'shift', 'cmd', 'win', 'super', 'alt_gr'}


def to_pynput(hotkey):
    """'ctrl+alt+c' -> '<ctrl>+<alt>+c' (pynput's format), or None if empty."""
    parts = [p.strip().lower() for p in hotkey.split('+') if p.strip()]
    if not parts:
        return None
    converted = []
    for part in parts:
        if part in ('win', 'super'):
            part = 'cmd'
        converted.append(f'<{part}>' if part in _MODIFIERS or len(part) > 1 else part)
    return '+'.join(converted)


class CopyLine(QObject):
    _requested = pyqtSignal()

    def __init__(self, hit_scanner, fix_text=None):
        super().__init__()
        self.hit_scanner = hit_scanner
        self.fix_text = fix_text
        self.listener = None
        self._requested.connect(self.copy)

    def start(self):
        self.stop()
        combo = to_pynput(config.copy_line_hotkey or '')
        if not combo:
            return
        try:
            self.listener = pynput_keyboard.GlobalHotKeys({combo: self._requested.emit})
            self.listener.start()
            logger.info(f"Copy line: hotkey {config.copy_line_hotkey}")
        except Exception as e:
            self.listener = None
            logger.warning(f"Copy line: can't use the hotkey '{config.copy_line_hotkey}': {e}")

    def stop(self):
        if self.listener:
            self.listener.stop()
            self.listener = None

    def copy(self):
        text = self.hit_scanner.text_at_mouse()
        if text and self.fix_text:
            try:
                text = self.fix_text(text)
            except Exception:
                logger.debug("Copy line: text fix failed", exc_info=True)
        if text:
            QApplication.clipboard().setText(text)
            logger.info(f"Copy line: copied {len(text)} characters")
            QToolTip.showText(QCursor.pos(), "Copied")
        else:
            QToolTip.showText(QCursor.pos(), "No text to copy")
