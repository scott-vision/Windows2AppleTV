"""HTTP capability probing for AirPlay receivers."""

import logging
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .device import AirPlayCapabilities, AirPlayDevice
from .plist import parse_plist

LOGGER = logging.getLogger(__name__)


class AirPlayProbeError(RuntimeError):
    """Raised when a receiver cannot be probed or returns invalid data."""


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if isinstance(item, (str, int, float)))
    return ()


def capabilities_from_info(device: AirPlayDevice, data: dict[str, object]) -> AirPlayCapabilities:
    name = str(data.get("name") or device.name)
    model = str(data["model"]) if data.get("model") is not None else device.model
    device_id = str(data["deviceID"]) if data.get("deviceID") is not None else device.device_id
    feature_value = data.get("features", device.features)
    features = int(feature_value, 0) if isinstance(feature_value, str) else feature_value if isinstance(feature_value, int) else None
    audio_formats = _string_tuple(data.get("audioFormats") or data.get("audio_formats"))
    video_formats = _string_tuple(data.get("videoFormats") or data.get("video_formats"))
    public_key = data.get("pk")
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        public_key = None
    raw = {key: value for key, value in data.items() if key.lower() not in {"pk", "pi", "deviceid", "deviceID"}}
    return AirPlayCapabilities(
        name,
        model,
        device_id,
        features,
        audio_formats,
        video_formats,
        bool(video_formats) if video_formats else None,
        bool(data.get("statusFlags")) if "statusFlags" in data else None,
        public_key,
        raw,
    )


class HttpAirPlayProbe:
    """Retrieve and normalize a receiver's unauthenticated `/info` response."""

    def __init__(self, timeout: float = 5.0, max_bytes: int = 2_000_000, opener: Callable[..., Any] | None = None) -> None:
        if timeout <= 0 or max_bytes <= 0:
            raise ValueError("timeout and max_bytes must be positive")
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener or urlopen

    def get_info(self, device: AirPlayDevice) -> AirPlayCapabilities:
        request = Request(
            f"http://{device.address}:{device.port}/info",
            headers={"User-Agent": "AirPlay/320.20", "Accept": "application/x-apple-binary-plist"},
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise AirPlayProbeError(f"receiver returned HTTP {response.status}")
                payload = response.read(self._max_bytes + 1)
        except HTTPError as exc:
            raise AirPlayProbeError(f"receiver returned HTTP {exc.code}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise AirPlayProbeError(f"could not reach receiver: {exc}") from exc
        if len(payload) > self._max_bytes:
            raise AirPlayProbeError(f"/info response exceeds the {self._max_bytes}-byte limit")
        try:
            return capabilities_from_info(device, parse_plist(payload, self._max_bytes))
        except ValueError as exc:
            raise AirPlayProbeError(str(exc)) from exc
