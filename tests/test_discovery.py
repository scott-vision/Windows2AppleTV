import plistlib
from dataclasses import dataclass

import pytest

from pycast.discovery.device import AirPlayDevice, format_features, pairing_required
from pycast.discovery.mdns import deduplicate_devices, device_from_service_info, select_device
from pycast.discovery.plist import PlistParseError, parse_plist
from pycast.discovery.probe import AirPlayProbeError, HttpAirPlayProbe


@dataclass
class FakeServiceInfo:
    name: str = "Living Room._airplay._tcp.local."
    port: int = 7000
    properties: dict[bytes, bytes] | None = None

    def parsed_addresses(self) -> list[str]:
        return ["192.168.1.42", "fe80::1"]


def test_service_info_decodes_properties_and_uses_ipv4() -> None:
    info = FakeServiceInfo(properties={b"name": b"Living Room", b"deviceid": b"AA:BB", b"features": b"0x1"})
    device = device_from_service_info(info)
    assert device is not None
    assert device.name == "Living Room"
    assert device.address == "192.168.1.42"
    assert device.features == 1


def test_malformed_service_info_is_ignored() -> None:
    assert device_from_service_info(FakeServiceInfo(port=0)) is None
    assert device_from_service_info(FakeServiceInfo(port=7000, properties={})) is not None


def test_devices_deduplicate_by_id_then_address() -> None:
    first = AirPlayDevice("A", "10.0.0.1", 7000, device_id="same")
    second = AirPlayDevice("A", "10.0.0.2", 7000, device_id="same")
    third = AirPlayDevice("B", "10.0.0.3", 7000)
    assert deduplicate_devices([first, second, third]) == [first, third]


def test_device_selection_rejects_missing_and_ambiguous_names() -> None:
    device = AirPlayDevice("Living Room", "10.0.0.1", 7000)
    with pytest.raises(LookupError, match="No AirPlay"):
        select_device([], device.name)
    with pytest.raises(LookupError, match="ambiguous"):
        select_device([device, AirPlayDevice(device.name, "10.0.0.2", 7000)], device.name)


def test_plist_parser_accepts_xml_and_binary() -> None:
    value = {"name": "Living Room", "features": 1}
    assert parse_plist(plistlib.dumps(value, fmt=plistlib.FMT_XML)) == value
    assert parse_plist(plistlib.dumps(value, fmt=plistlib.FMT_BINARY)) == value


def test_plist_parser_rejects_invalid_and_oversized_payloads() -> None:
    with pytest.raises(PlistParseError):
        parse_plist(b"not a plist")
    with pytest.raises(PlistParseError, match="limit"):
        parse_plist(b"x", max_bytes=0)


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


def test_http_probe_normalizes_info_and_redacts_secrets() -> None:
    payload = plistlib.dumps({"name": "Living Room", "model": "AppleTV", "deviceID": "AA", "features": "0x4", "audioFormats": ["ALAC"], "pk": "secret"}, fmt=plistlib.FMT_BINARY)
    device = AirPlayDevice("Fallback", "127.0.0.1", 7000)
    probe = HttpAirPlayProbe(opener=lambda *_args, **_kwargs: FakeResponse(payload))
    result = probe.get_info(device)
    assert result.name == "Living Room"
    assert result.features == 4
    assert result.audio_formats == ("ALAC",)
    assert "pk" not in result.raw


def test_http_probe_reports_bad_status_and_oversize() -> None:
    device = AirPlayDevice("A", "127.0.0.1", 7000)
    with pytest.raises(AirPlayProbeError, match="HTTP 503"):
        HttpAirPlayProbe(opener=lambda *_args, **_kwargs: FakeResponse(b"", 503)).get_info(device)
    with pytest.raises(AirPlayProbeError, match="exceeds"):
        HttpAirPlayProbe(max_bytes=1, opener=lambda *_args, **_kwargs: FakeResponse(b"xx")).get_info(device)


def test_feature_formatting() -> None:
    assert format_features(None) == "unknown"
    assert format_features(10) == "0xa"


def test_pairing_policy_defaults_to_unauthenticated() -> None:
    assert not pairing_required(AirPlayDevice("A", "127.0.0.1", 7000))
    assert pairing_required(AirPlayDevice("A", "127.0.0.1", 7000, properties={"pw": "1"}))
