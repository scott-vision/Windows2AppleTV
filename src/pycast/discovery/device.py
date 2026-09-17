"""Backend-neutral AirPlay receiver models."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AirPlayDevice:
    name: str
    address: str
    port: int
    device_id: str | None = None
    model: str | None = None
    features: int | None = None
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AirPlayCapabilities:
    name: str
    model: str | None
    device_id: str | None
    features: int | None
    audio_formats: tuple[str, ...]
    video_formats: tuple[str, ...]
    supports_video: bool | None
    supports_mirroring: bool | None
    server_public_key: bytes | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def format_features(features: int | None) -> str:
    return "unknown" if features is None else f"0x{features:x}"


def pairing_required(device: AirPlayDevice) -> bool:
    """Return whether mDNS metadata explicitly requires a password/PIN."""
    value = device.properties.get("pw", "").strip().lower()
    return value in {"1", "true", "yes", "required"}
