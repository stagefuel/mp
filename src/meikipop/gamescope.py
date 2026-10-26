# meikipop/gamescope.py
"""Steam Deck Game Mode (gamescope) support - lookup popup only.

In Game Mode there is no desktop: gamescope runs two rootless XWaylands, `:0` for
Steam's own UI and `:1` for games, and composites them itself. meikipop is started
next to a game (see packaging/steamdeck/meikipop-gamescope) with the game's
environment, so DISPLAY is the game's server. From there:

- capture: gamescope publishes what it shows as a PipeWire node named `gamescope`;
  it is read directly (no xdg portal exists here), see screenshot/gamescope_capture.py.
  Overlays are not part of that stream, so the popup never ends up in the OCR.
- cursor: queried on the game's display, in the game window's coordinates, then mapped
  to the screen the way gamescope scales the window (fit + centre, i.e. letterboxed).
- popup: gamescope only draws extra windows that live on Steam's display and carry
  GAMESCOPE_EXTERNAL_OVERLAY; like mangoapp's HUD, it stretches them to the whole
  screen and never gives them input. So the popup is drawn inside one transparent
  full-screen host window there (GAMESCOPE_NO_FOCUS=1), and the overlay atom is only
  switched on while a lookup is showing.

Everything here works in "overlay space": the coordinates of Steam's display, which
is also the coordinate space of the Qt screen the popup host lives on.
"""
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

ENV_FLAG = 'MEIKIPOP_GAMESCOPE'
STEAM_UI_APPID = 769
IS_GAMESCOPE = os.environ.get(ENV_FLAG) == '1'
GAME_DISPLAY = os.environ.get('DISPLAY', ':1')
OVERLAY_DISPLAY = os.environ.get('MEIKIPOP_OVERLAY_DISPLAY', ':0')


class Gamescope:
    """X11 plumbing for Game Mode. One shared instance, safe to call from any thread."""

    def __init__(self):
        from Xlib import X, display as xdisplay
        self._X = X
        self._lock = threading.Lock()
        self._game = xdisplay.Display(GAME_DISPLAY)
        self._overlay = xdisplay.Display(OVERLAY_DISPLAY)
        self._a_focused = self._overlay.intern_atom('GAMESCOPE_FOCUSED_WINDOW')
        self._a_overlay = self._overlay.intern_atom('GAMESCOPE_EXTERNAL_OVERLAY')
        self._a_nofocus = self._overlay.intern_atom('GAMESCOPE_NO_FOCUS')
        self._rect = None          # focused game window on the game display: x, y, w, h
        self._rect_time = 0.0
        logger.info(f"Game Mode: game display {GAME_DISPLAY}, overlay display {OVERLAY_DISPLAY}")

    # --- geometry -----------------------------------------------------------------
    def overlay_size(self):
        with self._lock:
            s = self._overlay.screen()
            return s.width_in_pixels, s.height_in_pixels

    def _game_window_rect(self):
        """Where the focused game window sits on the game display (refreshed every second)."""
        now = time.monotonic()
        if self._rect and now - self._rect_time < 1.0:
            return self._rect
        rect = None
        try:
            prop = self._overlay.screen().root.get_full_property(self._a_focused, self._X.AnyPropertyType)
            if prop and prop.value:
                win = self._game.create_resource_object('window', int(prop.value[0]))
                geo = win.get_geometry()
                pos = win.translate_coords(self._game.screen().root, 0, 0)
                rect = (-pos.x, -pos.y, geo.width, geo.height)
        except Exception as e:  # window gone / not on this display
            logger.debug(f"Game Mode: focused window lookup failed: {e}")
        if not rect or rect[2] <= 1 or rect[3] <= 1:
            s = self._game.screen()
            rect = (0, 0, s.width_in_pixels, s.height_in_pixels)
        if rect != self._rect:
            logger.info(f"Game Mode: game window {rect[2]}x{rect[3]} at {rect[0]},{rect[1]}")
        self._rect, self._rect_time = rect, now
        return rect

    def game_to_overlay(self, x, y):
        """gamescope fits the focused window into the output keeping its aspect ratio, centred."""
        gx, gy, gw, gh = self._game_window_rect()
        s = self._overlay.screen()
        ow, oh = s.width_in_pixels, s.height_in_pixels
        scale = min(ow / gw, oh / gh)
        off_x, off_y = (ow - gw * scale) / 2, (oh - gh * scale) / 2
        return int(off_x + (x - gx) * scale), int(off_y + (y - gy) * scale)

    def cursor_pos(self):
        with self._lock:
            p = self._game.screen().root.query_pointer()
            return self.game_to_overlay(p.root_x, p.root_y)

    def focused_app(self):
        """Steam app id gamescope is showing (769 = Steam's own UI), or None."""
        with self._lock:
            try:
                a = self._overlay.intern_atom('GAMESCOPE_FOCUSED_APP')
                prop = self._overlay.screen().root.get_full_property(a, self._X.AnyPropertyType)
                return int(prop.value[0]) if prop and prop.value else None
            except Exception:
                return None

    def focusable_apps(self):
        """App ids of the games gamescope currently has windows for (None if unreadable)."""
        with self._lock:
            try:
                a = self._overlay.intern_atom('GAMESCOPE_FOCUSABLE_APPS')
                prop = self._overlay.screen().root.get_full_property(a, self._X.AnyPropertyType)
                return [int(v) for v in prop.value] if prop else []
            except Exception:
                return None

    def claim_instance(self, appid):
        """One Game Mode meikipop per game: owns the X selection MEIKIPOP_GAMESCOPE_<appid> on Steam's
        display. Works across sandboxes (Flatpak has its own process list); the X server drops the claim
        as soon as the owner dies. False if another instance holds it."""
        with self._lock:
            atom = self._overlay.intern_atom(f'MEIKIPOP_GAMESCOPE_{appid}')
            if self._overlay.get_selection_owner(atom) != self._X.NONE:
                return False
            self._claim_window = self._overlay.screen().root.create_window(-10, -10, 1, 1, 0, self._overlay.screen().root_depth)
            self._claim_window.set_selection_owner(atom, self._X.CurrentTime)
            self._overlay.flush()
            return self._overlay.get_selection_owner(atom) == self._claim_window

    # --- overlay window -------------------------------------------------------------
    def prepare_overlay_window(self, window_id):
        """Before the host is mapped: never focusable, overlay off until something is shown."""
        with self._lock:
            from Xlib import Xatom
            win = self._overlay.create_resource_object('window', int(window_id))
            win.change_property(self._a_nofocus, Xatom.CARDINAL, 32, [1])
            win.change_property(self._a_overlay, Xatom.CARDINAL, 32, [0])
            self._overlay.flush()

    def set_overlay_visible(self, window_id, visible):
        with self._lock:
            from Xlib import Xatom
            win = self._overlay.create_resource_object('window', int(window_id))
            win.change_property(self._a_overlay, Xatom.CARDINAL, 32, [1 if visible else 0])
            self._overlay.flush()


_instance = None


def gamescope():
    global _instance
    if _instance is None:
        _instance = Gamescope()
    return _instance
