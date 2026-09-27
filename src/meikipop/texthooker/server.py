# meikipop/texthooker/server.py
import asyncio
import logging
import threading
from typing import Optional

from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class TexthookerServer:
    """Local websocket server that texthooker pages (kizuna-texthooker-ui, Renji's texthooker-ui) connect to,
    the same way they connect to Textractor/LunaHost. Every message is one plain-text line.

    Runs websockets' asyncio server on its own event loop thread. Sending never waits on a client, so a
    frozen background tab can't hold up the ocr thread, and the feed restarts the server if it ever dies."""

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._ws_server = None
        self._clients = set()
        self.port = None

    def start(self, port: int) -> bool:
        self.stop()
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        result = {}

        async def run_server():
            self._stop_event = asyncio.Event()
            try:
                # loopback only: nothing on the network can read the feed.
                # no keepalive pings: browsers freeze/throttle background tabs (the page sits behind the game),
                # so pongs arrive late and the default 20s ping timeout would drop the page every few minutes.
                # textractor/lunahost don't ping (or compress) either.
                server = await serve(self._handle_client, '127.0.0.1', port, ping_interval=None, compression=None)
            except OSError as e:
                result['error'] = e
                ready.set()
                return
            self._ws_server = server
            result['ok'] = True
            ready.set()
            try:
                await self._stop_event.wait()
            finally:
                server.close()
                await server.wait_closed()

        def run():
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run_server())
            except BaseException:
                logger.exception("Texthooker: server crashed")
            finally:
                self._shut_down_loop(loop)

        self._loop = loop
        self._thread = threading.Thread(target=run, daemon=True, name="TexthookerServer")
        self._thread.start()
        ready.wait(5)
        if not result.get('ok'):
            logger.error(f"Texthooker: could not listen on ws://localhost:{port} ({result.get('error')}). "
                         f"Is Textractor/LunaHost or another meikipop already using that port?")
            self.stop()
            return False
        self.port = port
        logger.info(f"Texthooker: serving text on ws://localhost:{port}")
        return True

    def _shut_down_loop(self, loop):
        # free the port first, even after a crash: a listening socket nobody accepts on makes pages look
        # connected-but-dead (windows keeps completing their tcp handshakes) and blocks restarting the server
        server, self._ws_server = self._ws_server, None
        listener = getattr(server, 'server', None)
        if listener is not None:
            try:
                listener.close()
            except Exception:
                logger.exception("Texthooker: could not close the listening socket")
        try:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()

    def stop(self):
        if self._thread and self._thread.is_alive() and self._loop and self._stop_event:
            try:
                self._loop.call_soon_threadsafe(self._stop_event.set)
            except RuntimeError:  # loop already closed
                pass
            self._thread.join(5)
            logger.info("Texthooker: server stopped.")
        self._thread = None
        self._loop = None
        self._stop_event = None
        self._clients = set()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    async def _handle_client(self, websocket):
        self._clients.add(websocket)
        origin = websocket.request.headers.get('Origin', 'no origin') if websocket.request else 'unknown'
        logger.info(f"Texthooker: client connected from {origin} ({len(self._clients)} total).")
        try:
            async for _ in websocket:  # nothing is expected from the page; just keep the connection open
                pass
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            reason = f"code {websocket.close_code}" + (f", {websocket.close_reason}" if websocket.close_reason else "")
            logger.info(f"Texthooker: client disconnected ({reason}).")

    def broadcast(self, text: str):
        """Queue text for every connected page and return immediately (called from the ocr thread)."""
        loop = self._loop
        if loop is None or not self.running:
            return
        try:
            # websockets' broadcast writes without waiting; a client that can't keep up is skipped, not waited on
            loop.call_soon_threadsafe(lambda: broadcast(set(self._clients), text))
        except RuntimeError:  # loop closed between the check and the call
            pass
