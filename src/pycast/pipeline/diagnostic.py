"""Timestamp-ordered local media diagnostic pipeline."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

import av

from pycast.capture.models import CapturedAudioChunk, CapturedVideoFrame
from pycast.codecs.alac import AlacAudioEncoder
from pycast.codecs.h264 import H264VideoEncoder
from pycast.codecs.models import EncodedAudioPacket, EncodedVideoPacket


@dataclass(frozen=True, slots=True)
class PipelineResult:
    output_path: Path
    video_frames: int
    audio_chunks: int
    video_packets: int
    audio_packets: int
    first_timestamp_ns: int | None
    last_timestamp_ns: int | None


MediaEvent = tuple[int, Literal["audio", "video"], CapturedAudioChunk | CapturedVideoFrame]


class DiagnosticPipeline:
    """Encode timestamped captured media and mux it into a local file.

    The pipeline accepts captured samples rather than raw DXcam/PyAudio objects;
    this makes the same orchestration usable with real capture adapters and fakes.
    """

    def __init__(self, width: int, height: int, fps: int, sample_rate: int, channels: int = 2) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._sample_rate = sample_rate
        self._channels = channels

    def encode_to_file(
        self,
        video_frames: Iterable[CapturedVideoFrame],
        audio_chunks: Iterable[CapturedAudioChunk],
        output_path: Path,
    ) -> PipelineResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_encoder = H264VideoEncoder(self._width, self._height, self._fps)
        audio_encoder = AlacAudioEncoder(self._sample_rate, self._channels)
        events = self._ordered_events(video_frames, audio_chunks)
        video_count = audio_count = video_packets = audio_packets = 0
        first_timestamp: int | None = None
        last_timestamp: int | None = None

        with av.open(str(output_path), mode="w", format="matroska") as container:
            video_stream, audio_stream = self._configure_streams(container)
            for timestamp, kind, sample in events:
                first_timestamp = timestamp if first_timestamp is None else first_timestamp
                last_timestamp = timestamp
                if kind == "video":
                    video_count += 1
                    video_encoded = video_encoder.encode(sample)  # type: ignore[arg-type]
                    video_packets += self._mux_video(container, video_stream, video_encoded)
                else:
                    audio_count += 1
                    audio_encoded = audio_encoder.encode(sample)  # type: ignore[arg-type]
                    audio_packets += self._mux_audio(container, audio_stream, audio_encoded)
            video_packets += self._mux_video(container, video_stream, video_encoder.flush())
            audio_packets += self._mux_audio(container, audio_stream, audio_encoder.flush())

        return PipelineResult(
            output_path,
            video_count,
            audio_count,
            video_packets,
            audio_packets,
            first_timestamp,
            last_timestamp,
        )

    @staticmethod
    def _ordered_events(video_frames: Iterable[CapturedVideoFrame], audio_chunks: Iterable[CapturedAudioChunk]) -> Iterator[MediaEvent]:
        events: list[MediaEvent] = [(frame.timestamp_ns, "video", frame) for frame in video_frames] + [(chunk.timestamp_ns, "audio", chunk) for chunk in audio_chunks]
        yield from sorted(events, key=lambda event: event[0])

    def _configure_streams(self, container: av.container.OutputContainer) -> tuple[Any, Any]:
        video_stream = container.add_stream("h264", rate=self._fps)
        video_stream.width = self._width
        video_stream.height = self._height
        video_stream.time_base = Fraction(1, 1_000_000_000)
        audio_stream = container.add_stream("alac", rate=self._sample_rate)
        audio_stream.layout = "mono" if self._channels == 1 else "stereo"
        audio_stream.time_base = Fraction(1, 1_000_000_000)
        return video_stream, audio_stream

    @staticmethod
    def _mux_video(container: av.container.OutputContainer, stream: Any, packets: list[EncodedVideoPacket]) -> int:
        for encoded in packets:
            raw_packet = av.Packet(encoded.data)
            raw_packet.stream = stream
            raw_packet.pts = encoded.timestamp_ns
            raw_packet.dts = encoded.timestamp_ns
            raw_packet.time_base = stream.time_base
            container.mux(raw_packet)
        return len(packets)

    @staticmethod
    def _mux_audio(container: av.container.OutputContainer, stream: Any, packets: list[EncodedAudioPacket]) -> int:
        for encoded in packets:
            raw_packet = av.Packet(encoded.data)
            raw_packet.stream = stream
            raw_packet.pts = encoded.timestamp_ns
            raw_packet.dts = encoded.timestamp_ns
            raw_packet.time_base = stream.time_base
            container.mux(raw_packet)
        return len(packets)
