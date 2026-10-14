# meikipop/gui/updates.py
"""The update flow behind the tray menu: check (quietly at startup, or on request), ask, download with progress,
hand over to the updater's restart helper and quit."""
import logging
import threading

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QSystemTrayIcon

from meikipop.config.config import APP_NAME, APP_VERSION, config
from meikipop.utils import updater

logger = logging.getLogger(__name__)

STARTUP_CHECK_DELAY_MS = 8000  # let the dictionary and ocr model load first


class UpdateManager(QObject):
    _checked = pyqtSignal(object, object, bool)  # update or None, error or None, asked by the user
    _progress = pyqtSignal(int, int)
    _downloaded = pyqtSignal(bool, object)  # finished (not cancelled), error or None

    def __init__(self, tray, single_instance):
        super().__init__()
        self.tray = tray
        self.single_instance = single_instance
        self.available = None
        self._checking = False
        self._cancel = False
        self._progress_dialog = None
        self._download_dest = None
        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)
        tray.messageClicked.connect(self._on_message_clicked)

    def start(self):
        if config.check_for_updates:
            QTimer.singleShot(STARTUP_CHECK_DELAY_MS, lambda: self.check(manual=False))

    def check(self, manual=True):
        if self._checking or self._progress_dialog:
            return
        self._checking = True
        threading.Thread(target=self._check_thread, args=(manual,), daemon=True, name="UpdateCheck").start()

    def _check_thread(self, manual):
        try:
            self._checked.emit(updater.find_update(), None, manual)
        except Exception as e:
            self._checked.emit(None, e, manual)

    def _on_checked(self, update, error, manual):
        self._checking = False
        if error:
            logger.warning(f"Update check failed: {error}")
            if manual:
                QMessageBox.warning(None, APP_NAME, f"Couldn't check for updates:\n{error}")
            return
        self.available = update
        self.tray.set_update_available(update)
        if update is None:
            logger.info("Update check: up to date.")
            if manual:
                QMessageBox.information(None, APP_NAME, f"{APP_NAME} {APP_VERSION} is the newest version.")
            return
        logger.info(f"Update check: {update.version} is available.")
        if manual:
            self.prompt()
        else:
            self.tray.showMessage(f"{APP_NAME} update",
                                  f"Version {update.version} is available. Click here or use the tray menu to update.",
                                  QSystemTrayIcon.MessageIcon.Information, 10000)

    def _on_message_clicked(self):
        if self.available:
            self.prompt()

    def prompt(self):
        update = self.available
        if update is None:
            self.check(manual=True)
            return
        box = QMessageBox()
        box.setWindowTitle(f"{APP_NAME} update")
        box.setIcon(QMessageBox.Icon.Information)
        if update.notes:
            box.setDetailedText(update.notes)
        if updater.can_self_update() and update.asset_url:
            box.setText(f"{APP_NAME} {update.version} is available (you have {APP_VERSION}).\n\n"
                        f"Update now? {APP_NAME} downloads it ({update.size / 1048576:.0f} MB), closes, and "
                        f"starts the new version. Your settings are kept.")
            update_button = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
            page_button = box.addButton("Release page", QMessageBox.ButtonRole.HelpRole)
            box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        else:
            box.setText(f"{APP_NAME} {update.version} is available (you have {APP_VERSION}).\n\n"
                        f"This copy runs from source, so it can't update itself: pull the new version, or "
                        f"download a release.")
            update_button = None
            page_button = box.addButton("Release page", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is page_button:
            QDesktopServices.openUrl(QUrl(update.page_url))
        elif update_button is not None and clicked is update_button:
            self._start_download(update)

    def _start_download(self, update):
        self._cancel = False
        self._download_dest = updater.download_path(update)
        dialog = QProgressDialog(f"Downloading {APP_NAME} {update.version}…", "Cancel", 0, 100)
        dialog.setWindowTitle(f"{APP_NAME} update")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._on_cancel)
        dialog.setValue(0)
        dialog.show()
        self._progress_dialog = dialog
        threading.Thread(target=self._download_thread, args=(update,), daemon=True, name="UpdateDownload").start()

    def _on_cancel(self):
        self._cancel = True

    def _download_thread(self, update):
        try:
            finished = updater.download(update, self._download_dest,
                                        progress=lambda done, total: self._progress.emit(done, total),
                                        cancelled=lambda: self._cancel)
            self._downloaded.emit(finished, None)
        except Exception as e:
            self._downloaded.emit(False, e)

    def _on_progress(self, done, total):
        if self._progress_dialog and total:
            self._progress_dialog.setValue(int(done * 100 / total))
            self._progress_dialog.setLabelText(f"Downloading {APP_NAME} {self.available.version}… "
                                               f"{done / 1048576:.0f} / {total / 1048576:.0f} MB")

    def _on_downloaded(self, finished, error):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        if error:
            logger.warning(f"Update download failed: {error}")
            QMessageBox.warning(None, APP_NAME, f"The update couldn't be downloaded:\n{error}")
            return
        if not finished:
            return
        try:
            updater.apply(self.available, self._download_dest)
        except Exception as e:
            logger.exception("Applying the update failed")
            QMessageBox.warning(None, APP_NAME, f"The update couldn't be installed:\n{e}")
            return
        logger.info(f"Restarting into {self.available.version}.")
        # let the new version claim the single-instance socket as soon as it starts
        self.single_instance.close()
        QApplication.quit()
