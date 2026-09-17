from dataclasses import dataclass

from pycast.capture.models import AudioDeviceInfo, CapturedAudioChunk, CapturedVideoFrame
from pycast.pipeline.capture import collect_media


@dataclass
class FakeVideo:
    running: bool = False

    def start(self, fps: int) -> None:
        self.running = True

    def grab(self) -> CapturedVideoFrame | None:
        return CapturedVideoFrame(b"frame", 1, 0) if self.running else None

    def stop(self) -> None:
        self.running = False


@dataclass
class FakeAudio:
    info: AudioDeviceInfo = AudioDeviceInfo(1, "fake", True, True, 48_000, 2)
    running: bool = False

    def start(self) -> None:
        self.running = True

    def read(self) -> CapturedAudioChunk:
        return CapturedAudioChunk(b"\0" * 4, 1, 48_000, 2, 2, 1)

    def stop(self) -> None:
        self.running = False


def test_capture_collection_uses_both_injected_sources() -> None:
    video = FakeVideo()
    audio = FakeAudio()
    result = collect_media(video, audio, 0.01, 30)
    assert result.video_frames
    assert result.audio_chunks
    assert not video.running
    assert not audio.running
