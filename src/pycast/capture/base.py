"""Protocols used to isolate capture backends from application services."""

from collections.abc import Callable, Iterable
from typing import Protocol

from .models import AudioDeviceInfo, CapturedAudioChunk, CapturedVideoFrame, DisplayInfo


class VideoCapture(Protocol):
    def start(self, fps: int) -> None: ...
    def grab(self) -> CapturedVideoFrame | None: ...
    def stop(self) -> None: ...


class AudioCapture(Protocol):
    info: AudioDeviceInfo

    def start(self) -> None: ...
    def read(self) -> CapturedAudioChunk: ...
    def stop(self) -> None: ...


VideoFactory = Callable[[int], VideoCapture]
AudioFactory = Callable[[AudioDeviceInfo], AudioCapture]
DisplayEnumerator = Callable[[], Iterable[DisplayInfo]]
AudioEnumerator = Callable[[], Iterable[AudioDeviceInfo]]
