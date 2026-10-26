# meikipop/main.py
import argparse
import os
import signal
import sys
import threading

# Steam Deck Game Mode has to be known before any meikipop module is imported (see meikipop/gamescope.py)
if '--gamescope' in sys.argv:
    os.environ['MEIKIPOP_GAMESCOPE'] = '1'

from PyQt6.QtCore import Qt, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from meikipop.utils.logger import setup_logging
from meikipop.config.config import APP_NAME, APP_VERSION, config
from meikipop.dictionary.lookup import Lookup
from meikipop.gui.copy_line import CopyLine
from meikipop.gui.game_areas import GameAreas
from meikipop.gui.input import InputLoop
from meikipop.gui.popup import Popup
from meikipop.gui.single_instance import SingleInstance
from meikipop.gui.tray import TrayIcon
from meikipop.gui.updates import UpdateManager
from meikipop.ocr.hit_scan import HitScanner
from meikipop.ocr.ocr import OcrProcessor
from meikipop.screenshot.screenmanager import ScreenManager
from meikipop.texthooker.feed import TextFeed
from meikipop.utils import autostart
from meikipop.utils.lastest_queue import LatestValueQueue


def qt_message_handler(mode, context, message):
    # Check if the message is the specific warning we want to suppress.
    if "QWindowsWindow::setGeometry" in message and "Unable to set geometry" in message:
        return  # Silently ignore this specific warning.
    if original_handler:
        original_handler(mode, context, message)

# This global variable will hold the original message handler.
original_handler = None


class SharedState:
    def __init__(self):
        self.running = True

        # events and queues
        self.screenshot_trigger_event = threading.Event()
        self.ocr_queue = LatestValueQueue()
        self.hit_scan_queue = LatestValueQueue()
        self.lookup_queue = LatestValueQueue()

        # screen lock - used by screen manager and popup
        self.screen_lock = threading.RLock()

        # set while the popup is locked in place for mining; pauses ocr and lookups
        self.popup_locked = False

        # set while "pause outside games" is on and no game is focused (see gui/game_areas.py)
        self.auto_paused = False

        # sends new ocr'd lines to texthooker pages over a local websocket (set up in run_gui)
        self.text_feed = None

    @property
    def paused(self):
        return not config.is_enabled or self.auto_paused


def run_gamescope_gui():
    """Steam Deck Game Mode: lookup popup only, started next to a game by packaging/steamdeck/meikipop-gamescope.

    No tray, settings, updates, single-instance lock, texthooker, mining, copy-line or per-game areas: there's no
    desktop to show them on, and the game's own window keeps focus. Qt draws on Steam's display (gamescope only
    shows overlay windows from there); input and the cursor stay on the game's display (DISPLAY).
    """
    from meikipop.gamescope import OVERLAY_DISPLAY, gamescope
    setup_logging()
    os.environ['QT_QPA_PLATFORM'] = 'xcb'
    os.environ.pop('WAYLAND_DISPLAY', None)
    shared_state = SharedState()

    global original_handler
    original_handler = qInstallMessageHandler(qt_message_handler)
    app = QApplication([sys.argv[0], '-display', OVERLAY_DISPLAY])
    app.setQuitOnLastWindowClosed(False)
    gamescope()  # connect to both displays now, so a problem shows up at start

    input_loop = InputLoop(shared_state)
    popup_window = Popup(shared_state, input_loop)
    screen_manager = ScreenManager(shared_state, input_loop)  # whole screen (forced in config)
    lookup = Lookup(shared_state, popup_window)
    ocr_processor = OcrProcessor(shared_state, screen_manager)
    hit_scanner = HitScanner(shared_state, input_loop, screen_manager)
    from meikipop.gui.gamemode import GameModeController
    game_mode = GameModeController(shared_state, popup_window, lookup)  # plugin settings, pause, preview
    for t in [lookup, hit_scanner, ocr_processor, screen_manager, input_loop]:
        t.start()
    game_mode.start()
    print(f"{APP_NAME}.{APP_VERSION} running in Steam Deck Game Mode (lookup only).")

    def signal_handler(sig, frame):
        QApplication.quit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    exit_code = app.exec()

    shared_state.running = False
    shared_state.screenshot_trigger_event.set()
    shared_state.ocr_queue.put(None)
    shared_state.hit_scan_queue.trigger()
    shared_state.lookup_queue.put(None)
    sys.exit(exit_code)


def run_gui(background=False):
    setup_logging()
    if background:
        autostart.minimize_console()
    shared_state = SharedState()

    global original_handler
    original_handler = qInstallMessageHandler(qt_message_handler)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # one meikipop at a time: a second launch opens the running one's settings and exits
    single_instance = SingleInstance()
    if single_instance.notify_running():
        print(f"{APP_NAME} is already running - opened its settings instead.")
        sys.exit(0)
    single_instance.listen()

    # KDE Wayland: follow the cursor through KWin, so lookups also work over Wayland-native windows
    from meikipop.gui.kwin_cursor import kde_wayland, kwin_cursor
    if kde_wayland():
        kwin_cursor.start()

    input_loop = InputLoop(shared_state)
    popup_window = Popup(shared_state, input_loop)

    screen_manager = ScreenManager(shared_state, input_loop)  # trigger region selection
    lookup = Lookup(shared_state, popup_window)  # load dictionary
    shared_state.text_feed = TextFeed(fix_text=lookup.fix_reversed_pairs)

    ocr_processor = OcrProcessor(shared_state, screen_manager)
    hit_scanner = HitScanner(shared_state, input_loop, screen_manager)
    game_areas = GameAreas(screen_manager, shared_state)
    copy_line = CopyLine(hit_scanner, fix_text=lookup.fix_reversed_pairs)
    tray_icon = TrayIcon(screen_manager, ocr_processor, popup_window, input_loop, lookup, game_areas, copy_line)
    # queued, so the other launch's connection is handled before the settings dialog's own event loop starts
    single_instance.activated.connect(tray_icon.show_settings, Qt.ConnectionType.QueuedConnection)
    tray_icon.update_manager = UpdateManager(tray_icon, single_instance)
    tray_icon.update_manager.start()

    for t in [lookup, hit_scanner, ocr_processor, screen_manager, input_loop]:
        t.start()
    game_areas.start()
    copy_line.start()
    autostart.sync(config.run_on_startup)  # follows the exe if an update renamed it

    ready_message = f"""
    --------------------------------------------------
    {APP_NAME}.{APP_VERSION} is running in the background.

      - To configure or change scan area: Right-click the icon in your system tray.
      - To exit: Press Ctrl+C in this terminal.

    --------------------------------------------------
    """
    print(ready_message)

    def signal_handler(sig, frame):
        QApplication.quit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    exit_code = app.exec()

    shared_state.running = False
    shared_state.text_feed.stop()
    shared_state.screenshot_trigger_event.set()
    shared_state.ocr_queue.put(None)
    shared_state.hit_scan_queue.trigger()
    shared_state.lookup_queue.put(None)
    sys.exit(exit_code)


def main():
    parser = argparse.ArgumentParser(
        prog="meikipop",
        description="Universal Japanese OCR popup dictionary"
    )
    parser.add_argument("--background", action="store_true",
                        help="Start quietly (used when starting at login; on windows the console starts minimized)")
    parser.add_argument("--gamescope", action="store_true",
                        help="Steam Deck Game Mode: lookup popup only, drawn as a gamescope overlay "
                             "(use packaging/steamdeck/meikipop-gamescope as a game's launch option)")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("build-dict", help="Build the dictionary from source files")
    subparsers.add_parser("self-test", help="Check that every bundled OCR provider can be imported, then exit")

    import_html_parser = subparsers.add_parser("import-yomitan-dict-html", help="Import Yomitan dictionary (HTML format)")
    import_html_parser.add_argument("dictionary_files", nargs='+', help="Path(s) to the dictionary zip file(s)")

    import_text_parser = subparsers.add_parser("import-yomitan-dict-text", help="Import Yomitan dictionary (text format)")
    import_text_parser.add_argument("dictionary_files", nargs='+', help="Path(s) to the dictionary zip file(s)")

    args = parser.parse_args()

    if args.command == "self-test":
        import importlib
        failed = False
        for module in ("meikipop.ocr.providers.meikiocr.provider", "meikipop.ocr.providers.meikiocr.vertical",
                       "meikipop.ocr.providers.glensv2", "meikipop.ocr.providers.owocr",
                       "meikipop.ocr.providers.screenai", "meikipop.texthooker.feed", "meikipop.anki.ankiconnect",
                       "meikipop.gui.kwin_cursor", "meikipop.gamescope", "meikipop.utils.updater", "meikipop.gui.updates",
                       "meikipop.gui.single_instance", "meikipop.gui.game_areas", "meikipop.gui.copy_line",
                       "meikipop.utils.autostart"):
            try:
                importlib.import_module(module)
                print(f"ok      {module}")
            except Exception as e:
                failed = True
                print(f"FAILED  {module}: {e!r}")
        if getattr(sys, 'frozen', False):
            from meikipop.utils.paths import paths
            bundled = paths.get_resource_path('dictionary.pkl')
            if os.path.exists(bundled):
                print(f"ok      bundled dictionary ({os.path.getsize(bundled) / 1048576:.1f} MB)")
            else:
                failed = True
                print("FAILED  no bundled dictionary")
        sys.exit(1 if failed else 0)
    elif args.command == "build-dict":
        from meikipop.scripts.build_dictionary import main as build_main
        build_main()
    elif args.command == "import-yomitan-dict-html":
        from meikipop.scripts.import_yomitan_dict_html import main as import_html_main
        import_html_main([*args.dictionary_files])
    elif args.command == "import-yomitan-dict-text":
        from meikipop.scripts.import_yomitan_dict_text import main as import_text_main
        import_text_main([*args.dictionary_files])
    elif args.gamescope:
        run_gamescope_gui()
    else:
        run_gui(background=args.background)


if __name__ == "__main__":
    main()