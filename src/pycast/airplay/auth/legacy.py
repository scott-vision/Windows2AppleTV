"""Legacy AirPlay PIN pairing using the receiver's SRP exchange."""

import binascii
import hashlib
import logging
import os
import plistlib
from typing import Any, cast

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from srptools import SRPClientSession, SRPContext, constants

from pycast.discovery.device import AirPlayDevice

from .credentials import AirPlayCredentials, CredentialStore

LOGGER = logging.getLogger(__name__)


def _sha512(*parts: bytes | str) -> bytes:
    digest = hashlib.sha512()
    for part in parts:
        digest.update(part.encode() if isinstance(part, str) else part)
    return digest.digest()


class _AppleSrpContext(SRPContext):  # type: ignore[misc]
    def get_common_session_key(self, premaster_secret: bytes) -> bytes:
        first = cast(bytes, self.hash(premaster_secret, b"\x00\x00\x00\x00", as_bytes=True))
        second = cast(bytes, self.hash(premaster_secret, b"\x00\x00\x00\x01", as_bytes=True))
        return first + second


class LegacyAirPlayPairer:
    """Perform the legacy AirPlay PIN exchange over an injected HTTP client."""

    def __init__(self, http: Any, credential_store: CredentialStore | None = None) -> None:
        self._http = http
        self._credential_store = credential_store

    def pair(self, device: AirPlayDevice, pin: str, display_name: str = "pycast") -> AirPlayCredentials:
        if len(pin) != 4 or not pin.isdecimal():
            raise ValueError("AirPlay PIN must be exactly four digits")
        credentials = AirPlayCredentials(os.urandom(8), os.urandom(32))
        signing_key = credentials.private_seed
        client_id = credentials.client_id.hex().upper()
        auth_public = _ed25519_public(signing_key)
        session = SRPClientSession(
            _AppleSrpContext(client_id, pin, prime=constants.PRIME_2048, generator=constants.PRIME_2048_GEN),
            binascii.hexlify(signing_key).decode(),
        )

        self._post(device, "/pair-pin-start", b"", {})
        first = self._post_plist(device, {"method": "pin", "user": client_id})
        try:
            salt = first["salt"]
            receiver_public = first["pk"]
            if not isinstance(salt, bytes) or not isinstance(receiver_public, bytes):
                raise ValueError("receiver returned invalid SRP parameters")
            session.process(binascii.hexlify(receiver_public).decode(), binascii.hexlify(salt).decode())
            if not session.verify_proof(session.key_proof_hash):
                raise ValueError("receiver SRP proof did not verify")
            client_public = binascii.unhexlify(session.public)
            proof = binascii.unhexlify(session.key_proof)
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("invalid legacy AirPlay pairing response") from exc

        self._post_plist(device, {"pk": client_public, "proof": proof})
        shared = binascii.unhexlify(session.key)
        aes_key = _sha512("Pair-Setup-AES-Key", shared)[:16]
        iv = bytearray(_sha512("Pair-Setup-AES-IV", shared)[:16])
        iv[-1] = (iv[-1] + 1) % 256
        encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(bytes(iv)), backend=default_backend()).encryptor()
        encrypted = encryptor.update(auth_public) + encryptor.finalize()
        self._post_plist(device, {"epk": encrypted, "authTag": encryptor.tag})
        if self._credential_store is not None:
            key = device.device_id or device.address
            self._credential_store.save(key, credentials)
        LOGGER.info("AirPlay pairing succeeded for %s", device.name)
        return credentials

    def _post_plist(self, device: AirPlayDevice, values: dict[str, object]) -> dict[str, object]:
        body = self._post(device, "/pair-setup-pin", plistlib.dumps(values, fmt=plistlib.FMT_BINARY), {"Content-Type": "application/x-apple-binary-plist"})
        try:
            parsed = plistlib.loads(body)
        except (plistlib.InvalidFileException, ValueError) as exc:
            raise RuntimeError("receiver returned invalid pairing plist") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("receiver pairing response was not a dictionary")
        return parsed

    def _post(self, device: AirPlayDevice, path: str, body: bytes, extra_headers: dict[str, str]) -> bytes:
        headers = {"User-Agent": "AirPlay/320.20", "Connection": "keep-alive", **extra_headers}
        response = self._http.post(device, path, body, headers)
        if response.status != 200:
            raise RuntimeError(f"receiver rejected {path}: HTTP {response.status}")
        return cast(bytes, response.body)


def _ed25519_public(seed: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
