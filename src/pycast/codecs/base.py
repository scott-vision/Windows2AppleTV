"""Interfaces shared by current and future codec implementations."""

from typing import Protocol

from pycast.capture.models import CapturedAudioChunk, CapturedVideoFrame

from .models import EncodedAudioPacket, EncodedVideoPacket


class VideoEncoder(Protocol):
    def encode(self, frame: CapturedVideoFrame) -> list[EncodedVideoPacket]: ...
    def flush(self) -> list[EncodedVideoPacket]: ...


class AudioEncoder(Protocol):
    def encode(self, chunk: CapturedAudioChunk) -> list[EncodedAudioPacket]: ...
    def flush(self) -> list[EncodedAudioPacket]: ...
