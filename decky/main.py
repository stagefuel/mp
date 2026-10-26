# meikipop Decky plugin - backend (runs as the deck user)
#
# Game Mode meikipop (meikipop --gamescope, started by ~/.local/bin/meikipop-gamescope from a
# game's launch options) layers ~/.config/meikipop/gamemode.ini over its normal config and
# re-reads it every second, so everything here applies live. Touching gamemode-preview makes it
# show a sample popup. The desktop meikipop never reads gamemode.ini.
import configparser
import os
from pathlib import Path

import decky  # type: ignore

HOME = Path(decky.DECKY_USER_HOME)
CONFIG_DIR = HOME / ".config" / "meikipop"
GAMEMODE_INI = CONFIG_DIR / "gamemode.ini"
PREVIEW = CONFIG_DIR / "gamemode-preview"
WRAPPER = HOME / ".local" / "bin" / "meikipop-gamescope"

# key -> (section, default, type); defaults match meikipop's own
SETTINGS = {
    "enabled": ("GameMode", True, bool),
    "font_size_definitions": ("Theme", 26, int),
    "font_size_header": ("Theme", 32, int),
    "popup_max_width_percent": ("Theme", 40, int),
    "popup_max_height_percent": ("Theme", 40, int),
    "background_opacity": ("Theme", 211, int),
    "compact_mode": ("Theme", True, bool),
    "auto_scan_mode_lookups_without_hotkey": ("Settings", True, bool),
}


def _read():
    parser = configparser.ConfigParser()
    parser.read(GAMEMODE_INI, encoding="utf-8")
    return parser


class Plugin:
    async def get_settings(self):
        parser = _read()
        out = {}
        for key, (section, default, kind) in SETTINGS.items():
            try:
                if not parser.has_option(section, key):
                    out[key] = default
                elif kind is bool:
                    out[key] = parser.getboolean(section, key)
                else:
                    out[key] = parser.getint(section, key)
            except ValueError:
                out[key] = default
        return out

    async def set_setting(self, key, value):
        if key not in SETTINGS:
            return False
        section, _, kind = SETTINGS[key]
        parser = _read()
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, str(bool(value)).lower() if kind is bool else str(int(value)))
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = GAMEMODE_INI.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            parser.write(f)
        os.replace(tmp, GAMEMODE_INI)  # meikipop never sees a half-written file
        return True

    async def reset_settings(self):
        GAMEMODE_INI.unlink(missing_ok=True)
        return True

    async def preview(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PREVIEW.touch()
        os.utime(PREVIEW)
        return True

    async def status(self):
        """What the panel needs to know: the wrapper path, and which meikipop it would run."""
        binary = HOME / "Applications" / "meikipop" / "meikipop"
        flatpak = Path("/var/lib/flatpak/app/io.github.stagefuel.meikipop").exists() or \
            (HOME / ".local/share/flatpak/app/io.github.stagefuel.meikipop").exists()
        return {
            "wrapper": str(WRAPPER),
            "wrapper_installed": WRAPPER.is_file() and os.access(WRAPPER, os.X_OK),
            "meikipop": "custom" if (CONFIG_DIR / "gamescope.cmd").is_file() else
                        "binary" if binary.is_file() else "flatpak" if flatpak else "",
        }

    async def _main(self):
        decky.logger.info("meikipop plugin loaded")

    async def _unload(self):
        pass
