# meikipop/config/config.py
import configparser
import logging
import os
import sys

from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

APP_NAME = "meikipop"
APP_VERSION = "2.0.5"
MAX_DICT_ENTRIES = 10
IS_LINUX = sys.platform.startswith('linux')
IS_WINDOWS = sys.platform.startswith('win')
IS_MACOS = sys.platform.startswith('darwin')
# todo should we use this instead?: IS_WAYLAND = IS_LINUX and bool(os.environ.get('WAYLAND_DISPLAY'))
IS_WAYLAND = IS_LINUX and os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'

# Force xwayland so windows can pop up in arbitary locations
if IS_WAYLAND:
    os.environ['QT_QPA_PLATFORM'] = 'xcb'

CONFIG_PATH = paths.config_path
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
            'validated_dict_ts': -1
        },
        'Theme': {
            'theme_name': 'Nazeka',
            'font_family': '',
            'font_size_definitions': 14,
            'font_size_header': 18,
            'compact_mode': True,
            'show_all_glosses': False,
            'show_deconjugation': False,
            'show_pos': False,
            'show_tags': False,
            'show_frequency': False,
            'show_kanji': True,
            'show_examples': True,
            'show_components': True,
            'color_background': '#2E2E2E',
            'color_foreground': '#F0F0F0',
            'color_highlight_word': '#88D8FF',
            'color_highlight_reading': '#90EE90',
            'background_opacity': 245,
            'popup_position_mode': 'always_below',
            'popup_layout': 'jl',
            'color_deconjugation': '#4CAF50',
            'color_frequency': '#FFFF00',
            'color_dictionary': '#ADD8E6',
            'popup_max_width_percent': 40,
            'popup_max_height_percent': 40
        },
        'Anki': {
            'anki_enabled': True,
            'anki_connect_url': 'http://127.0.0.1:8765',
            'anki_deck': 'VN vocab',
            'anki_note_type': 'core2.3k-anime-card',
            'anki_fields': 'Word=word;Reading=reading;Glossary=definitions',
            'anki_tags': '',
            'anki_allow_duplicates': False
        }
    }

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        parser = configparser.ConfigParser()
        found = parser.read(CONFIG_PATH, encoding='utf-8')

        for section, settings in self._SCHEMA.items():
            for key, default in settings.items():
                if parser.has_option(section, key):
                    if isinstance(default, bool):
                        val = parser.getboolean(section, key)
                    elif isinstance(default, int):
                        val = parser.getint(section, key)
                    elif isinstance(default, float):
                        val = parser.getfloat(section, key)
                    else:
                        val = parser.get(section, key)
                else:
                    val = default
                setattr(self, key, val)

        self.is_enabled = True
        if found:
            logger.info(f"Configuration loaded from '{CONFIG_PATH}'.")
        else:
            logger.info(f"No configuration found at '{CONFIG_PATH}'. A new one will be created with default values.")

    def save(self):
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