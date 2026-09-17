"""First unauthenticated AirPlay screen-mirroring session path."""

import plistlib
import random
import socket
import struct
import uuid
from dataclasses import dataclass
from typing import Any

from pycast.capture.models import CapturedVideoFrame
from pycast.codecs.h264 import H264VideoEncoder
from pycast.discovery.device import AirPlayDevice

from .rtsp import RtspClient


@dataclass(frozen=True, slots=True)
class MirrorSetup:
    width: int
    height: int
    data_port: int
    session_id: str


class UnauthenticatedMirror:
    """Negotiate and send unencrypted H.264 video to a receiver.

    This is intentionally video-only and is useful for validating the RTSP and
    mirror framing path before FairPlay and screen-audio transport are added.
    """

    def __init__(self, device: AirPlayDevice, width: int, height: int, fps: int = 30, timeout: float = 5.0) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self._rtsp = RtspClient(device, timeout)
        self._data: socket.socket | None = None
        self._session_id = str(uuid.uuid4())
        self._sequence = 0

    def start(self) -> MirrorSetup:
        self._rtsp.connect()
        stream_id = random.randrange(1_000_000_000, 9_000_000_000)
        uri = f"rtsp://{self.device.address}:{self.device.port}/{stream_id}"
        timing_port = _allocate_udp_port()
        client_device_id = _local_device_id()
        setup = {
            "deviceID": client_device_id,
            "macAddress": client_device_id,
            "sessionUUID": self._session_id,
            "sourceVersion": "280.33",
            "isScreenMirroringSession": True,
            "timingProtocol": "NTP",
            "timingPort": timing_port,
            "osBuildVersion": "13F69",
            "model": "Windows",
            "name": "pycast",
            "combinedGetInfoWithControlSetup": True,
            "updateSessionRequest": False,
        }
        response = self._rtsp.request_plist("SETUP", uri, setup)
        if response.status >= 300:
            raise RuntimeError(f"receiver rejected control SETUP with HTTP {response.status}; same-network access does not guarantee a plaintext session; encrypted/FairPlay setup may be required")
        response_info = _parse_plist(response.body)
        video_id = random.randrange(1_000_000_000, 9_000_000_000)
        video_uri = f"rtsp://{self.device.address}:{self.device.port}/{video_id}"
        video_setup = {
            "streams": [
                {
                    "type": 110,
                    "streamConnectionID": video_id,
                    "latencyMs": 75,
                    "timestampInfo": [{"name": name} for name in ("SubSu", "BePxT", "AfPxT", "BefEn", "EmEnc")],
                }
            ],
        }
        video_response = self._rtsp.request_plist("SETUP", video_uri, video_setup)
        if video_response.status >= 300:
            raise RuntimeError(f"receiver rejected video SETUP with HTTP {video_response.status}; FairPlay key setup may be required")
        video_info = _parse_plist(video_response.body)
        data_port = _find_stream_port(video_info, 110, "dataPort")
        if not data_port:
            raise RuntimeError("receiver accepted video SETUP but returned no video data port")
        self._data = socket.create_connection((self.device.address, data_port), self._rtsp.timeout)
        self._data.settimeout(2.0)
        if not bool(response_info.get("skipRecord")):
            record = self._rtsp.request("RECORD", uri, headers={"Session": self._session_id, "Range": "npt=0-", "RTP-Info": "seq=0;rtptime=0"})
            if record.status >= 300:
                raise RuntimeError(f"receiver rejected RECORD with HTTP {record.status}")
        return MirrorSetup(self.width, self.height, data_port, self._session_id)

    def send(self, frame: CapturedVideoFrame, encoder: H264VideoEncoder) -> None:
        if self._data is None:
            raise RuntimeError("mirror session has not started")
        packets = encoder.encode(frame)
        for packet in packets:
            nals = _annex_b_nals(packet.data)
            sps = next((nal for nal in nals if nal and nal[0] & 0x1F == 7), None)
            pps = next((nal for nal in nals if nal and nal[0] & 0x1F == 8), None)
            if sps is not None and pps is not None:
                self._send_codec(_avcc_config(sps, pps), packet.timestamp_ns)
            payload = b"".join(struct.pack(">I", len(nal)) + nal for nal in nals if nal and nal[0] & 0x1F in (1, 5))
            if payload:
                self._send_frame(payload, any(nal[0] & 0x1F == 5 for nal in nals if nal), packet.timestamp_ns)

    def close(self) -> None:
        if self._data is not None:
            self._data.close()
            self._data = None
        self._rtsp.close()

    def _send_codec(self, payload: bytes, timestamp_ns: int) -> None:
        header = bytearray(128)
        struct.pack_into("<I", header, 0, len(payload))
        header[4:8] = b"\x01\x00\x16\x01"
        struct.pack_into("<Q", header, 8, _ntp_timestamp(timestamp_ns))
        struct.pack_into("<ff", header, 16, self.width, self.height)
        struct.pack_into("<ff", header, 40, self.width, self.height)
        struct.pack_into("<ff", header, 56, self.width, self.height)
        self._write(bytes(header) + payload)

    def _send_frame(self, payload: bytes, keyframe: bool, timestamp_ns: int) -> None:
        header = bytearray(128)
        struct.pack_into("<I", header, 0, len(payload))
        header[4] = 0
        header[5] = 0x10 if keyframe else 0
        struct.pack_into("<Q", header, 8, _ntp_timestamp(timestamp_ns))
        self._write(bytes(header) + payload)

    def _write(self, data: bytes) -> None:
        assert self._data is not None
        self._sequence += 1
        self._data.sendall(data)


def _allocate_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _local_device_id() -> str:
    value = uuid.getnode()
    octets = [(value >> shift) & 0xFF for shift in range(40, -1, -8)]
    return ":".join(f"{octet:02X}" for octet in octets)


def _parse_plist(body: bytes) -> dict[str, Any]:
    try:
        value = plistlib.loads(body)
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise RuntimeError("receiver returned invalid SETUP plist") from exc
    if not isinstance(value, dict):
        raise RuntimeError("receiver SETUP response was not a dictionary")
    return value


def _find_stream_port(data: dict[str, Any], stream_type: int, key: str) -> int:
    for stream in data.get("streams", []):
        if isinstance(stream, dict) and stream.get("type") == stream_type:
            try:
                value = stream.get(key, 0)
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _annex_b_nals(data: bytes) -> list[bytes]:
    starts: list[int] = []
    index = 0
    while index < len(data) - 3:
        if data[index : index + 4] == b"\x00\x00\x00\x01":
            starts.append(index + 4)
            index += 4
        elif data[index : index + 3] == b"\x00\x00\x01":
            starts.append(index + 3)
            index += 3
        else:
            index += 1
    nal_units: list[bytes] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(data)
        while end > start and data[end - 1] == 0:
            end -= 1
        nal_units.append(data[start:end])
    return nal_units


def _avcc_config(sps: bytes, pps: bytes) -> bytes:
    return b"\x01" + sps[1:4] + b"\xff\xe1" + struct.pack(">H", len(sps)) + sps + b"\x01" + struct.pack(">H", len(pps)) + pps + b"\x02\x00\x00\x00"


def _ntp_timestamp(timestamp_ns: int) -> int:
    seconds, remainder = divmod(timestamp_ns, 1_000_000_000)
    return ((seconds + 2_208_988_800) << 32) | ((remainder << 32) // 1_000_000_000)
