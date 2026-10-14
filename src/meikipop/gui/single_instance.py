# meikipop/gui/single_instance.py
"""Only one meikipop at a time. The first one listens on a local socket (a named pipe on windows, a socket file in
the data dir elsewhere). A second launch connects to it, which makes the first one open its settings, and exits."""
import getpass
import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from meikipop.config.config import IS_WINDOWS
from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)


def _server_name():
    if IS_WINDOWS:
        return f"meikipop-{getpass.getuser()}"
    return os.path.join(paths.data_dir, 'instance.sock')


class SingleInstance(QObject):
    activated = pyqtSignal()  # another launch asked this instance to show itself

    def __init__(self):
        super().__init__()
        self.name = _server_name()
        self.server = None

    def notify_running(self, timeout_ms=1000):
        """True if meikipop is already running (it has been asked to open its settings)."""
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(timeout_ms):
            return False
        socket.write(b"show\n")
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True

    def listen(self):
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.name):
            # a crashed instance leaves its socket file behind. nothing answered on it, so it can go
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                logger.warning(f"Single instance: can't listen on {self.name}: {self.server.errorString()}")
                self.server = None
                return
        self.server.newConnection.connect(self._on_new_connection)

    def _on_new_connection(self):
        while self.server and self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            logger.info("Another meikipop was started; showing this one instead.")
            self.activated.emit()

    def close(self):
        """Stop answering, e.g. right before an update restarts meikipop."""
        if self.server:
            self.server.close()
            self.server = None
