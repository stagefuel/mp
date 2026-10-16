# meikipop/utils/autostart.py
"""Start meikipop when you log in: a value under the registry's Run key on windows, an autostart .desktop file
on linux. Started that way it gets --background (on windows its console window starts minimized).
`sync()` runs at every start, so the entry follows the program when an update renames or moves it."""
import logging
import os
import shlex
import sys

from meikipop.config.config import IS_LINUX, IS_WINDOWS

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "meikipop"
FLATPAK_APP_ID = "io.github.stagefuel.meikipop"


def supported():
    return IS_WINDOWS or IS_LINUX


def _command():
    """The command line that starts this copy of meikipop, as a list."""
    if os.environ.get('FLATPAK_ID'):
        return ['flatpak', 'run', FLATPAK_APP_ID, '--background']
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--background']
    return [sys.executable, '-m', 'meikipop.main', '--background']


def _desktop_file():
    # in the flatpak, XDG_CONFIG_HOME is the app's own dir; autostart has to go in the real one
    if os.environ.get('FLATPAK_ID'):
        config_home = os.path.expanduser('~/.config')
    else:
        config_home = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(config_home, 'autostart', 'meikipop.desktop')


def _windows_command_line():
    import subprocess
    return subprocess.list2cmdline(_command())


def is_registered():
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
                return bool(value)
        except OSError:
            return False
    if IS_LINUX:
        return os.path.exists(_desktop_file())
    return False


def _register():
    if IS_WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _windows_command_line())
    elif IS_LINUX:
        path = _desktop_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = ("[Desktop Entry]\n"
                   "Type=Application\n"
                   "Name=meikipop\n"
                   "Comment=Japanese OCR popup dictionary\n"
                   f"Exec={' '.join(shlex.quote(part) for part in _command())}\n"
                   "Icon=io.github.stagefuel.meikipop\n"
                   "Terminal=false\n"
                   "X-GNOME-Autostart-enabled=true\n")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)


def _unregister():
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
    elif IS_LINUX:
        try:
            os.remove(_desktop_file())
        except FileNotFoundError:
            pass


def sync(enabled):
    """Make the login entry match the setting (and point at this copy of meikipop). Never raises."""
    if not supported():
        return
    try:
        if enabled:
            _register()
        elif is_registered():
            _unregister()
    except Exception as e:
        logger.warning(f"Run on startup: couldn't update the login entry: {e}")


def minimize_console():
    """--background on windows: the console window that comes with the exe starts minimized."""
    if not IS_WINDOWS:
        return
    import ctypes
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
