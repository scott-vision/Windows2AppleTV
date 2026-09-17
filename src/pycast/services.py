"""Application services used by the CLI and by future UI clients."""

import time
import wave
from dataclasses import dataclass
from pathlib import Path

from .capture.base import (
    AudioEnumerator,
    AudioFactory,
    DisplayEnumerator,
    VideoFactory,
)
from .capture.models import AudioDeviceInfo, CapturedVideoFrame, DisplayInfo


class CaptureUnavailableError(RuntimeError):
    """Raised when a requested capture source cannot be selected or started."""


@dataclass(frozen=True, slots=True)
class VideoDiagnostic:
    frames: int
    empty_attempts: int
    elapsed_seconds: float
    achieved_fps: float
    sample_frame: CapturedVideoFrame | None


@dataclass(frozen=True, slots=True)
class AudioDiagnostic:
    chunks: int
    captured_seconds: float
    sample_rate: int
    channels: int
    sample_width: int
    wav_path: Path | None


def choose_display(displays: list[DisplayInfo], requested: int | None) -> DisplayInfo:
    if not displays:
        raise CaptureUnavailableError("No displays were found. Run this command on Windows with a monitor attached.")
    index = 0 if requested is None else requested
    matches = [display for display in displays if display.index == index]
    if not matches:
        raise CaptureUnavailableError(f"Display {index} was not found; available indexes: 0-{len(displays) - 1}.")
    return matches[0]


def choose_audio_device(devices: list[AudioDeviceInfo], requested: int | None) -> AudioDeviceInfo:
    loopbacks = [device for device in devices if device.is_loopback]
    if not loopbacks:
        raise CaptureUnavailableError("No WASAPI loopback devices were found. Check Windows output devices and PyAudioWPatch.")
    if requested is not None:
        matches = [device for device in loopbacks if device.index == requested]
        if not matches:
            raise CaptureUnavailableError(f"Loopback device {requested} was not found.")
        return matches[0]
    return next((device for device in loopbacks if device.is_default), loopbacks[0])


def run_video_diagnostic(factory: VideoFactory, display_index: int, seconds: float, fps: int) -> VideoDiagnostic:
    if seconds <= 0 or fps <= 0:
        raise ValueError("seconds and fps must be positive")
    capture = factory(display_index)
    frames = 0
    empty = 0
    sample: CapturedVideoFrame | None = None
    started = time.perf_counter()
    capture.start(fps)
    try:
        deadline = started + seconds
        while time.perf_counter() < deadline:
            frame = capture.grab()
            if frame is None:
                empty += 1
                time.sleep(min(0.001, 1 / fps))
            else:
                frames += 1
                sample = sample or frame
    finally:
        capture.stop()
    elapsed = time.perf_counter() - started
    return VideoDiagnostic(frames, empty, elapsed, frames / elapsed if elapsed else 0.0, sample)


def save_video_frame(frame: CapturedVideoFrame, path: Path) -> None:
    """Write one captured NumPy-compatible frame through PyAV."""
    try:
        import av
    except ImportError as exc:
        raise CaptureUnavailableError("PyAV is required to save a diagnostic frame") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    pixel_format = "bgra" if getattr(frame.data, "shape", (0, 0, 0))[-1] == 4 else "bgr24"
    video_frame = av.VideoFrame.from_ndarray(frame.data, format=pixel_format)
    with av.open(str(path), mode="w", format="image2") as container:
        stream = container.add_stream("png")
        for packet in stream.encode(video_frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def run_audio_diagnostic(factory: AudioFactory, device: AudioDeviceInfo, seconds: float, wav_path: Path | None = None) -> AudioDiagnostic:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    capture = factory(device)
    chunks: list[bytes] = []
    started = time.perf_counter()
    capture.start()
    try:
        while time.perf_counter() - started < seconds:
            chunk = capture.read()
            chunks.append(chunk.data)
    finally:
        capture.stop()
    elapsed = time.perf_counter() - started
    if wav_path is not None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), "wb") as output:
            output.setnchannels(capture.info.channels or 2)
            output.setsampwidth(2)
            output.setframerate(capture.info.sample_rate or 48000)
            output.writeframes(b"".join(chunks))
    return AudioDiagnostic(
        len(chunks),
        elapsed,
        capture.info.sample_rate or 48000,
        capture.info.channels or 2,
        2,
        wav_path,
    )


def enumerate_displays_safe(enumerator: DisplayEnumerator) -> list[DisplayInfo]:
    return list(enumerator())


def enumerate_audio_safe(enumerator: AudioEnumerator) -> list[AudioDeviceInfo]:
    return list(enumerator())
