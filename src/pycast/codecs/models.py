"""Backend-neutral outputs from media encoders."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EncodedVideoPacket:
    data: bytes
    timestamp_ns: int
    keyframe: bool


@dataclass(frozen=True, slots=True)
class EncodedAudioPacket:
    data: bytes
    timestamp_ns: int
    sample_rate: int
    channels: int
    frame_count: int
