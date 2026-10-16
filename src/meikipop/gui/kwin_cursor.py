# meikipop/gui/kwin_cursor.py
"""Cursor position on KDE Plasma (Wayland) via a KWin script.

On Wayland meikipop runs under XWayland, which only sees the pointer while it's over an X11 window; over
Wayland-native windows (Firefox, Konsole, Okular, ...) the position it reads is frozen. KWin can tell: a tiny
KWin script, loaded over D-Bus, calls back into meikipop with `workspace.cursorPos` whenever the cursor
moves (tested: exact positions, ~10-25 ms). It also reports which window is focused (for per-game scan areas;
XWayland can't see Wayland-native windows either). The script lives only in the running KWin session and is
unloaded when meikipop exits."""
import atexit
import logging
import os
import threading

from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

BUS_NAME = 'io.github.meikipop.Cursor'
OBJECT_PATH = '/Cursor'
INTERFACE = 'io.github.meikipop.Cursor'
SCRIPT_NAME = 'meikipop-cursor'
SCRIPT = """// meikipop: report the cursor position to meikipop whenever it moves (Wayland-native windows included)
function send() {
    var p = workspace.cursorPos;
    callDBus("%s", "%s", "%s", "Moved", Math.round(p.x), Math.round(p.y));
}
workspace.cursorPosChanged.connect(send);
send();
// ... and the focused window, as X11 would describe it (instance, class), so saved games match on either
function activated(w) {
    if (!w) return;
    callDBus("%s", "%s", "%s", "Activated", String(w.resourceName || ""), String(w.resourceClass || ""),
             String(w.caption || ""), w.pid || 0);
}
workspace.windowActivated.connect(activated);
activated(workspace.activeWindow);
""" % ((BUS_NAME, OBJECT_PATH, INTERFACE) * 2)
INTROSPECTION = """<node><interface name="%s"><method name="Moved">
<arg type="i" direction="in"/><arg type="i" direction="in"/></method><method name="Activated">
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="i" direction="in"/>
</method></interface></node>""" % INTERFACE


class KWinCursor:
    def __init__(self):
        self._position = None
        self._active_window = None  # (instance, class, caption, pid)
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.active = False
        self._loop = None

    def start(self) -> bool:
        try:
            from gi.repository import Gio, GLib  # noqa: F401 - present wherever Wayland capture works
        except ImportError:
            logger.info("KWin cursor: PyGObject isn't available, using XWayland's cursor position.")
            return False
        threading.Thread(target=self._run, daemon=True, name="KWinCursor").start()
        if not self._ready.wait(5) or not self.active:
            logger.warning("KWin cursor: couldn't set up the KWin script; the cursor position is only known over "
                           "X11/XWayland windows.")
            return False
        atexit.register(self.stop)
        logger.info("KWin cursor: following the cursor through KWin (works over Wayland-native windows).")
        return True

    @property
    def position(self):
        with self._lock:
            return self._position

    @property
    def active_window(self):
        with self._lock:
            return self._active_window

    def _run(self):
        from gi.repository import Gio, GLib
        context = GLib.MainContext.new()
        context.push_thread_default()
        try:
            self._loop = GLib.MainLoop.new(context, False)
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
            connection.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, None, None)
            reply = connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                                         'RequestName', GLib.Variant('(su)', (BUS_NAME, 4)),  # 4 = do not queue
                                         None, Gio.DBusCallFlags.NONE, -1, None)
            if reply.unpack()[0] not in (1, 4):  # primary owner / already owner
                raise RuntimeError(f"the D-Bus name {BUS_NAME} is taken (another meikipop running?)")
            self._connection = connection
            self._load_script()
            self.active = True
        except Exception as e:
            logger.warning(f"KWin cursor: {e}")
            self._ready.set()
            context.pop_thread_default()
            return
        self._ready.set()
        try:
            self._loop.run()
        finally:
            context.pop_thread_default()

    def _on_call(self, connection, sender, path, interface, method, params, invocation):
        if method == 'Moved':
            x, y = params.unpack()
            with self._lock:
                self._position = (x, y)
        elif method == 'Activated':
            with self._lock:
                self._active_window = params.unpack()
        invocation.return_value(None)

    def _scripting(self, method, args, reply_type=None):
        from gi.repository import Gio, GLib
        return self._connection.call_sync('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting', method,
                                          args, GLib.VariantType.new(reply_type) if reply_type else None,
                                          Gio.DBusCallFlags.NONE, 3000, None)

    def _load_script(self):
        from gi.repository import Gio, GLib
        path = os.path.join(paths.data_dir, 'kwin_cursor.js')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(SCRIPT)
        # a script left behind by a crashed meikipop would otherwise keep the old copy loaded
        self._scripting('unloadScript', GLib.Variant('(s)', (SCRIPT_NAME,)))
        script_id = self._scripting('loadScript', GLib.Variant('(ss)', (path, SCRIPT_NAME)), '(i)').unpack()[0]
        if script_id < 0:
            raise RuntimeError("KWin refused to load the script")
        self._connection.call_sync('org.kde.KWin', f'/Scripting/Script{script_id}', 'org.kde.kwin.Script', 'run',
                                   None, None, Gio.DBusCallFlags.NONE, 3000, None)

    def stop(self):
        if not self.active:
            return
        self.active = False
        try:
            from gi.repository import GLib
            self._scripting('unloadScript', GLib.Variant('(s)', (SCRIPT_NAME,)))
            logger.info("KWin cursor: script unloaded.")
        except Exception as e:
            logger.warning(f"KWin cursor: couldn't unload the KWin script: {e}")
        if self._loop:
            self._loop.quit()


kwin_cursor = KWinCursor()


def kde_wayland() -> bool:
    from meikipop.config.config import IS_WAYLAND
    return IS_WAYLAND and 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
