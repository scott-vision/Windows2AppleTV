"""Windows monitor enumeration and DXcam backend."""

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Any

from .models import CapturedVideoFrame, DisplayInfo, timestamp_ns

LOGGER = logging.getLogger(__name__)


def enumerate_displays() -> list[DisplayInfo]:
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    monitors: list[DisplayInfo] = []
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def callback(handle: int, _dc: int, rect_ptr: Any, _data: int) -> int:
        rect = rect_ptr.contents
        index = len(monitors)
        name = f"Display {index + 1}"
        monitors.append(
            DisplayInfo(
                index,
                name,
                rect.right - rect.left,
                rect.bottom - rect.top,
                rect.left,
                rect.top,
                index == 0,
            )
        )
        return 1

    user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(callback), 0)
    return monitors


class DxcamVideoCapture:
    """Adapter that converts DXcam frames into backend-neutral frames."""

    def __init__(self, display_index: int) -> None:
        if sys.platform != "win32":
            raise RuntimeError("DXcam video capture is available on Windows only")
        try:
            import dxcam
        except ImportError as exc:
            raise RuntimeError("DXcam is not installed; run `uv sync` on Windows") from exc
        # BGRA is DXcam's native buffer format and avoids a cv2 conversion path.
        self._camera = dxcam.create(output_idx=display_index, region=None, output_color="BGRA")
        self._display_index = display_index

    def start(self, fps: int) -> None:
        self._camera.start(target_fps=fps, video_mode=True)

    def grab(self) -> CapturedVideoFrame | None:
        frame = self._camera.get_latest_frame()
        if frame is None:
            return None
        return CapturedVideoFrame(frame, timestamp_ns(), self._display_index)

    def stop(self) -> None:
        self._camera.stop()


def dxcam_available() -> bool:
    try:
        import dxcam  # noqa: F401
    except ImportError:
        return False
    return sys.platform == "win32"
