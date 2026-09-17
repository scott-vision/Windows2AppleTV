"""Backend-neutral capture data models."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DisplayInfo:
    index: int
    name: str
    width: int
    height: int
    left: int = 0
    top: int = 0
    is_primary: bool = False


@dataclass(frozen=True, slots=True)
class AudioDeviceInfo:
    index: int
    name: str
    is_output: bool
    is_loopback: bool
    sample_rate: int | None = None
    channels: int | None = None
    is_default: bool = False
    backend_index: int | None = None


@dataclass(frozen=True, slots=True)
class CapturedVideoFrame:
    data: Any
    timestamp_ns: int
    display_index: int


@dataclass(frozen=True, slots=True)
class CapturedAudioChunk:
    data: bytes
    timestamp_ns: int
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int


def timestamp_ns() -> int:
    """Return the shared monotonic acquisition clock value."""
    import time

    return time.perf_counter_ns()
