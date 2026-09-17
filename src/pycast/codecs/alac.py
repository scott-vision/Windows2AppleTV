"""PyAV ALAC encoder for captured signed 16-bit PCM."""

from fractions import Fraction
from typing import Any

from pycast.capture.models import CapturedAudioChunk

from .models import EncodedAudioPacket


class AlacAudioEncoder:
    """Encode interleaved PCM chunks as ALAC while retaining capture timestamps."""

    def __init__(self, sample_rate: int, channels: int = 2) -> None:
        if sample_rate <= 0 or channels not in (1, 2):
            raise ValueError("sample_rate must be positive and channels must be 1 or 2")
        try:
            import av
            import numpy
        except ImportError as exc:
            raise RuntimeError("PyAV and NumPy are required for ALAC encoding") from exc
        self._av = av
        self._numpy = numpy
        self._sample_rate = sample_rate
        self._channels = channels
        self._context = av.CodecContext.create("alac", "w")
        self._context.sample_rate = sample_rate
        self._context.layout = "mono" if channels == 1 else "stereo"
        self._context.format = "s16p"
        self._context.time_base = Fraction(1, 1_000_000_000)
        self._context.open()

    def encode(self, chunk: CapturedAudioChunk) -> list[EncodedAudioPacket]:
        expected_bytes = chunk.frame_count * chunk.channels * chunk.sample_width
        if len(chunk.data) != expected_bytes:
            raise ValueError("audio chunk byte length does not match its frame metadata")
        samples: Any = self._numpy.frombuffer(chunk.data, dtype=self._numpy.int16)
        samples = samples.reshape(chunk.frame_count, chunk.channels).T.copy()
        audio_frame = self._av.AudioFrame.from_ndarray(samples, format="s16p", layout="mono" if chunk.channels == 1 else "stereo")
        audio_frame.sample_rate = chunk.sample_rate
        audio_frame.pts = chunk.timestamp_ns
        audio_frame.time_base = Fraction(1, 1_000_000_000)
        return [self._packet(packet, chunk) for packet in self._context.encode(audio_frame)]

    def flush(self) -> list[EncodedAudioPacket]:
        return [self._packet(packet, None) for packet in self._context.encode(None)]

    def _packet(self, packet: Any, source: CapturedAudioChunk | None) -> EncodedAudioPacket:
        timestamp = packet.pts if packet.pts is not None else 0
        if packet.time_base is not None:
            timestamp = int(timestamp * packet.time_base * 1_000_000_000)
        return EncodedAudioPacket(
            bytes(packet),
            timestamp,
            self._sample_rate,
            self._channels,
            source.frame_count if source is not None else 0,
        )
