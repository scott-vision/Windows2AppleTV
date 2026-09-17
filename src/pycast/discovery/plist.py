"""Safe property-list parsing boundary for AirPlay responses."""

import plistlib


class PlistParseError(ValueError):
    """Raised when an AirPlay plist cannot be safely decoded."""


def parse_plist(payload: bytes, max_bytes: int = 2_000_000) -> dict[str, object]:
    if len(payload) > max_bytes:
        raise PlistParseError(f"plist response exceeds the {max_bytes}-byte limit")
    try:
        value = plistlib.loads(payload)
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise PlistParseError("invalid property-list response") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PlistParseError("AirPlay plist must contain a dictionary with string keys")
    return value
