from dataclasses import FrozenInstanceError

import pytest

from pycast.capture.models import (
    AudioDeviceInfo,
    CapturedVideoFrame,
    DisplayInfo,
    timestamp_ns,
)
from pycast.services import (
    CaptureUnavailableError,
    choose_audio_device,
    choose_display,
    run_video_diagnostic,
)


def test_models_are_typed_and_immutable() -> None:
    display = DisplayInfo(0, "Display 1", 1920, 1080, is_primary=True)
    assert display.width == 1920
    with pytest.raises(FrozenInstanceError):
        display.width = 1  # type: ignore[misc]


def test_acquisition_clock_is_monotonic() -> None:
    assert timestamp_ns() <= timestamp_ns()


def test_audio_selection_prefers_default_loopback() -> None:
    devices = [
        AudioDeviceInfo(1, "Other", True, True),
        AudioDeviceInfo(2, "Default", True, True, is_default=True),
    ]
    assert choose_audio_device(devices, None).index == 2


def test_zero_devices_are_actionable() -> None:
    with pytest.raises(CaptureUnavailableError, match="No displays"):
        choose_display([], None)
    with pytest.raises(CaptureUnavailableError, match="No WASAPI"):
        choose_audio_device([], None)


class FakeVideo:
    def __init__(self) -> None:
        self.running = False
        self.calls = 0

    def start(self, fps: int) -> None:
        self.running = True

    def grab(self) -> CapturedVideoFrame | None:
        self.calls += 1
        return CapturedVideoFrame(b"frame", self.calls, 0) if self.calls == 1 else None

    def stop(self) -> None:
        self.running = False


def test_video_service_injects_fake_backend() -> None:
    fake = FakeVideo()
    result = run_video_diagnostic(lambda _: fake, 0, 0.01, 30)
    assert result.frames >= 1
    assert result.sample_frame is not None
    assert not fake.running
