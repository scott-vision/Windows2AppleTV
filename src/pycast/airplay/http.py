"""Small synchronous HTTP transport used by AirPlay authentication."""

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pycast.discovery.device import AirPlayDevice


@dataclass(frozen=True, slots=True)
class AirPlayHttpResponse:
    status: int
    body: bytes


class AirPlayHttpClient:
    def __init__(self, timeout: float = 5.0, max_bytes: int = 2_000_000) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def post(self, device: AirPlayDevice, path: str, body: bytes, headers: dict[str, str]) -> AirPlayHttpResponse:
        request = Request(f"http://{device.address}:{device.port}{path}", data=body, method="POST", headers={**headers, "Content-Length": str(len(body))})
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = response.read(self._max_bytes + 1)
                if len(payload) > self._max_bytes:
                    raise RuntimeError("AirPlay response exceeds configured size limit")
                return AirPlayHttpResponse(response.status, payload)
        except HTTPError as exc:
            return AirPlayHttpResponse(exc.code, exc.read(self._max_bytes))
        except (TimeoutError, URLError, OSError) as exc:
            raise RuntimeError(f"could not reach AirPlay receiver: {exc}") from exc
