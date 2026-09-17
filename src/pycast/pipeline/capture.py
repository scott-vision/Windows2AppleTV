"""Concurrent capture collection for the local diagnostic pipeline."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pycast.capture.base import AudioCapture, VideoCapture
from pycast.capture.models import CapturedAudioChunk, CapturedVideoFrame


@dataclass(frozen=True, slots=True)
class CapturedMedia:
    video_frames: list[CapturedVideoFrame]
    audio_chunks: list[CapturedAudioChunk]


def collect_media(video: VideoCapture, audio: AudioCapture, seconds: float, fps: int) -> CapturedMedia:
    """Collect video and loopback audio concurrently for a bounded interval."""
    if seconds <= 0 or fps <= 0:
        raise ValueError("seconds and fps must be positive")
    video_frames: list[CapturedVideoFrame] = []
    audio_chunks: list[CapturedAudioChunk] = []
    deadline = time.perf_counter() + seconds
    video.start(fps)
    audio.start()

    def collect_video() -> None:
        while time.perf_counter() < deadline:
            frame = video.grab()
            if frame is not None:
                video_frames.append(frame)
            time.sleep(0)

    def collect_audio() -> None:
        while time.perf_counter() < deadline:
            audio_chunks.append(audio.read())

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(collect_video), executor.submit(collect_audio)]
            for future in futures:
                future.result()
    finally:
        video.stop()
        audio.stop()
    return CapturedMedia(video_frames, audio_chunks)
