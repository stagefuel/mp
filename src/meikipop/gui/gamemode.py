# meikipop/gui/gamemode.py
"""Steam Deck Game Mode housekeeping, run once a second on the Qt thread (see meikipop/gamescope.py).

- reloads ~/.config/meikipop/gamemode.ini (written by the meikipop Decky plugin) when it changes,
  and re-lays out the popup, so plugin sliders apply live
- pauses scanning while Steam's own UI (or anything but this game) is in front: gamescope's stream
  shows whatever is on screen, and the library/Quick Access menu shouldn't be OCR'd
- shows a sample lookup when the plugin touches gamemode-preview (its "Preview" button)
"""
import logging
import os

from PyQt6.QtCore import QTimer

from meikipop.config.config import config, GAMEMODE_PATH
from meikipop.gamescope import STEAM_UI_APPID, gamescope

logger = logging.getLogger(__name__)

PREVIEW_PATH = os.path.join(os.path.dirname(GAMEMODE_PATH), 'gamemode-preview')
PREVIEW_TEXT = '日本語を勉強しています'
PREVIEW_SECONDS = 6


class GameModeController:
    def __init__(self, shared_state, popup, lookup):
        self.shared_state = shared_state
        self.popup = popup
        self.lookup = lookup
        self.game_appid = self._env_appid()
        self.settings_mtime = self._mtime(GAMEMODE_PATH)
        self.preview_mtime = self._mtime(PREVIEW_PATH)
        self.last_focus = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        logger.info(f"Game Mode: this game is app {self.game_appid or '?'}")

    @staticmethod
    def _env_appid():
        for name in ('MEIKIPOP_APPID', 'SteamAppId', 'SteamGameId', 'STEAM_COMPAT_APP_ID'):
            try:
                value = int(os.environ.get(name, '0'))
            except ValueError:
                continue
            if value > 0:
                return value
        return None

    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    def start(self):
        self.timer.start(1000)

    def tick(self):
        try:
            self._check_settings()
            self._check_focus()
            self._check_preview()
        except Exception:
            logger.exception("Game Mode: housekeeping failed")

    def _check_settings(self):
        mtime = self._mtime(GAMEMODE_PATH)
        if mtime and mtime != self.settings_mtime:
            self.settings_mtime = config.load_gamemode_file()
            self.popup.reapply_settings()

    def _check_focus(self):
        focused = gamescope().focused_app()
        if focused is None:
            return
        elsewhere = focused == STEAM_UI_APPID or (self.game_appid is not None and focused != self.game_appid)
        if elsewhere != self.shared_state.auto_paused:
            logger.info(f"Game Mode: {'paused' if elsewhere else 'resumed'} (focused app {focused})")
        self.shared_state.auto_paused = elsewhere

    def _check_preview(self):
        mtime = self._mtime(PREVIEW_PATH)
        if mtime and mtime != self.preview_mtime:
            self.preview_mtime = mtime
            result = self.lookup.lookup(PREVIEW_TEXT, quiet=True)
            self.popup.show_preview(result, (PREVIEW_TEXT, 0), PREVIEW_SECONDS)
