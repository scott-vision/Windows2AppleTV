"""Typer command-line interface."""

import contextlib
import importlib.util
import logging
import platform
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pycast.airplay import (
    AirPlayHttpClient,
    CredentialStore,
    LegacyAirPlayPairer,
)
from pycast.capture.audio import (
    WasapiLoopbackCapture,
    enumerate_audio_devices,
    pyaudiowpatch_available,
)
from pycast.capture.displays import DxcamVideoCapture, dxcam_available, enumerate_displays
from pycast.codecs.h264 import H264VideoEncoder
from pycast.codecs.resample import normalize_pcm
from pycast.discovery import (
    AirPlayDevice,
    HttpAirPlayProbe,
    ZeroconfDiscovery,
    format_features,
    pairing_required,
    select_device,
)
from pycast.discovery.probe import AirPlayProbeError
from pycast.pipeline.capture import collect_media
from pycast.pipeline.diagnostic import DiagnosticPipeline
from pycast.services import (
    CaptureUnavailableError,
    choose_audio_device,
    choose_display,
    run_audio_diagnostic,
    run_video_diagnostic,
    save_video_frame,
)

app = typer.Typer(no_args_is_help=True, help="Windows media capture diagnostics for pycast.")
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")


def _diagnostic_path(name: str) -> Path:
    return Path(".local") / "diagnostics" / name


def _native_airplay_path() -> Path:
    candidates = [
        Path.cwd() / "native" / "pycast-airplay.exe",
        Path(__file__).resolve().parents[3] / "native" / "pycast-airplay.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("native AirPlay session helper is missing: native\\pycast-airplay.exe")


def _request_pin_display(device: AirPlayDevice, timeout: float) -> None:
    import uuid

    response = AirPlayHttpClient(timeout).post(
        device,
        "/pair-pin-start",
        b"",
        {
            "Content-Type": "application/octet-stream",
            "X-Apple-HKP": "5",
            "X-Apple-Client-Name": "pycast",
            "X-Apple-Client-ID": str(uuid.uuid4()),
            "X-Apple-SupportedPINLengths": "4",
        },
    )
    if response.status >= 300:
        raise RuntimeError(f"receiver rejected PIN display request with HTTP {response.status}")


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging.")] = False,
) -> None:
    _setup_logging(verbose)


@app.command()
def displays() -> None:
    """List Windows displays available to capture."""
    items = enumerate_displays()
    if not items:
        console.print("No displays found (display enumeration is Windows-only).")
        return
    table = Table("Index", "Name", "Resolution", "Position", "Primary")
    for item in items:
        table.add_row(
            str(item.index),
            item.name,
            f"{item.width}x{item.height}",
            f"{item.left},{item.top}",
            "yes" if item.is_primary else "",
        )
    console.print(table)


@app.command("audio-devices")
def audio_devices() -> None:
    """List Windows output and WASAPI loopback devices."""
    items = enumerate_audio_devices()
    if not items:
        console.print("No audio devices found (audio enumeration is Windows-only or PyAudioWPatch is unavailable).")
        return
    table = Table("Index", "Name", "Kind", "Rate", "Channels", "Default")
    for item in items:
        table.add_row(
            str(item.index),
            item.name,
            "loopback" if item.is_loopback else "output",
            str(item.sample_rate or ""),
            str(item.channels or ""),
            "yes" if item.is_default else "",
        )
    console.print(table)


@app.command("capture-video")
def capture_video(
    display: Annotated[int | None, typer.Option(help="Display index.")] = None,
    seconds: Annotated[float, typer.Option(min=0.1)] = 3.0,
    fps: Annotated[int, typer.Option(min=1)] = 30,
    save_frame: Annotated[bool, typer.Option("--save-frame")] = False,
) -> None:
    """Capture a short DXcam diagnostic sample."""
    try:
        selected = choose_display(enumerate_displays(), display)
        result = run_video_diagnostic(lambda index: DxcamVideoCapture(index), selected.index, seconds, fps)
    except (CaptureUnavailableError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if save_frame and result.sample_frame is not None:
        try:
            save_video_frame(result.sample_frame, _diagnostic_path("video-frame.png"))
            console.print("Saved .local/diagnostics/video-frame.png")
        except CaptureUnavailableError as exc:
            console.print(f"Frame captured, but it could not be saved: {exc}")
    console.print(f"Frames: {result.frames}; empty attempts: {result.empty_attempts}; elapsed: {result.elapsed_seconds:.2f}s; achieved FPS: {result.achieved_fps:.2f}")


@app.command("capture-audio")
def capture_audio(
    device: Annotated[int | None, typer.Option(help="Loopback device index.")] = None,
    seconds: Annotated[float, typer.Option(min=0.1)] = 3.0,
    save_wav: Annotated[bool, typer.Option("--save-wav")] = False,
) -> None:
    """Capture a short WASAPI loopback diagnostic sample."""
    try:
        selected = choose_audio_device(enumerate_audio_devices(), device)
        path = _diagnostic_path("audio-capture.wav") if save_wav else None
        result = run_audio_diagnostic(lambda item: WasapiLoopbackCapture(item), selected, seconds, path)
    except (CaptureUnavailableError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Chunks: {result.chunks}; captured: {result.captured_seconds:.2f}s; format: PCM {result.sample_width * 8}-bit, {result.sample_rate}Hz, {result.channels} channels")
    if result.wav_path:
        console.print(f"Saved {result.wav_path}")


@app.command("capture-media")
def capture_media(
    display: Annotated[int | None, typer.Option(help="Display index.")] = None,
    device: Annotated[int | None, typer.Option(help="Loopback device index.")] = None,
    seconds: Annotated[float, typer.Option(min=0.1)] = 3.0,
    fps: Annotated[int, typer.Option(min=1)] = 30,
    output: Annotated[Path, typer.Option(help="Diagnostic media output path.")] = Path(".local/diagnostics/diagnostic.mkv"),
) -> None:
    """Capture and encode synchronized local video/audio diagnostics."""
    try:
        selected_display = choose_display(enumerate_displays(), display)
        selected_audio = choose_audio_device(enumerate_audio_devices(), device)
        captured = collect_media(
            DxcamVideoCapture(selected_display.index),
            WasapiLoopbackCapture(selected_audio),
            seconds,
            fps,
        )
        audio_chunks = [normalize_pcm(chunk, selected_audio.sample_rate or 48_000, selected_audio.channels or 2) for chunk in captured.audio_chunks]
        result = DiagnosticPipeline(
            selected_display.width,
            selected_display.height,
            fps,
            selected_audio.sample_rate or 48_000,
            selected_audio.channels or 2,
        ).encode_to_file(captured.video_frames, audio_chunks, output)
    except (CaptureUnavailableError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Video frames: {result.video_frames}; audio chunks: {result.audio_chunks}; video packets: {result.video_packets}; audio packets: {result.audio_packets}")
    console.print(f"Timestamp range: {result.first_timestamp_ns} → {result.last_timestamp_ns}")
    console.print(f"Saved {result.output_path}")


@app.command()
def discover(timeout: Annotated[float, typer.Option(min=0.1)] = 5.0) -> None:
    """Discover AirPlay receivers on the local network."""
    try:
        devices = ZeroconfDiscovery().discover(timeout)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not devices:
        console.print("No AirPlay devices found. Check that the receiver and computer are on the same LAN.")
        return
    table = Table("Name", "Address", "Port", "Model", "Device ID", "Features")
    for device_item in devices:
        table.add_row(
            device_item.name,
            device_item.address,
            str(device_item.port),
            device_item.model or "unknown",
            device_item.device_id or "unknown",
            format_features(device_item.features),
        )
    console.print(table)


@app.command()
def probe(name: str, timeout: Annotated[float, typer.Option(min=0.1)] = 5.0) -> None:
    """Probe one discovered AirPlay receiver's /info capabilities."""
    try:
        device_item = select_device(ZeroconfDiscovery().discover(timeout), name)
        capabilities = HttpAirPlayProbe(timeout=timeout).get_info(device_item)
    except (AirPlayProbeError, LookupError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Name: {capabilities.name}")
    console.print(f"Address: {device_item.address}:{device_item.port}")
    console.print(f"Model: {capabilities.model or 'unknown'}")
    console.print(f"Device ID: {capabilities.device_id or 'unknown'}")
    console.print(f"Features: {format_features(capabilities.features)}")
    console.print(f"Audio formats: {', '.join(capabilities.audio_formats) or 'not advertised'}")
    console.print(f"Video formats: {', '.join(capabilities.video_formats) or 'not advertised'}")
    console.print(f"Mirroring indicator: {capabilities.supports_mirroring if capabilities.supports_mirroring is not None else 'not advertised'}")
    console.print("Pairing may be unnecessary when the receiver allows same-network clients.")
    console.print("Authenticated pairing and encrypted media streaming are not implemented yet.")


@app.command()
def mirror(
    name: str,
    display: Annotated[int | None, typer.Option(help="Display index to mirror.")] = None,
    fps: Annotated[int, typer.Option(min=1, max=60)] = 30,
    seconds: Annotated[float | None, typer.Option(min=0.1, help="Stop after this many seconds; omit to run until Ctrl-C.")] = None,
    timeout: Annotated[float, typer.Option(min=0.1)] = 5.0,
) -> None:
    """Pair once and mirror one Windows display to an Apple TV."""
    capture: DxcamVideoCapture | None = None
    native_process: subprocess.Popen[bytes] | None = None
    frames = 0
    started = 0.0
    receiver_closed = False
    helper_exit_code: int | None = None
    helper_stderr = b""
    try:
        device_item = select_device(ZeroconfDiscovery().discover(timeout), name)
        selected_display = choose_display(enumerate_displays(), display)
        _request_pin_display(device_item, timeout)
        pin = typer.prompt("Enter the PIN shown on the receiver", hide_input=False)
        if len(pin) != 4 or not pin.isdigit():
            raise ValueError("AirPlay PIN must be exactly four digits")
        helper = _native_airplay_path()
        native_process = subprocess.Popen(
            [str(helper), "-target", device_item.address, "-port", str(device_item.port), "-code", pin],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        encoder = H264VideoEncoder(selected_display.width, selected_display.height, fps)
        capture = DxcamVideoCapture(selected_display.index)
        capture.start(fps)
        # The duration applies to active capture, not discovery, PIN entry, or
        # the receiver's HAP/FairPlay setup time.
        started = time.monotonic()
        console.print(f"Mirroring {selected_display.name} to {device_item.name}; Ctrl-C to stop.")
        wall_clock_offset = time.time_ns() - time.perf_counter_ns()
        while seconds is None or time.monotonic() - started < seconds:
            frame = capture.grab()
            if frame is not None:
                for packet in encoder.encode(frame):
                    if native_process.stdin is None:
                        raise RuntimeError("native AirPlay helper has no input pipe")
                    payload = packet.data
                    timestamp = wall_clock_offset + packet.timestamp_ns
                    try:
                        native_process.stdin.write(struct.pack("<Iq", len(payload), timestamp))
                        native_process.stdin.write(payload)
                        native_process.stdin.flush()
                    except OSError as exc:
                        # The pipe can report its broken state before poll()
                        # observes that the helper has exited (notably on
                        # Windows), so do not turn a normal remote shutdown
                        # into a CLI error when the write itself is a broken
                        # pipe.
                        if isinstance(exc, BrokenPipeError) or native_process.poll() is not None:
                            receiver_closed = True
                            break
                        raise RuntimeError(f"AirPlay helper input failed: {exc}") from exc
                    frames += 1
                if receiver_closed:
                    break
            time.sleep(1 / fps)
    except KeyboardInterrupt:
        console.print("Stopping mirror…")
    except (CaptureUnavailableError, LookupError, RuntimeError, ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        if capture is not None:
            capture.stop()
        if native_process is not None:
            if native_process.stdin is not None:
                with contextlib.suppress(OSError):
                    native_process.stdin.close()
            try:
                native_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                native_process.kill()
                native_process.wait()
            helper_exit_code = native_process.returncode
            if native_process.stderr is not None:
                helper_stderr = native_process.stderr.read()
    if receiver_closed:
        console.print("AirPlay receiver closed the mirror session.")
        console.print(f"Native AirPlay helper exit code: {helper_exit_code}")
        if helper_stderr:
            diagnostic = helper_stderr.decode(errors="replace").strip()
            if diagnostic:
                console.print(f"Native AirPlay helper error: {diagnostic}")
    console.print(f"Frames sent: {frames}")


@app.command()
def pair(
    name: str,
    timeout: Annotated[float, typer.Option(min=0.1)] = 5.0,
    display_name: Annotated[str, typer.Option(help="Name stored with the pairing credentials.")] = "pycast",
) -> None:
    """Pair with a legacy AirPlay receiver using its four-digit PIN."""
    try:
        device_item = select_device(ZeroconfDiscovery().discover(timeout), name)
        if device_item.properties.get("vv") not in (None, "1"):
            raise RuntimeError("this initial pairing implementation supports legacy AirPlay receivers (vv=1)")
        if not pairing_required(device_item):
            console.print(f"{device_item.name} advertises same-network access without a PIN. AirPlay screen mirroring still performs the receiver's HAP/FairPlay authorization during session startup.")
            return
        pin = typer.prompt("Enter the PIN shown on the Apple TV", hide_input=False)
        credentials = LegacyAirPlayPairer(AirPlayHttpClient(timeout), CredentialStore()).pair(device_item, pin, display_name)
    except (LookupError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Pairing successful; credentials saved for {device_item.name} ({credentials.client_id.hex()}).")


@app.command()
def doctor() -> None:
    """Report local media-capture prerequisites."""
    console.print(f"Python: {sys.version.split()[0]}")
    console.print(f"Windows: {platform.platform()}; supported: {'yes' if sys.platform == 'win32' else 'no'}")
    for name in ("dxcam", "pyaudiowpatch", "av"):
        console.print(f"{name}: {'available' if (dxcam_available() if name == 'dxcam' else pyaudiowpatch_available() if name == 'pyaudiowpatch' else importlib.util.find_spec(name) is not None) else 'unavailable'}")
    display_count = len(enumerate_displays())
    audio_count = len(enumerate_audio_devices())
    console.print(f"Displays: {display_count}; audio/loopback devices: {audio_count}")
    console.print(f"Basic prerequisites: {'appears usable' if display_count and audio_count and dxcam_available() and pyaudiowpatch_available() else 'incomplete — check Windows capture devices and native dependencies'}")
