# meikipop Decky plugin - backend (runs as the deck user)
#
# Game Mode meikipop (meikipop --gamescope, started by ~/.local/bin/meikipop-gamescope from a
# game's launch options) layers ~/.config/meikipop/gamemode.ini over its normal config and
# re-reads it every second, so everything here applies live. Touching gamemode-preview makes it
# show a sample popup. The desktop meikipop never reads gamemode.ini.
import configparser
import os
import signal
import subprocess
from pathlib import Path

import decky  # type: ignore

HOME = Path(decky.DECKY_USER_HOME)
CONFIG_DIR = HOME / ".config" / "meikipop"
GAMEMODE_INI = CONFIG_DIR / "gamemode.ini"
PREVIEW = CONFIG_DIR / "gamemode-preview"
# the Flatpak keeps its config in its own sandbox dir; settings and preview go to both
FLATPAK_CONFIG_DIR = HOME / ".var" / "app" / "io.github.stagefuel.meikipop" / "config" / "meikipop"


def _config_dirs():
    dirs = [CONFIG_DIR]
    if FLATPAK_CONFIG_DIR.parent.parent.is_dir():  # the Flatpak has been run at least once
        dirs.append(FLATPAK_CONFIG_DIR)
    return dirs
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


def _procs():
    """(pid, argv) of every process we can read."""
    for entry in os.scandir("/proc"):
        if entry.name.isdigit():
            try:
                with open(f"/proc/{entry.name}/cmdline", "rb") as f:
                    argv = f.read().split(b"\0")
                yield int(entry.name), [a.decode("utf-8", "replace") for a in argv if a]
            except OSError:
                continue


def _game_reaper(appid):
    """pid of the running game's reaper (Steam's launcher process), or None."""
    for pid, argv in _procs():
        if len(argv) >= 3 and argv[0].endswith("reaper") and argv[1] == "SteamLaunch" \
                and argv[2] == f"AppId={appid}":
            return pid
    return None


def _meikipops(appid):
    """pids of Game Mode meikipops (and --attach wrappers) for this game."""
    out = []
    for pid, argv in _procs():
        for i, a in enumerate(argv[:-1]):
            if (a == "--appid" and argv[i + 1] == str(appid) and "--gamescope" in argv) or \
                    (a == "--attach" and argv[i + 1] == str(appid) and argv and "meikipop-gamescope" in " ".join(argv)):
                out.append(pid)
                break
    return out


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
        for d in _config_dirs():
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "gamemode.ini.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                parser.write(f)
            os.replace(tmp, d / "gamemode.ini")  # meikipop never sees a half-written file
        return True

    async def reset_settings(self):
        for d in _config_dirs():
            (d / "gamemode.ini").unlink(missing_ok=True)
        return True

    async def preview(self):
        for d in _config_dirs():
            d.mkdir(parents=True, exist_ok=True)
            (d / "gamemode-preview").touch()
            os.utime(d / "gamemode-preview")
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

    async def running(self, appid):
        """{game: is it running, meikipop: is a Game Mode meikipop running for it}"""
        return {"game": _game_reaper(appid) is not None, "meikipop": bool(_meikipops(appid))}

    async def start_for(self, appid):
        """Start meikipop next to an already running game (stops by itself when the game exits)."""
        reaper = _game_reaper(appid)
        if reaper is None or _meikipops(appid) or not WRAPPER.is_file():
            return False
        env = {}
        try:  # the game's own environment, like a launch-option start would have
            with open(f"/proc/{reaper}/environ", "rb") as f:
                for item in f.read().split(b"\0"):
                    key, _, value = item.decode("utf-8", "replace").partition("=")
                    if key and not key.startswith("LD_"):
                        env[key] = value
        except OSError:
            env = {"DISPLAY": ":1", "XDG_RUNTIME_DIR": "/run/user/1000", "HOME": str(HOME),
                   "PATH": "/usr/local/bin:/usr/bin:/bin"}
        # setsid -f: the wrapper is re-parented away from Decky at once (no zombie, survives plugin reloads)
        subprocess.run(["setsid", "-f", str(WRAPPER), "--attach", str(appid)], env=env, timeout=10,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        decky.logger.info(f"started meikipop for running app {appid}")
        return True

    async def stop_for(self, appid):
        pids = _meikipops(appid)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        if pids:
            decky.logger.info(f"stopped meikipop for app {appid} ({len(pids)} process(es))")
        return bool(pids)

    async def _main(self):
        decky.logger.info("meikipop plugin loaded")

    async def _unload(self):
        pass
