# meikipop/texthooker/server.py
import logging
import threading

from websockets.exceptions import WebSocketException
from websockets.sync.server import serve

logger = logging.getLogger(__name__)


class TexthookerServer:
    """Local websocket server that texthooker pages (kizuna-texthooker-ui, Renji's texthooker-ui) connect to,
    the same way they connect to Textractor/LunaHost. Every message is one plain-text line."""

    def __init__(self):
        self._server = None
        self._clients = set()
        self._lock = threading.Lock()
        self.port = None

    def start(self, port: int):
        self.stop()
        try:
            # loopback only: nothing on the network can read the feed
            self._server = serve(self._handle_client, '127.0.0.1', port)
        except OSError as e:
            logger.error(f"Texthooker: could not listen on ws://localhost:{port} ({e}). "
                         f"Is Textractor/LunaHost or another meikipop already using that port?")
            self._server = None
            return False
        self.port = port
        threading.Thread(target=self._server.serve_forever, daemon=True, name="TexthookerServer").start()
        logger.info(f"Texthooker: serving text on ws://localhost:{port}")
        return True

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("Texthooker: server stopped.")
        with self._lock:
            self._clients.clear()

    @property
    def running(self):
        return self._server is not None

    def _handle_client(self, websocket):
        with self._lock:
            self._clients.add(websocket)
        logger.info(f"Texthooker: client connected ({len(self._clients)} total).")
        try:
            for _ in websocket:  # nothing is expected from the page; just keep the connection open
                pass
        except WebSocketException:
            pass
        finally:
            with self._lock:
                self._clients.discard(websocket)
            logger.info("Texthooker: client disconnected.")

    def broadcast(self, text: str):
        with self._lock:
            clients = list(self._clients)
        for websocket in clients:
            try:
                websocket.send(text)
            except (WebSocketException, OSError):
                with self._lock:
                    self._clients.discard(websocket)
