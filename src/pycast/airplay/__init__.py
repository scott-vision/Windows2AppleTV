"""AirPlay authentication primitives and pairing workflows."""

from .auth.credentials import AirPlayCredentials, CredentialStore
from .auth.legacy import LegacyAirPlayPairer
from .http import AirPlayHttpClient
from .mirror import MirrorSetup, UnauthenticatedMirror
from .transient import TransientAirPlayPairer, TransientPairing

__all__ = [
    "AirPlayCredentials",
    "AirPlayHttpClient",
    "CredentialStore",
    "LegacyAirPlayPairer",
    "MirrorSetup",
    "UnauthenticatedMirror",
    "TransientAirPlayPairer",
    "TransientPairing",
]
