"""PIN-less legacy AirPlay pairing used by receivers allowing local clients."""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from pycast.discovery.device import AirPlayCapabilities, AirPlayDevice

from .rtsp import RtspClient


@dataclass(frozen=True, slots=True)
class TransientPairing:
    """Ephemeral key material produced by a successful pair-verify exchange."""

    shared_secret: bytes
    client_public_key: bytes


class TransientAirPlayPairer:
    """Perform the original no-PIN AirPlay pair-setup/pair-verify exchange."""

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def pair(self, device: AirPlayDevice, capabilities: AirPlayCapabilities) -> TransientPairing:
        if capabilities.server_public_key is None:
            raise RuntimeError("receiver /info did not include the public key needed for PIN-less pairing")
        signing_key = ed25519.Ed25519PrivateKey.generate()
        client_signing_public = signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        client_key = x25519.X25519PrivateKey.generate()
        client_public = client_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        client = RtspClient(device, self.timeout)
        try:
            client.connect()
            setup = client.request(
                "POST",
                "/pair-setup",
                client_signing_public,
                {"Content-Type": "application/octet-stream", "X-Apple-HKP": "3"},
            )
            if setup.status >= 300 or len(setup.body) != 32:
                client.close()
                return self._hap_pair(device)
            server_signing_public = setup.body
            flags = {
                "X-Apple-HKP": "3",
                **({"X-Apple-PD": "1"} if capabilities.features is None or not capabilities.features & (1 << 27) else {}),
            }
            verify_request = b"\x01\x00\x00\x00" + client_public + client_signing_public
            verify = client.request(
                "POST",
                "/pair-verify",
                verify_request,
                {
                    "Content-Type": "application/octet-stream",
                    **flags,
                },
            )
            if verify.status >= 300 or len(verify.body) != 96:
                raise RuntimeError(f"receiver rejected pair-verify step 1 (HTTP {verify.status})")
            server_public = verify.body[:32]
            shared = client_key.exchange(x25519.X25519PublicKey.from_public_bytes(server_public))
            aes_key = _derive(shared, b"Pair-Verify-AES-Key")
            aes_iv = _derive(shared, b"Pair-Verify-AES-IV")
            server_signature = _aes_ctr(aes_key, aes_iv, verify.body[32:])
            server_signing = ed25519.Ed25519PublicKey.from_public_bytes(server_signing_public)
            server_signing.verify(server_signature, server_public + client_public)
            client_signature = signing_key.sign(client_public + server_public)
            encrypted = _aes_ctr(aes_key, aes_iv, b"\0" * 64, offset=64)
            encrypted = bytes(a ^ b for a, b in zip(client_signature, encrypted, strict=True))
            final = client.request(
                "POST",
                "/pair-verify",
                b"\0\0\0\0" + encrypted,
                {"Content-Type": "application/octet-stream", **flags},
            )
            if final.status >= 300:
                raise RuntimeError(f"receiver rejected pair-verify step 2 (HTTP {final.status})")
            return TransientPairing(shared, client_signing_public)
        except ValueError as exc:
            raise RuntimeError("receiver returned invalid cryptographic pairing data") from exc
        finally:
            client.close()

    def _hap_pair(self, device: AirPlayDevice) -> TransientPairing:
        client = RtspClient(device, self.timeout)
        pairing_id = str(uuid.uuid4())
        signing_key = ed25519.Ed25519PrivateKey.generate()
        signing_public = signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        client_name = "pycast"
        pair_headers = {
            "Content-Type": "application/octet-stream",
            "X-Apple-HKP": "5",
            "X-Apple-Client-Name": client_name,
            "X-Apple-Client-ID": pairing_id,
            "X-Apple-PD": "1",
        }
        try:
            client.connect()
            # Modern Apple receivers use the screen-capture HAP profile even
            # when their UI says that no password is required.  That profile
            # is ordinary SRP with an empty secret; the transient flag belongs
            # to HKP type 4 and is rejected by this receiver.
            m1 = _tlv([(0x00, b"\x00"), (0x06, b"\x01")])
            m2: dict[int, bytes] | None = None
            for attempt in range(4):
                response = client.request("POST", "/pair-setup", m1, pair_headers)
                if response.status >= 300:
                    raise RuntimeError(f"receiver rejected transient HAP pair-setup (HTTP {response.status})")
                candidate = _tlv_decode(response.body)
                if (error := candidate.get(0x07)) and error[0] == 3:
                    if attempt == 3:
                        raise RuntimeError("receiver kept pair-setup in HAP backoff after four attempts")
                    delay = int.from_bytes(candidate.get(0x08, b"\x00"), "little")
                    if delay > 30:
                        raise RuntimeError(f"receiver requested a {delay}s HAP backoff; pairing is not currently available")
                    time.sleep(delay)
                    continue
                if error := candidate.get(0x07):
                    raise RuntimeError(f"receiver rejected transient HAP pair-setup (TLV error {error[0]})")
                m2 = candidate
                break
            if m2 is None:
                raise RuntimeError("receiver did not return HAP pairing data")
            salt = m2.get(0x02)
            server_b = m2.get(0x03)
            if salt is None or server_b is None:
                raise RuntimeError("receiver returned incomplete transient HAP pairing data")
            public, proof, shared = _srp_client_proof(salt, server_b, b"")
            m3 = _tlv([(0x06, b"\x03"), (0x03, public), (0x04, proof)])
            m4_response = client.request("POST", "/pair-setup", m3, pair_headers)
            if m4_response.status >= 300:
                raise RuntimeError(f"receiver rejected transient HAP proof (HTTP {m4_response.status})")
            m4 = _tlv_decode(m4_response.body)
            if 0x07 in m4:
                raise RuntimeError(f"receiver rejected transient HAP proof (error {m4[0x07][0]})")
            if 0x04 in m4 and not _verify_srp_server_proof(public, proof, shared, m4[0x04]):
                raise RuntimeError("receiver returned an invalid transient HAP proof")
            session_key = _hkdf(shared, b"Pair-Setup-Encrypt-Salt", b"Pair-Setup-Encrypt-Info", 32)
            sig_key = _hkdf(shared, b"Pair-Setup-Controller-Sign-Salt", b"Pair-Setup-Controller-Sign-Info", 32)
            pairing_id_bytes = pairing_id.encode("ascii")
            signature = signing_key.sign(sig_key + pairing_id_bytes + signing_public)
            sub = _tlv([(0x01, pairing_id_bytes), (0x03, signing_public), (0x0A, signature), (0x12, b"\xe1\x57com.apple.ScreenCapture\x01")])
            nonce = b"\0\0\0\0PS-Msg05"
            encrypted = _chacha_seal(session_key, nonce, sub)
            m5 = _tlv([(0x05, encrypted), (0x06, b"\x05")])
            final = client.request("POST", "/pair-setup", m5, pair_headers)
            if final.status >= 300:
                raise RuntimeError(f"receiver rejected transient HAP identity (HTTP {final.status})")
            return TransientPairing(shared, signing_public)
        finally:
            client.close()


def _derive(shared: bytes, label: bytes) -> bytes:
    return hashlib.sha512(label + shared).digest()[:16]


_SRP_N = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64"
    "ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6B"
    "F12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB31"
    "43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF",
    16,
)


def _srp_pad(value: int) -> bytes:
    return value.to_bytes(384, "big")


def _srp_client_proof(salt: bytes, server_b_bytes: bytes, password: bytes) -> tuple[bytes, bytes, bytes]:
    username = b"Pair-Setup"
    generator = 5
    server_b = int.from_bytes(server_b_bytes, "big")
    inner = hashlib.sha512(username + b":" + password).digest()
    x = int.from_bytes(hashlib.sha512(salt + inner).digest(), "big")
    k = int.from_bytes(hashlib.sha512(_srp_pad(_SRP_N) + _srp_pad(generator)).digest(), "big")
    private = secrets.randbelow(_SRP_N - 1) + 1
    public_int = pow(generator, private, _SRP_N)
    public = _srp_pad(public_int)
    server_public = _srp_pad(server_b)
    public_natural = public_int.to_bytes((public_int.bit_length() + 7) // 8, "big")
    server_natural = server_b.to_bytes((server_b.bit_length() + 7) // 8, "big")
    u = int.from_bytes(hashlib.sha512(public + server_public).digest(), "big")
    gx = pow(generator, x, _SRP_N)
    shared_int = pow((server_b - k * gx) % _SRP_N, private + u * x, _SRP_N)
    shared = hashlib.sha512(shared_int.to_bytes((shared_int.bit_length() + 7) // 8, "big")).digest()
    hn = hashlib.sha512(_SRP_N.to_bytes(384, "big")).digest()
    hg = hashlib.sha512(generator.to_bytes(384, "big")).digest()
    proof = hashlib.sha512(bytes(a ^ b for a, b in zip(hn, hg, strict=True)) + hashlib.sha512(username).digest() + salt + public_natural + server_natural + shared).digest()
    return public, proof, shared


def _verify_srp_server_proof(public: bytes, proof: bytes, shared: bytes, server_proof: bytes) -> bool:
    return server_proof == hashlib.sha512(public.lstrip(b"\0") + proof + shared).digest()


def _aes_ctr(key: bytes, iv: bytes, payload: bytes, offset: int = 0) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
    if offset:
        cipher.update(b"\0" * offset)
    return cipher.update(payload) + cipher.finalize()


def _tlv(items: list[tuple[int, bytes]]) -> bytes:
    output = bytearray()
    for tag, value in items:
        for offset in range(0, len(value), 255):
            chunk = value[offset : offset + 255]
            output.extend((tag, len(chunk)))
            output.extend(chunk)
    return bytes(output)


def _tlv_decode(data: bytes) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    index = 0
    while index < len(data):
        if index + 2 > len(data):
            raise RuntimeError("receiver returned truncated pairing TLV")
        tag, length = data[index], data[index + 1]
        index += 2
        value = data[index : index + length]
        if len(value) != length:
            raise RuntimeError("receiver returned truncated pairing TLV value")
        index += length
        result[tag] = result.get(tag, b"") + value
    return result


def _hkdf(secret: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA512(), length=length, salt=salt, info=info).derive(secret)


def _hex_bytes(value: str | bytes) -> bytes:
    return bytes.fromhex(value) if isinstance(value, str) else value


def _chacha_seal(key: bytes, nonce: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    return ChaCha20Poly1305(key).encrypt(nonce, data, None)
