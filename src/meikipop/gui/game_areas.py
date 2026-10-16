# meikipop/gui/game_areas.py
"""Per-game scan areas, and pausing outside games.

Choosing a scan area (tray → Scan Area) saves it for the game you were last in; switching back to that game later
puts its area back. A "game" is any program you've saved a scan area for, so with "Pause Outside Games" on, meikipop
only scans while one of them is in front."""
import json
import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal

from meikipop.config.config import config
from meikipop.gui.foreground import ForegroundWatcher
from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

AREAS_PATH = os.path.join(os.path.dirname(paths.config_path), 'game_areas.json')


class GameAreas(QObject):
    _app_changed = pyqtSignal(object)  # from the watcher thread
    paused_changed = pyqtSignal(bool)
    area_applied = pyqtSignal()  # a game's saved area was switched to (the tray updates its check marks)

    def __init__(self, screen_manager, shared_state, watcher=None):
        super().__init__()
        self.screen_manager = screen_manager
        self.shared_state = shared_state
        self.areas = self._load()
        self.watcher = watcher or ForegroundWatcher(on_change=self._app_changed.emit)
        self._app_changed.connect(self._on_app_changed)

    @staticmethod
    def _load():
        try:
            with open(AREAS_PATH, encoding='utf-8') as f:
                areas = json.load(f)
            return areas if isinstance(areas, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.warning(f"Game areas: couldn't read {AREAS_PATH}: {e}")
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(AREAS_PATH), exist_ok=True)
            with open(AREAS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.areas, f, ensure_ascii=False, indent=1)
        except OSError as e:
            logger.warning(f"Game areas: couldn't save {AREAS_PATH}: {e}")

    def start(self):
        if not ForegroundWatcher.supported():
            logger.info("Game areas: the focused window can't be seen in this session; per-game areas are off.")
            return
        self.watcher.start()
        self.update_pause()

    @property
    def current_game(self):
        """The program the user was last in, if a scan area is saved for it."""
        app = self.watcher.app
        return app if app and app.key in self.areas else None

    def remember_region(self, monitor):
        self._remember({'area': dict(monitor)})

    def remember_screen(self, index):
        self._remember({'screen': int(index)})

    def _remember(self, entry):
        app = self.watcher.app
        if app is None or not self.watcher.is_alive():
            return
        entry['name'] = app.name
        self.areas[app.key] = entry
        self._save()
        logger.info(f"Game areas: saved the scan area for '{app.name}'")
        self.update_pause()

    def forget_all(self):
        self.areas = {}
        self._save()
        self.update_pause()

    def _on_app_changed(self, app):
        entry = self.areas.get(app.key)
        if entry and config.per_game_scan_area:
            if 'area' in entry:
                self.screen_manager.monitor = dict(entry['area'])
                config.scan_region = 'region'
            else:
                self.screen_manager.set_scan_screen(entry['screen'])
                config.scan_region = str(entry['screen'])
            self.screen_manager.force_screenshot_trigger()
            self.area_applied.emit()
            logger.info(f"Game areas: switched to the scan area saved for '{entry.get('name', app.name)}'")
        self.update_pause()

    def update_pause(self):
        """Pause while the user isn't in a game (only with that setting on and at least one game saved)."""
        app = self.watcher.app
        paused = bool(config.pause_outside_games and self.areas and self.watcher.is_alive()
                      and (app is None or app.key not in self.areas))
        if paused != self.shared_state.auto_paused:
            self.shared_state.auto_paused = paused
            logger.info("Paused: not in a game." if paused else "Resumed: in a game.")
            if not paused:
                self.screen_manager.force_screenshot_trigger()
                self.shared_state.screenshot_trigger_event.set()
            self.paused_changed.emit(paused)
