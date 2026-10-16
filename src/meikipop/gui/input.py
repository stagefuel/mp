# meikipop/gui/input.py
import ctypes
import ctypes.wintypes
import logging
import sys
import threading
import time

from pynput import mouse
from pynput import keyboard as pynput_keyboard

from meikipop.config.config import config, IS_LINUX, IS_MACOS, IS_WINDOWS
from meikipop.gui.kwin_cursor import kwin_cursor

if IS_LINUX:
    from Xlib import display as xlib_display
    from Xlib.error import XError
    from Xlib import X, XK
elif IS_MACOS:
    import Quartz
    from AppKit import NSEvent
else:
    import keyboard


logger = logging.getLogger(__name__)

# win32 messages seen by the low-level hooks
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
DOUBLE_TAP_SECONDS = 0.4  # two presses of the hotkey this close together lock/unlock the popup

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MOUSEWHEEL = 0x0201, 0x0202, 0x0207, 0x0208, 0x020A
VK_ESCAPE = 0x1B

class LinuxX11KeyboardController:
    def __init__(self, hotkey_str):
        self.hotkey_str = hotkey_str.lower()
        try:
            self.display = xlib_display.Display()
            self._setup_keycodes()
        except (XError, Exception) as e:
            logger.critical("Could not connect to X server. Is DISPLAY environment variable set? Error: %s", e)
            logger.critical("Meikipop cannot run without a graphical session.")
            sys.exit(1)

    def _setup_keycodes(self):
        self.modifier_groups = []
        modifier_map = {
            'shift': ['Shift_L', 'Shift_R'],
            'ctrl': ['Control_L', 'Control_R'],
            'alt': ['Alt_L', 'Alt_R']
        }
        hotkeys = self.hotkey_str.split('+')

        for key in hotkeys:
            target_keysyms = modifier_map.get(key)
            if not target_keysyms:
                logger.critical(f"Unsupported hotkey '{key}' for Linux/X11. Use 'shift', 'ctrl', or 'alt'.")
                sys.exit(1)
            group_keycodes = set()
            for keysym_str in target_keysyms:
                keysym = XK.string_to_keysym(keysym_str)
                if keysym:
                    keycode = self.display.keysym_to_keycode(keysym)
                    if keycode:
                        group_keycodes.add(keycode)

            if not group_keycodes:
                logger.critical(f"Could not find keycodes for hotkey '{key}'.")
                sys.exit(1)

            self.modifier_groups.append(group_keycodes)

    def is_hotkey_pressed(self) -> bool:
        try:
            key_map = self.display.query_keymap()
            for group in self.modifier_groups:
                group_is_pressed = False
                for keycode in group:
                    if (key_map[keycode // 8] >> (keycode % 8)) & 1:
                        group_is_pressed = True
                        break
                if not group_is_pressed:
                    return False
            return True
        except XError:
            return False


class WindowsKeyboardController:
    def __init__(self, hotkey_str):
        self.hotkey_str = hotkey_str.lower()

    def is_hotkey_pressed(self) -> bool:
        try:
            return keyboard.is_pressed(self.hotkey_str)
        except ImportError:
            logger.critical("FATAL: The 'keyboard' library failed to import a backend. This often means it needs to be run with administrator/sudo privileges.")
            sys.exit(1)
        except Exception:
            return False


class MacOSKeyboardController:
    def __init__(self, hotkey_str):
        self.hotkey_str = hotkey_str.lower()
        self.modifiers = self.hotkey_str.split('+')

        # Map common hotkey strings to macOS key codes
        key_mapping = {
            'shift': [56, 60],  # Left and Right Shift
            'ctrl': [59, 62],   # Left and Right Control
            'alt': [58, 61],    # Left and Right Option/Alt
            'cmd': [55, 54],    # Left and Right Command
        }

        for mod in self.modifiers:
            self.keycodes_to_check = key_mapping.get(mod, [])
            if not self.keycodes_to_check:
                logger.critical(
                    f"Unsupported hotkey '{self.hotkey_str}' for macOS. Use 'shift', 'ctrl', 'alt', or 'cmd'.")
                sys.exit(1)

    def is_hotkey_pressed(self) -> bool:
        try:
            # Get current modifier flags
            flags = NSEvent.modifierFlags()

            # Iterate through all required modifiers in the combo
            for mod in self.modifiers:
                if mod == 'shift':
                    if not (flags & (1 << 17) or flags & (1 << 18)):
                        return False
                elif mod == 'ctrl':
                    if not (flags & (1 << 12)):
                        return False
                elif mod == 'alt':
                    if not (flags & (1 << 19)):
                        return False
                elif mod == 'cmd':
                    if not (flags & (1 << 20)):
                        return False
            return True
        except Exception as e:
            logger.warning(f"Error checking hotkey state: {e}")
            return False

class X11InputGrabber(threading.Thread):
    """Linux/X11 (incl. XWayland): while the popup is up, grab the middle button - and Esc while it's locked -
    on the root window, so the X11 app under the cursor (e.g. a Wine game; many VNs hide their text box on middle
    click) doesn't act on them too. meikipop still sees them through pynput's record extension. Wayland-native
    apps can't be affected: X can't grab their input."""

    MIDDLE_BUTTON = 2

    def __init__(self):
        super().__init__(daemon=True, name="X11InputGrabber")
        self.want_button = False
        self.want_escape = False
        self._has_button = False
        self._has_escape = False
        self.display = xlib_display.Display()
        self.root = self.display.screen().root
        self.escape_keycode = self.display.keysym_to_keycode(XK.string_to_keysym('Escape'))

    def run(self):
        while True:
            try:
                self._apply()
                while self.display.pending_events():
                    self.display.next_event()  # grabbed presses are delivered to us; nothing to do with them
            except Exception:
                logger.exception("X11 input grab failed")
                time.sleep(1)
            time.sleep(0.01)

    def _apply(self):
        changed = False
        if self.want_button != self._has_button:
            if self.want_button:
                self.root.grab_button(self.MIDDLE_BUTTON, X.AnyModifier, False,
                                      X.ButtonPressMask | X.ButtonReleaseMask,
                                      X.GrabModeAsync, X.GrabModeAsync, X.NONE, X.NONE)
            else:
                self.root.ungrab_button(self.MIDDLE_BUTTON, X.AnyModifier)
            self._has_button = self.want_button
            changed = True
        if self.want_escape != self._has_escape and self.escape_keycode:
            if self.want_escape:
                self.root.grab_key(self.escape_keycode, X.AnyModifier, False, X.GrabModeAsync, X.GrabModeAsync)
            else:
                self.root.ungrab_key(self.escape_keycode, X.AnyModifier)
            self._has_escape = self.want_escape
            changed = True
        if changed:
            self.display.sync()  # surfaces a BadAccess (another client holds the grab) as an exception here


class InputLoop(threading.Thread):
    _mouse_controller = None

    def __init__(self, shared_state):
        super().__init__(daemon=True, name="InputLoop")
        self.shared_state = shared_state

        self.hotkey_str = config.hotkey.lower()
        if IS_LINUX:
            self.keyboard_controller = LinuxX11KeyboardController(self.hotkey_str)
        elif IS_MACOS:
            self.keyboard_controller = MacOSKeyboardController(self.hotkey_str)
        else: # IS_WINDOWS
            self.keyboard_controller = WindowsKeyboardController(self.hotkey_str)

        self.started_auto_mode = False

        self.popup = None
        self._suppressing_middle = False
        self._suppressing_escape = False

        self.x11_grabber = None
        if IS_LINUX:
            try:
                self.x11_grabber = X11InputGrabber()
            except Exception as e:
                logger.warning(f"Middle click/Esc won't be kept from the app under the popup: {e}")

    def attach_popup(self, popup):
        self.popup = popup

    # --- popup locking (middle click) and closing (esc / click outside) ---
    def _start_listeners(self):
        mouse_kwargs, key_kwargs = {}, {}
        if IS_WINDOWS:
            # on windows the hooks can swallow the input, so the game under the popup doesn't also react to it
            mouse_kwargs['win32_event_filter'] = self._win32_mouse_filter
            key_kwargs['win32_event_filter'] = self._win32_key_filter
        self.mouse_listener = mouse.Listener(on_click=self._on_click, **mouse_kwargs)
        self.key_listener = pynput_keyboard.Listener(on_press=self._on_key_press, **key_kwargs)
        self.mouse_listener.start()
        self.key_listener.start()

    def _popup_accepts_lock_toggle(self):
        return self.popup is not None and (self.popup.is_visible or self.shared_state.popup_locked)

    def _on_click(self, x, y, button, pressed):
        if not pressed or self.popup is None:
            return
        if button == mouse.Button.middle:
            if self._popup_accepts_lock_toggle():
                self.popup.lock_toggle_requested.emit()
        elif self.shared_state.popup_locked:
            self.popup.click_while_locked.emit()

    def _on_key_press(self, key):
        if key == pynput_keyboard.Key.esc and self.shared_state.popup_locked and self.popup is not None:
            self.popup.escape_pressed.emit()

    def _point_in_locked_popup(self, x, y):
        # both the hook's point and GetWindowRect are physical pixels (qt makes the process per-monitor dpi aware)
        hwnd = self.popup.native_handle
        if not hwnd:
            return False
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        return rect.left <= x < rect.right and rect.top <= y < rect.bottom

    def _win32_mouse_filter(self, msg, data):
        # while locked, clicks and scrolling inside the popup are handled here instead of relying on the
        # popup window getting them itself, and are swallowed so nothing underneath reacts
        if (self.shared_state.popup_locked and msg in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEWHEEL)
                and self._point_in_locked_popup(data.pt.x, data.pt.y)):
            if msg == WM_LBUTTONDOWN:
                self.popup.mine_click_requested.emit()
            elif msg == WM_MOUSEWHEEL:
                self.popup.scroll_requested.emit(ctypes.c_short(data.mouseData >> 16).value)
            self.mouse_listener.suppress_event()
        if msg == WM_MBUTTONDOWN and self._popup_accepts_lock_toggle():
            self._suppressing_middle = True
            self.popup.lock_toggle_requested.emit()
            self.mouse_listener.suppress_event()
        if msg == WM_MBUTTONUP and self._suppressing_middle:
            self._suppressing_middle = False
            self.mouse_listener.suppress_event()
        return True

    def _win32_key_filter(self, msg, data):
        if data.vkCode != VK_ESCAPE:
            return True
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN) and self.shared_state.popup_locked:
            self._suppressing_escape = True
            self.popup.escape_pressed.emit()
            self.key_listener.suppress_event()
        if msg in (WM_KEYUP, WM_SYSKEYUP) and self._suppressing_escape:
            self._suppressing_escape = False
            self.key_listener.suppress_event()
        return True

    def run(self):
        logger.debug("Input thread started.")
        last_mouse_pos = (0, 0)
        hotkey_was_pressed = False
        last_hotkey_press = 0.0
        self._start_listeners()

        if self.x11_grabber:
            self.x11_grabber.start()

        while self.shared_state.running:
            if self.x11_grabber:
                self.x11_grabber.want_button = not self.shared_state.paused and self._popup_accepts_lock_toggle()
                self.x11_grabber.want_escape = not self.shared_state.paused and self.shared_state.popup_locked
            if self.shared_state.paused:
                time.sleep(0.1)
                continue
            try:
                current_mouse_pos = self.get_mouse_pos()

                # double-tap the hotkey: lock/unlock the popup (a keyboard alternative to middle click, which
                # meikipop can't see over Wayland-native windows)
                try:
                    hotkey_down = self.keyboard_controller.is_hotkey_pressed()
                except Exception:
                    hotkey_down = False
                if hotkey_down and not hotkey_was_pressed:
                    now = time.monotonic()
                    if (config.lock_on_hotkey_double_tap and now - last_hotkey_press <= DOUBLE_TAP_SECONDS
                            and self._popup_accepts_lock_toggle()):
                        self.popup.lock_toggle_requested.emit()
                        now = 0.0  # a third tap starts a new double tap
                    last_hotkey_press = now

                # a locked popup freezes the current lookup: no new screenshots, ocr or hit scans
                if self.shared_state.popup_locked:
                    last_mouse_pos = current_mouse_pos
                    hotkey_was_pressed = hotkey_down
                    continue
                hotkey_is_pressed = hotkey_down

                # trigger screenshots + ocr in manual mode
                if hotkey_is_pressed and not hotkey_was_pressed and not config.auto_scan_mode:
                    logger.info(f"Input: Hotkey '{config.hotkey}' pressed. Triggering screenshot.")
                    self.shared_state.screenshot_trigger_event.set()

                # trigger initial screenshots + ocr in auto mode
                if not self.started_auto_mode and config.auto_scan_mode:
                    self.shared_state.screenshot_trigger_event.set()
                self.started_auto_mode = config.auto_scan_mode

                # trigger screenshots + ocr in auto-on-mouse-move mode
                if config.auto_scan_mode and config.auto_scan_on_mouse_move and current_mouse_pos != last_mouse_pos:
                    self.shared_state.screenshot_trigger_event.set()

                # trigger hit_scans + lookups
                if current_mouse_pos != last_mouse_pos:
                    self.shared_state.hit_scan_queue.trigger()

                if hotkey_was_pressed and not hotkey_is_pressed:
                    logger.info(f"Input: Hotkey '{config.hotkey}' released.")

                last_mouse_pos = current_mouse_pos
                hotkey_was_pressed = hotkey_is_pressed
                self.hotkey_is_pressed = hotkey_is_pressed
            except:
                logger.exception("An unexpected error occurred in the input loop. Continuing...")
            finally:
                time.sleep(0.01)
        logger.debug("Input thread stopped.")

    def is_virtual_hotkey_down(self):
        return self.keyboard_controller.is_hotkey_pressed() or (
                config.auto_scan_mode and config.auto_scan_mode_lookups_without_hotkey)

    def reapply_settings(self):
        logger.debug(f"InputLoop: Re-applying settings. New hotkey: '{config.hotkey}'.")
        self.hotkey_str = config.hotkey.lower()
        if IS_LINUX:
            self.keyboard_controller = LinuxX11KeyboardController(self.hotkey_str)
        elif IS_MACOS:
            self.keyboard_controller = MacOSKeyboardController(self.hotkey_str)
        else: # IS_WINDOWS
            self.keyboard_controller = WindowsKeyboardController(self.hotkey_str)

    @staticmethod
    def get_mouse_pos():
        # KDE Wayland: XWayland can't see the pointer over Wayland-native windows, KWin can
        if kwin_cursor.active:
            position = kwin_cursor.position
            if position is not None:
                return position
        try:
            pos = InputLoop._mouse_controller.position
        except Exception:
            InputLoop._mouse_controller = mouse.Controller()
            pos = InputLoop._mouse_controller.position
        # Convert floats to integers for QPoint compatibility
        return int(pos[0]), int(pos[1])
