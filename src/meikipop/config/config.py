# meikipop/config/config.py
import configparser
import logging
import os
import sys

from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

APP_NAME = "meikipop"
APP_VERSION = "2.0.6-fork.2-linux-preview.1"
MAX_DICT_ENTRIES = 10
IS_LINUX = sys.platform.startswith('linux')
IS_WINDOWS = sys.platform.startswith('win')
IS_MACOS = sys.platform.startswith('darwin')
# todo should we use this instead?: IS_WAYLAND = IS_LINUX and bool(os.environ.get('WAYLAND_DISPLAY'))
IS_WAYLAND = IS_LINUX and os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'

# Steam Deck Game Mode (see meikipop/gamescope.py): plain X11 on the game's display
from meikipop.gamescope import IS_GAMESCOPE
if IS_GAMESCOPE:
    IS_WAYLAND = False

# Force xwayland so windows can pop up in arbitary locations
if IS_WAYLAND:
    os.environ['QT_QPA_PLATFORM'] = 'xcb'

# default popup font: one that ships with each OS and has Japanese glyphs
DEFAULT_FONT = 'Segoe UI' if IS_WINDOWS else 'Hiragino Sans' if IS_MACOS else 'Noto Sans CJK JP'

CONFIG_PATH = paths.config_path
GAMEMODE_PATH = os.path.join(os.path.dirname(CONFIG_PATH), 'gamemode.ini')
DICT_PATH = paths.dictionary_path

class Config:
    _instance = None

    _SCHEMA = {
        'Settings': {
            'hotkey': 'shift',
            'scan_region': 'region',
            'max_lookup_length': 25,
            'frequency_list_path': '',
            'glens_low_bandwidth': False,
            'ocr_provider': 'meikiocr (local)',
            'auto_scan_mode': True,
            'auto_scan_mode_lookups_without_hotkey': True,
            'auto_scan_interval_seconds': 0.5,
            'auto_scan_on_mouse_move': True,
            'magpie_compatibility': True,
            'texthooker_enabled': False,
            'texthooker_port': 9001,
            'texthooker_stable_scans': 2,
            'check_for_updates': True,
            'run_on_startup': False,
            'per_game_scan_area': True,
            'pause_outside_games': False,
            'copy_line_hotkey': 'ctrl+alt+c',
            'last_scan_area': '',
            'validated_dict_ts': -1
        },
        'Theme': {
            'theme_name': 'Default',
            'font_family': DEFAULT_FONT,
            'font_size_definitions': 26,
            'font_size_header': 32,
            'compact_mode': True,
            'show_all_glosses': False,
            'show_deconjugation': False,
            'show_pos': False,
            'show_tags': False,
            'show_frequency': False,
            'show_kanji': True,
            'show_examples': True,
            'show_components': True,
            'color_background': '#f0f0f0',
            'color_foreground': '#2e2e2e',
            'color_highlight_word': '#03a9f4',
            'color_highlight_reading': '#2e2e2e',
            'background_opacity': 211,
            'popup_position_mode': 'always_below',
            'popup_layout': 'jl',
            'popup_requires_mouse_move': True,
            'lock_on_hotkey_double_tap': True,
            'color_deconjugation': '#4CAF50',
            'color_frequency': '#FFFF00',
            'color_dictionary': '#ADD8E6',
            'popup_max_width_percent': 40,
            'popup_max_height_percent': 40
        },
        'Anki': {
            'anki_enabled': True,
            'anki_connect_url': 'http://127.0.0.1:8765',
            'anki_deck': 'Default',
            'anki_note_type': 'Basic',
            'anki_fields': 'Front=word;Back=reading_definitions',
            'anki_tags': '',
            'anki_allow_duplicates': False
        }
    }

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    @staticmethod
    def _parse(parser, section, key, default):
        if isinstance(default, bool):
            return parser.getboolean(section, key)
        if isinstance(default, int):
            return parser.getint(section, key)
        if isinstance(default, float):
            return parser.getfloat(section, key)
        return parser.get(section, key)

    def _load(self):
        parser = configparser.ConfigParser()
        found = parser.read(CONFIG_PATH, encoding='utf-8')

        for section, settings in self._SCHEMA.items():
            for key, default in settings.items():
                val = self._parse(parser, section, key, default) if parser.has_option(section, key) else default
                setattr(self, key, val)

        self.is_enabled = True
        if found:
            logger.info(f"Configuration loaded from '{CONFIG_PATH}'.")
        else:
            logger.info(f"No configuration found at '{CONFIG_PATH}'. A new one will be created with default values.")

    # Game Mode is lookup-only and shares config.ini with the desktop meikipop, so these
    # are forced in memory and nothing is ever written back.
    _GAMESCOPE_OVERRIDES = {
        'scan_region': '1', 'per_game_scan_area': False, 'pause_outside_games': False,
        'texthooker_enabled': False, 'anki_enabled': False, 'check_for_updates': False,
        'run_on_startup': False, 'lock_on_hotkey_double_tap': False, 'magpie_compatibility': False,
    }

    def apply_gamescope_overrides(self):
        for key, value in self._GAMESCOPE_OVERRIDES.items():
            setattr(self, key, value)
        logger.info("Game Mode: lookup-only settings applied (not saved)")
        self.load_gamemode_file()

    # Game Mode's own settings, written by the meikipop Decky plugin: popup look/size only, layered over
    # config.ini so the desktop meikipop is never affected. [GameMode] enabled = false pauses lookups.
    GAMEMODE_KEYS = ('font_size_definitions', 'font_size_header', 'popup_max_width_percent',
                     'popup_max_height_percent', 'background_opacity', 'compact_mode', 'popup_position_mode',
                     'popup_layout', 'show_kanji', 'show_examples', 'show_frequency', 'show_deconjugation',
                     'theme_name', 'font_family', 'auto_scan_mode_lookups_without_hotkey', 'hotkey')

    def load_gamemode_file(self):
        """(Re)read gamemode.ini; returns its mtime, or 0 if there is none."""
        try:
            mtime = os.path.getmtime(GAMEMODE_PATH)
        except OSError:
            return 0
        parser = configparser.ConfigParser()
        try:
            parser.read(GAMEMODE_PATH, encoding='utf-8')
            for section, settings in self._SCHEMA.items():
                for key, default in settings.items():
                    if key in self.GAMEMODE_KEYS and parser.has_option(section, key):
                        setattr(self, key, self._parse(parser, section, key, default))
            self.is_enabled = parser.getboolean('GameMode', 'enabled', fallback=True)
            logger.info(f"Game Mode: settings from {GAMEMODE_PATH} (enabled={self.is_enabled})")
        except (configparser.Error, ValueError) as e:
            logger.warning(f"Game Mode: ignoring a bad {GAMEMODE_PATH}: {e}")
        return mtime

    def save(self):
        if IS_GAMESCOPE:
            logger.info("Game Mode: settings are not saved")
            return
        parser = configparser.ConfigParser()
        for section, settings in self._SCHEMA.items():
            parser.add_section(section)
            for key in settings:
                val = getattr(self, key)
                parser.set(section, key, str(val).lower() if isinstance(val, bool) else str(val))

        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            parser.write(f)
        logger.info(f"Settings saved to '{CONFIG_PATH}'.")


config = Config()
if IS_GAMESCOPE:
    config.apply_gamescope_overrides()