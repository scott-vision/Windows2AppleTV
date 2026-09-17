"""Minimal synchronous RTSP/1.0 transport for AirPlay session setup."""

import plistlib
import socket
from dataclasses import dataclass
from typing import Any

from pycast.discovery.device import AirPlayDevice


@dataclass(frozen=True, slots=True)
class RtspResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class RtspClient:
    def __init__(self, device: AirPlayDevice, timeout: float = 5.0) -> None:
        self.device = device
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._cseq = 0

    def connect(self) -> None:
        self._socket = socket.create_connection((self.device.address, self.device.port), self.timeout)
        self._socket.settimeout(self.timeout)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def request(self, method: str, uri: str, body: bytes = b"", headers: dict[str, str] | None = None) -> RtspResponse:
        if self._socket is None:
            raise RuntimeError("RTSP client is not connected")
        self._cseq += 1
        request_headers = {
            "CSeq": str(self._cseq),
            "User-Agent": "AirPlay/935.7.1",
            "X-Apple-ProtocolVersion": "1",
            "Content-Length": str(len(body)),
            **(headers or {}),
        }
        lines = [f"{method} {uri} RTSP/1.0"] + [f"{key}: {value}" for key, value in request_headers.items()]
        self._socket.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        return self._read_response()

    def request_plist(self, method: str, uri: str, values: dict[str, Any], headers: dict[str, str] | None = None) -> RtspResponse:
        return self.request(
            method,
            uri,
            plistlib.dumps(values, fmt=plistlib.FMT_BINARY),
            {"Content-Type": "application/x-apple-binary-plist", **(headers or {})},
        )

    def _read_response(self) -> RtspResponse:
        assert self._socket is not None
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = self._socket.recv(1)
            if not chunk:
                raise RuntimeError("receiver closed the RTSP connection before replying")
            data.extend(chunk)
            if len(data) > 64_000:
                raise RuntimeError("RTSP response headers exceed size limit")
        header_bytes, _, remainder = bytes(data).partition(b"\r\n\r\n")
        lines = header_bytes.decode("iso-8859-1").split("\r\n")
        try:
            status = int(lines[0].split()[1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError("invalid RTSP status line") from exc
        response_headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                response_headers[key.strip().lower()] = value.strip()
        try:
            content_length = int(response_headers.get("content-length", "0"))
        except ValueError as exc:
            raise RuntimeError("receiver returned an invalid RTSP Content-Length") from exc
        if content_length < 0 or content_length > 16_000_000:
            raise RuntimeError("receiver returned an unsafe RTSP response size")
        while len(remainder) < content_length:
            chunk = self._socket.recv(content_length - len(remainder))
            if not chunk:
                raise RuntimeError("receiver closed the RTSP connection before the response body was complete")
            remainder += chunk
        return RtspResponse(status, response_headers, remainder[:content_length])
