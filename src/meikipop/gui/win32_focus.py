# meikipop/gui/win32_focus.py
"""Windows only: make the locked popup the foreground window, and hand the foreground back afterwards.

Games that read the mouse through raw input or DirectInput still get wheel/clicks that the low-level hook
swallows, but only while they are the foreground window - so the locked popup has to take the foreground."""
import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def get_foreground():
    return user32.GetForegroundWindow()


def _set_noactivate(hwnd, enabled):
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    style = (style | WS_EX_NOACTIVATE) if enabled else (style & ~WS_EX_NOACTIVATE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)


def _force_foreground(hwnd):
    """SetForegroundWindow only works for the foreground process; attaching to the current foreground
    window's input queue for the call lifts that restriction (no synthetic key presses needed)."""
    foreground = user32.GetForegroundWindow()
    if foreground == hwnd:
        return True
    this_thread = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = bool(foreground_thread and foreground_thread != this_thread
                    and user32.AttachThreadInput(this_thread, foreground_thread, True))
    try:
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(this_thread, foreground_thread, False)


def take_foreground(hwnd):
    """Activate hwnd, returning the window that had the foreground before."""
    previous = user32.GetForegroundWindow()
    _set_noactivate(hwnd, False)
    ok = _force_foreground(hwnd)
    logger.info(f"Popup took the foreground: {ok}")
    return previous


def give_back_foreground(hwnd, previous):
    """If hwnd still has the foreground, return it to previous (the game)."""
    try:
        if previous and user32.GetForegroundWindow() == hwnd and user32.IsWindow(previous):
            _force_foreground(previous)
    finally:
        _set_noactivate(hwnd, True)
