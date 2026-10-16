# meikipop/gui/tray.py
import os

from PyQt6.QtGui import QIcon, QAction, QActionGroup
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from meikipop.config.config import APP_NAME, config, IS_WINDOWS
from meikipop.gui.settings_dialog import SettingsDialog
from meikipop.ocr.ocr import OcrProcessor
from meikipop.utils.paths import paths


class TrayIcon(QSystemTrayIcon):
    def __init__(self, screen_manager, ocr_processor: OcrProcessor, popup_window, input_loop, lookup, game_areas=None,
                 copy_line=None, parent=None):
        # Resolve icon paths using
        icon_path = paths.get_resource_path('icon.ico')
        icon_inactive_path = paths.get_resource_path('icon.inactive.ico')

        if os.path.exists(icon_path):
            self.icon = QIcon(icon_path)
            self.icon_inactive = QIcon(icon_inactive_path)
        else:
            # print(f"Warning: Custom icon not found at '{icon_path}'. Using default.")
            from PyQt6.QtWidgets import QStyle
            self.icon = QIcon(QApplication.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon
            ))
            self.icon_inactive = self.icon
        super().__init__(self.icon, parent)

        self.screen_manager = screen_manager
        self.ocr_processor = ocr_processor
        self.popup_window = popup_window
        self.input_loop = input_loop
        self.lookup = lookup
        self.game_areas = game_areas
        self.copy_line = copy_line
        self.scan_area_actions = []
        self.settings_dialog = None

        self.menu = QMenu()

        # Settings Action
        self.menu.addAction("Settings").triggered.connect(self.show_settings)

        self.menu.addSeparator()

        # OCR Provider Selection
        ocr_menu = self.menu.addMenu("OCR Provider")
        self.ocr_action_group = QActionGroup(self)
        self.ocr_action_group.setExclusive(True)
        self.ocr_action_group.triggered.connect(self._on_ocr_provider_selected)

        for provider_name in self.ocr_processor.available_providers.keys():
            action = ocr_menu.addAction(provider_name)
            action.setCheckable(True)
            if provider_name == config.ocr_provider:
                action.setChecked(True)
            self.ocr_action_group.addAction(action)

        self.menu.addSeparator()

        # Scan Mode Selection
        scan_mode_menu = self.menu.addMenu("Scan Mode")
        self.scan_mode_action_group = QActionGroup(self)
        self.scan_mode_action_group.setExclusive(True)
        self.scan_mode_action_group.triggered.connect(self._on_scan_mode_selected)

        manual_action = scan_mode_menu.addAction("Manual")
        manual_action.setCheckable(True)
        manual_action.setChecked(not config.auto_scan_mode)
        self.scan_mode_action_group.addAction(manual_action)

        auto_action = scan_mode_menu.addAction("Auto")
        auto_action.setCheckable(True)
        auto_action.setChecked(config.auto_scan_mode)
        self.scan_mode_action_group.addAction(auto_action)

        # Scan Area Selection
        scan_area_menu = self.menu.addMenu("Scan Area")
        self.scan_area_action_group = QActionGroup(self)
        self.scan_area_action_group.setExclusive(True)
        self.scan_area_action_group.triggered.connect(self._on_scan_area_selected)

        region_action = scan_area_menu.addAction("Custom Region")
        region_action.setCheckable(True)
        region_action.setData('region')
        self.scan_area_action_group.addAction(region_action)
        self.scan_area_actions.append(region_action)

        for i, res in enumerate(self.screen_manager.get_screens()):
            action = scan_area_menu.addAction(f"Screen {i} ({res['width']}x{res['height']})")
            action.setCheckable(True)
            action.setData(i)
            self.scan_area_action_group.addAction(action)
            self.scan_area_actions.append(action)

        self.update_scan_area_check()

        self.menu.addSeparator()

        self.enable_action = self.menu.addAction("Pause meikipop")
        self.enable_action.setCheckable(True)
        self.enable_action.triggered.connect(self.toggle_enabled_state)
        self.activated.connect(self.on_tray_activated)

        if copy_line:
            self.menu.addAction("Copy Line").triggered.connect(copy_line.copy)

        self.menu.addSeparator()

        # set up by main.py once the tray exists (gui/updates.py)
        self.update_manager = None
        self.update_action = self.menu.addAction("Check for Updates…")
        self.update_action.triggered.connect(self._on_update_action)

        self.menu.addAction("Quit").triggered.connect(QApplication.instance().quit)

        self.setContextMenu(self.menu)
        self.setToolTip(APP_NAME)

        if game_areas:
            game_areas.paused_changed.connect(lambda _paused: self.update_icon())
            game_areas.area_applied.connect(self.update_scan_area_check)

        self.prevent_ghost_icon_on_win()

        self.show()

    def on_tray_activated(self, reason):
        """Handles clicks on the tray icon."""
        # QSystemTrayIcon.ActivationReason.Trigger is the enum for a normal left-click.
        if reason == self.ActivationReason.Trigger:
            self.toggle_enabled_state()

    def toggle_enabled_state(self):
        """Toggles the enabled/paused state of the application."""
        self.enable_action.setChecked(config.is_enabled)
        config.is_enabled = not config.is_enabled
        self.update_icon()

    def update_icon(self):
        auto_paused = bool(self.game_areas and self.game_areas.shared_state.auto_paused)
        self.setIcon(self.icon if config.is_enabled and not auto_paused else self.icon_inactive)
        self.setToolTip(f"{APP_NAME} (paused outside games)" if config.is_enabled and auto_paused else APP_NAME)

    def update_scan_area_check(self):
        current_region = config.scan_region
        action_to_check = None
        for action in self.scan_area_actions:
            if str(action.data()) == str(current_region):
                action_to_check = action
                break

        if not action_to_check:
            # If no specific match is found, default to checking the 'Custom Region' action.
            action_to_check = self.scan_area_actions[0]

        action_to_check.setChecked(True)

    def _on_scan_mode_selected(self, action: QAction):
        is_auto = action.text() == "Auto"
        if is_auto != config.auto_scan_mode:
            config.auto_scan_mode = is_auto
            config.save()

    def _on_scan_area_selected(self, action: QAction):
        selected_id = action.data()
        if selected_id == 'region':
            if self.screen_manager.set_scan_region():
                if self.game_areas and (config.per_game_scan_area or config.pause_outside_games):
                    self.game_areas.remember_region(self.screen_manager.monitor)
                if config.scan_region != 'region':
                    config.scan_region = 'region'
                    config.save()
            else:
                self.update_scan_area_check()
        else:  # It's a screen index
            index = int(selected_id)
            if str(index) != config.scan_region:
                self.screen_manager.set_scan_screen(index)
                config.scan_region = str(index)
                config.save()
            if self.game_areas and (config.per_game_scan_area or config.pause_outside_games):
                self.game_areas.remember_screen(index)

    def _on_ocr_provider_selected(self, action):
        provider_name = action.text()
        if provider_name != config.ocr_provider:
            self.ocr_processor.switch_provider(provider_name)

    def reapply_settings(self):
        """Updates the tray menu's checkmarks to reflect the current config."""
        # Update OCR Provider selection
        for action in self.ocr_action_group.actions():
            if action.text() == config.ocr_provider:
                action.setChecked(True)
                break

        # Update Scan Mode selection
        for action in self.scan_mode_action_group.actions():
            is_auto_action = action.text() == "Auto"
            if is_auto_action == config.auto_scan_mode:
                action.setChecked(True)
                break

    def _on_update_action(self):
        if not self.update_manager:
            return
        if self.update_manager.available:
            self.update_manager.prompt()
        else:
            self.update_manager.check(manual=True)

    def set_update_available(self, update):
        font = self.update_action.font()
        font.setBold(update is not None)
        self.update_action.setFont(font)
        self.update_action.setText(f"Update to {update.version}…" if update else "Check for Updates…")

    def show_settings(self):
        # a second launch of meikipop asks for this too, so bring an open dialog forward instead of stacking another
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        self.settings_dialog = SettingsDialog(self.ocr_processor, self.popup_window, self.input_loop, self.lookup,
                                              self)
        try:
            self.settings_dialog.exec()
        finally:
            self.settings_dialog = None

    def prevent_ghost_icon_on_win(self):
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes
            def win_console_handler(ctrl_type):
                # 2 = CTRL_CLOSE_EVENT (Closing the console window)
                if ctrl_type == 2:
                    try:
                        self.hide()
                    except:
                        pass
                    return False
                return False

            HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
            self._win_handler_ref = HandlerRoutine(win_console_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._win_handler_ref, True)
