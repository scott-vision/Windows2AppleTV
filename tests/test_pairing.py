import pytest

from pycast.airplay.auth.credentials import AirPlayCredentials


def test_credentials_round_trip_and_shape_validation() -> None:
    credentials = AirPlayCredentials(b"12345678", bytes(range(32)))
    assert AirPlayCredentials.parse(credentials.serialize()) == credentials
    with pytest.raises(ValueError, match="8-byte"):
        AirPlayCredentials(b"short", bytes(range(32)))
    with pytest.raises(ValueError, match="format"):
        AirPlayCredentials.parse("not-a-credential")


def test_credentials_reject_bad_hex() -> None:
    with pytest.raises(ValueError, match="encoding"):
        AirPlayCredentials.parse("zz:00")
