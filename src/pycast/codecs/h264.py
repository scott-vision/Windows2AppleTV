"""PyAV H.264 encoder with nanosecond timestamp propagation."""

from fractions import Fraction
from typing import Any

from pycast.capture.models import CapturedVideoFrame

from .models import EncodedVideoPacket


class H264VideoEncoder:
    """Encode BGR/BGRA NumPy frames with FFmpeg's software libx264 encoder."""

    def __init__(self, width: int, height: int, fps: int, preset: str = "veryfast") -> None:
        if width <= 0 or height <= 0 or fps <= 0:
            raise ValueError("width, height, and fps must be positive")
        try:
            import av
        except ImportError as exc:
            raise RuntimeError("PyAV is required for H.264 encoding") from exc
        self._av = av
        self._context = av.CodecContext.create("libx264", "w")
        self._context.width = width
        self._context.height = height
        self._context.pix_fmt = "yuv420p"
        self._context.framerate = Fraction(fps, 1)
        self._context.time_base = Fraction(1, 1_000_000_000)
        self._context.options = {"preset": preset, "tune": "zerolatency"}
        self._context.open()

    def encode(self, frame: CapturedVideoFrame) -> list[EncodedVideoPacket]:
        pixel_format = "bgra" if getattr(frame.data, "shape", (0, 0, 0))[-1] == 4 else "bgr24"
        video_frame = self._av.VideoFrame.from_ndarray(frame.data, format=pixel_format)
        video_frame.pts = frame.timestamp_ns
        video_frame.time_base = Fraction(1, 1_000_000_000)
        return [self._packet(packet) for packet in self._context.encode(video_frame)]

    def flush(self) -> list[EncodedVideoPacket]:
        return [self._packet(packet) for packet in self._context.encode(None)]

    def _packet(self, packet: Any) -> EncodedVideoPacket:
        timestamp = packet.pts if packet.pts is not None else 0
        if packet.time_base is not None:
            timestamp = int(timestamp * packet.time_base * 1_000_000_000)
        return EncodedVideoPacket(bytes(packet), timestamp, bool(packet.is_keyframe))
