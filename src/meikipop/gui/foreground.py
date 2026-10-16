# meikipop/gui/foreground.py
"""Which program the user is in: the foreground window's program, ignoring meikipop's own windows and the desktop
shell (taskbar, tray, desktop), so opening meikipop's tray menu or locking its popup doesn't count as leaving the
game. Used to remember a scan area per game and to pause outside games."""
import logging
import os
import threading
import time
from dataclasses import dataclass

from meikipop.config.config import IS_LINUX, IS_WINDOWS, IS_WAYLAND

logger = logging.getLogger(__name__)

POLL_SECONDS = 0.5

# focusing these doesn't mean the user left the game
_SHELL_PROGRAMS = {
    'explorer.exe', 'shellexperiencehost.exe', 'startmenuexperiencehost.exe', 'searchhost.exe',
    'searchapp.exe', 'lockapp.exe', 'textinputhost.exe', 'applicationframehost.exe',
    'plasmashell', 'kwin_wayland', 'kwin_x11', 'xfce4-panel', 'gnome-shell', 'xfdesktop', 'lxpanel', 'krunner',
}


@dataclass(frozen=True)
class App:
    key: str  # stable id: the program's path on windows, its window class on linux
    name: str  # for showing to the user


class _WindowsSource:
    def __init__(self):
        import ctypes
        import ctypes.wintypes
        self.ctypes = ctypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

    def current(self):
        """(App, pid) of the foreground window, or None."""
        ctypes = self.ctypes
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = ctypes.wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            path = buffer.value
        finally:
            self.kernel32.CloseHandle(handle)
        length = self.user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, title, length + 1)
        exe = os.path.basename(path)
        name = title.value.strip() or os.path.splitext(exe)[0]
        return App(key=path.lower(), name=name), pid.value, exe.lower()


class _X11Source:
    def __init__(self):
        from Xlib import X, display
        self.X = X
        self.display = display.Display()
        self.root = self.display.screen().root
        self.NET_ACTIVE_WINDOW = self.display.intern_atom('_NET_ACTIVE_WINDOW')
        self.NET_WM_PID = self.display.intern_atom('_NET_WM_PID')
        self.NET_WM_NAME = self.display.intern_atom('_NET_WM_NAME')
        self.UTF8_STRING = self.display.intern_atom('UTF8_STRING')

    def current(self):
        active = self.root.get_full_property(self.NET_ACTIVE_WINDOW, self.X.AnyPropertyType)
        if not active or not active.value or not active.value[0]:
            return None
        window = self.display.create_resource_object('window', active.value[0])
        wm_class = window.get_wm_class()
        if not wm_class:
            return None
        pid_prop = window.get_full_property(self.NET_WM_PID, self.X.AnyPropertyType)
        pid = pid_prop.value[0] if pid_prop and len(pid_prop.value) else 0
        name_prop = window.get_full_property(self.NET_WM_NAME, self.UTF8_STRING)
        title = name_prop.value.decode('utf-8', 'replace') if name_prop and name_prop.value else ''
        program = (wm_class[1] or wm_class[0]).lower()
        return App(key=f"x11:{wm_class[0].lower()}:{wm_class[1].lower()}", name=title.strip() or program), \
            pid, program


class _KWinSource:
    """KDE Wayland: the focused window as reported by the KWin script in kwin_cursor (covers native windows too)."""

    def current(self):
        from meikipop.gui.kwin_cursor import kwin_cursor
        window = kwin_cursor.active_window
        if not window:
            return None
        instance, wm_class, caption, pid = window
        if not (instance or wm_class):
            return None
        program = (wm_class or instance).lower()
        return App(key=f"x11:{instance.lower()}:{wm_class.lower()}", name=caption.strip() or program), pid, program


def _kwin_active():
    from meikipop.gui.kwin_cursor import kwin_cursor
    return kwin_cursor.active


class ForegroundWatcher(threading.Thread):
    """Polls the foreground program and calls `on_change(app)` (on this thread) when the user switches to a
    different one. `app` is the last real program in the foreground, never meikipop or the shell."""

    def __init__(self, on_change=None, source=None):
        super().__init__(daemon=True, name="ForegroundWatcher")
        self.on_change = on_change
        self.app = None
        self._source = source
        self._running = True
        self._own_pids = {os.getpid(), os.getppid()}  # meikipop, and pyinstaller's onefile bootloader

    @staticmethod
    def supported():
        return IS_WINDOWS or (IS_LINUX and (not IS_WAYLAND or _kwin_active()))

    def _make_source(self):
        if IS_WINDOWS:
            return _WindowsSource()
        if IS_WAYLAND:
            return _KWinSource()
        return _X11Source()

    def poll(self):
        current = self._source.current()
        if current is None:
            return
        app, pid, program = current
        if pid in self._own_pids or program in _SHELL_PROGRAMS:
            return
        # by program, not window title: many games change their title as you play
        if self.app is None or app.key != self.app.key:
            self.app = app
            logger.info(f"Foreground: now in '{app.name}' ({app.key})")
            if self.on_change:
                self.on_change(app)

    def run(self):
        try:
            if self._source is None:
                self._source = self._make_source()
        except Exception as e:
            logger.warning(f"Foreground: can't watch the focused window here: {e}")
            return
        while self._running:
            try:
                self.poll()
            except Exception:
                logger.debug("Foreground: poll failed", exc_info=True)
            time.sleep(POLL_SECONDS)

    def stop(self):
        self._running = False
