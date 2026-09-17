"""Pairing credentials and secure persistence."""

import binascii
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AirPlayCredentials:
    """Legacy AirPlay credentials: an identifier and a private 32-byte seed."""

    client_id: bytes
    private_seed: bytes

    def __post_init__(self) -> None:
        if len(self.client_id) != 8 or len(self.private_seed) != 32:
            raise ValueError("AirPlay credentials must contain an 8-byte ID and 32-byte seed")

    def serialize(self) -> str:
        return f"{self.client_id.hex()}:{self.private_seed.hex()}"

    @classmethod
    def parse(cls, value: str) -> "AirPlayCredentials":
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("invalid AirPlay credential format")
        try:
            return cls(binascii.unhexlify(parts[0]), binascii.unhexlify(parts[1]))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid AirPlay credential encoding") from exc


class CredentialStore:
    """Keyring-backed store for long-lived receiver credentials."""

    def __init__(self, service_name: str = "pycast") -> None:
        self._service_name = service_name

    def save(self, receiver_key: str, credentials: AirPlayCredentials) -> None:
        try:
            import keyring

            keyring.set_password(self._service_name, receiver_key, credentials.serialize())
        except Exception as exc:
            raise RuntimeError("Windows secure credential storage is unavailable") from exc

    def load(self, receiver_key: str) -> AirPlayCredentials | None:
        try:
            import keyring

            value = keyring.get_password(self._service_name, receiver_key)
        except Exception as exc:
            raise RuntimeError("Windows secure credential storage is unavailable") from exc
        return AirPlayCredentials.parse(value) if value else None
