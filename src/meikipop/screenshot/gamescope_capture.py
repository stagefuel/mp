# meikipop/screenshot/gamescope_capture.py
"""mss-compatible capture for Steam Deck Game Mode.

gamescope exposes its composited output (without overlays) as a PipeWire node named
`gamescope`. There's no xdg portal in Game Mode, so unlike wayland_mss_shim.py this
connects to the node directly. Like the Wayland shim, pixels are only copied out of
the latest frame when a screenshot is actually requested.

Frames are returned in overlay space (the size of Steam's display), so they line up
with the cursor coordinates and the popup host - see meikipop/gamescope.py.
"""
import logging
import threading

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from mss.exception import ScreenShotError
from mss.models import Monitor
from mss.screenshot import ScreenShot, Size

from meikipop.gamescope import gamescope

logger = logging.getLogger(__name__)

PIPELINE = (
    'pipewiresrc target-object=gamescope always-copy=true ! '
    'videoconvert ! '
    'videorate drop-only=true ! '
    'video/x-raw,format=BGRx,max-framerate=10/1 ! '
    'appsink name=sink max-buffers=1 drop=true emit-signals=true enable-last-sample=false qos=false sync=false'
)


class GamescopeStream:
    def __init__(self):
        Gst.init(None)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.last_sample = None
        self.last_frame = None
        self.pipeline = Gst.parse_launch(PIPELINE)
        sink = self.pipeline.get_by_name('sink')
        sink.connect('new-sample', self._on_new_sample)
        self.pipeline.set_state(Gst.State.PLAYING)
        logger.info("Game Mode: reading the gamescope PipeWire stream")

    def _on_new_sample(self, appsink):
        sample = appsink.emit('pull-sample')
        if sample is not None:
            with self.lock:
                self.last_sample = sample
                self.last_frame = None
            self.ready.set()
        return Gst.FlowReturn.OK

    def request_frame(self):
        """(bgrx bytes, width, height) of the newest frame, scaled to overlay space."""
        with self.lock:
            if self.last_frame is None and self.last_sample is not None:
                self.last_frame = self._to_overlay_space(self.last_sample)
            return self.last_frame

    @staticmethod
    def _to_overlay_space(sample):
        caps = sample.get_caps().get_structure(0)
        width, height = caps.get_value('width'), caps.get_value('height')
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            data = bytes(info.data)
        finally:
            buffer.unmap(info)
        stride = len(data) // height
        if stride != width * 4:  # drop row padding
            data = b''.join(data[r * stride:r * stride + width * 4] for r in range(height))
        ow, oh = gamescope().overlay_size()
        if (width, height) != (ow, oh):  # e.g. docked: stream at output size, Steam's display smaller
            from PIL import Image
            img = Image.frombytes('RGB', (width, height), data, 'raw', 'BGRX').resize((ow, oh), Image.BILINEAR)
            data, width, height = img.tobytes('raw', 'BGRX'), ow, oh
        return data, width, height

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)


_stream = None
_stream_lock = threading.Lock()


class MSSGamescopeShim:
    def __init__(self):
        global _stream
        with _stream_lock:
            if _stream is None:
                _stream = GamescopeStream()
                if not _stream.ready.wait(timeout=10):
                    raise ScreenShotError("No frames from gamescope's PipeWire stream (is this Game Mode?)")
        frame = _stream.request_frame()
        if not frame:
            raise ScreenShotError('Invalid frame received')
        _, w, h = frame
        whole = Monitor({'top': 0, 'left': 0, 'width': w, 'height': h})
        self._monitors = [whole, whole]

    @property
    def monitors(self):
        return self._monitors

    def grab(self, area):
        frame = _stream.request_frame()
        if not frame:
            raise ScreenShotError('Invalid frame received')
        data, fw, fh = frame
        left = max(0, min(area['left'], fw - 1)); top = max(0, min(area['top'], fh - 1))
        right = max(left + 1, min(area['left'] + area['width'], fw))
        bottom = max(top + 1, min(area['top'] + area['height'], fh))
        if (left, top, right, bottom) != (0, 0, fw, fh):
            stride, w = fw * 4, right - left
            data = b''.join(data[y * stride + left * 4:y * stride + right * 4] for y in range(top, bottom))
            fw, fh = w, bottom - top
        return ScreenShot(bytearray(data), self._monitors[0], size=Size(fw, fh))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class MSSModuleShim:
    def mss(self):
        return MSSGamescopeShim()

    def __getattr__(self, name):
        import mss as real_mss
        return getattr(real_mss, name)
