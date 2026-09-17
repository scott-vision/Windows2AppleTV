"""Windows output and WASAPI loopback enumeration."""

import sys
from contextlib import suppress
from queue import Empty, Queue
from typing import Any

from .models import AudioDeviceInfo, CapturedAudioChunk, timestamp_ns


def enumerate_audio_devices() -> list[AudioDeviceInfo]:
    if sys.platform != "win32":
        return []
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []
    audio = pyaudio.PyAudio()
    try:
        default_index: int | None = None
        with suppress(OSError, KeyError, TypeError, ValueError):
            default_index = int(audio.get_default_output_device_info()["index"])
        default_loopback_index: int | None = None
        with suppress(OSError, KeyError, TypeError, ValueError):
            default_loopback_index = int(audio.get_default_wasapi_loopback()["index"])
        devices: list[AudioDeviceInfo] = []
        for info in audio.get_loopback_device_info_generator():
            devices.append(
                _info_from_raw(
                    info,
                    is_output=False,
                    is_loopback=True,
                    default_index=default_loopback_index,
                )
            )
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get("maxOutputChannels", 0)) > 0:
                devices.append(_info_from_raw(info, is_output=True, is_loopback=False, default_index=default_index))
        return devices
    finally:
        audio.terminate()


def _info_from_raw(info: dict[str, Any], *, is_output: bool, is_loopback: bool, default_index: int | None) -> AudioDeviceInfo:
    index = int(info.get("index", -1))
    return AudioDeviceInfo(
        index,
        str(info.get("name", "Unnamed device")),
        is_output,
        is_loopback,
        int(info["defaultSampleRate"]) if info.get("defaultSampleRate") else None,
        int(info.get("maxInputChannels", info.get("maxOutputChannels", 0))) or None,
        index == default_index,
        index,
    )


class WasapiLoopbackCapture:
    """Blocking PyAudioWPatch adapter for a loopback device."""

    def __init__(self, device: AudioDeviceInfo, chunk_frames: int = 1024) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WASAPI loopback capture is available on Windows only")
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as exc:
            raise RuntimeError("PyAudioWPatch is not installed; run `uv sync` on Windows") from exc
        self.info = device
        self._audio = pyaudio.PyAudio()
        raw = self._audio.get_device_info_by_index(device.backend_index if device.backend_index is not None else device.index)
        self._rate = int(raw.get("defaultSampleRate", 48000))
        self._channels = min(int(raw.get("maxInputChannels", 2)), 2) or 2
        self._width = 2
        self._chunk_frames = chunk_frames
        self._stream: Any = None
        self._chunks: Queue[tuple[bytes, int]] = Queue()

    def start(self) -> None:
        import pyaudiowpatch as pyaudio

        def callback(data: bytes, frame_count: int, _time_info: Any, _status: Any) -> tuple[None, int]:
            del frame_count
            self._chunks.put((data, timestamp_ns()))
            return None, pyaudio.paContinue

        self._stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            input=True,
            input_device_index=self.info.backend_index or self.info.index,
            frames_per_buffer=self._chunk_frames,
            stream_callback=callback,
        )
        self._stream.start_stream()

    def read(self) -> CapturedAudioChunk:
        try:
            data, acquired_at = self._chunks.get(timeout=1.0)
        except Empty as exc:
            raise RuntimeError("WASAPI loopback produced no samples within one second") from exc
        return CapturedAudioChunk(
            data,
            acquired_at,
            self._rate,
            self._channels,
            self._width,
            len(data) // (self._channels * self._width),
        )

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        self._audio.terminate()


def pyaudiowpatch_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import pyaudiowpatch  # noqa: F401
    except ImportError:
        return False
    return True
