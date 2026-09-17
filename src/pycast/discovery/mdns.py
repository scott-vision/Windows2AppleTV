"""mDNS discovery for AirPlay receivers."""

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from .device import AirPlayDevice

LOGGER = logging.getLogger(__name__)
SERVICE_TYPE = "_airplay._tcp.local."


class AirPlayDiscovery(Protocol):
    def discover(self, timeout: float = 5.0) -> list[AirPlayDevice]: ...


def select_device(devices: list[AirPlayDevice], name: str) -> AirPlayDevice:
    matches = [device for device in devices if device.name == name]
    if not matches:
        raise LookupError(f'No AirPlay device named "{name}" was found.')
    if len(matches) > 1:
        addresses = ", ".join(device.address for device in matches)
        raise LookupError(f'AirPlay device name "{name}" is ambiguous ({addresses}).')
    return matches[0]


def _decode_properties(properties: dict[bytes, bytes | None]) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for raw_key, raw_value in properties.items():
        try:
            key = raw_key.decode("utf-8", errors="replace")
            value = (raw_value or b"").decode("utf-8", errors="replace")
        except AttributeError:
            continue
        decoded[key] = value
    return decoded


def device_from_service_info(info: Any) -> AirPlayDevice | None:
    addresses = [address for address in info.parsed_addresses() if ":" not in address]
    try:
        port = int(info.port)
    except (TypeError, ValueError):
        return None
    if not addresses or not 1 <= port <= 65535:
        return None
    properties = _decode_properties(info.properties or {})
    features: int | None = None
    raw_features = properties.get("features")
    if raw_features:
        try:
            features = int(raw_features, 0)
        except ValueError:
            LOGGER.debug("Ignoring malformed AirPlay features value")
    return AirPlayDevice(
        name=properties.get("name") or str(info.name).removesuffix("._airplay._tcp.local."),
        address=addresses[0],
        port=port,
        device_id=properties.get("deviceid"),
        model=properties.get("model"),
        features=features,
        properties=properties,
    )


def deduplicate_devices(devices: list[AirPlayDevice]) -> list[AirPlayDevice]:
    unique: dict[tuple[str, str, int], AirPlayDevice] = {}
    for device in devices:
        key = ("id", device.device_id, 0) if device.device_id else ("address", device.address, device.port)
        unique.setdefault(key, device)
    return list(unique.values())


class ZeroconfDiscovery:
    """Discover AirPlay services for a bounded period."""

    def __init__(self, zeroconf_factory: Callable[[], Any] | None = None, browser_factory: Callable[..., Any] | None = None) -> None:
        self._zeroconf_factory = zeroconf_factory
        self._browser_factory = browser_factory

    def discover(self, timeout: float = 5.0) -> list[AirPlayDevice]:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        try:
            from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
        except ImportError as exc:
            raise RuntimeError("zeroconf is required for AirPlay discovery") from exc
        zeroconf = (self._zeroconf_factory or Zeroconf)()
        devices: list[AirPlayDevice] = []

        def on_change(*args: Any, **kwargs: Any) -> None:
            # zeroconf 0.14x calls handlers with keywords; older releases used
            # positional arguments. Supporting both keeps discovery portable.
            _zc, _service_type, name, state_change = (kwargs.get("zeroconf"), kwargs.get("service_type"), kwargs.get("name"), kwargs.get("state_change")) if kwargs else args
            if state_change not in (ServiceStateChange.Added, ServiceStateChange.Updated):
                return
            info = _zc.get_service_info(SERVICE_TYPE, name, timeout=1_000)
            if info is not None:
                device = device_from_service_info(info)
                if device is not None:
                    devices.append(device)

        browser = (self._browser_factory or ServiceBrowser)(zeroconf, SERVICE_TYPE, handlers=[on_change])
        try:
            time.sleep(timeout)
        finally:
            browser.cancel()
            zeroconf.close()
        return deduplicate_devices(devices)
