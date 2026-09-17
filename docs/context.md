# Project context and engineering handoff

This is the durable handoff for future contributors and Codex sessions. It records the implementation, design decisions, hardware evidence, failed approaches, and current uncertainties. Never add PINs, private keys, session keys, pairing seeds, or raw debug traces here.

## Goal and current boundary

The goal is to mirror a Windows display to an Apple TV from a normal Windows laptop with one simple command. The current milestone is a real, encrypted, video-only AirPlay mirror session. Pairing, HAP authentication, FairPlay setup, and H.264 transport are implemented through the bundled native helper. System-audio transport, robust reconnects, and production packaging are not complete.

The project deliberately does not implement a general AirPlay receiver, internet streaming, arbitrary receiver access, audio in the live mirror command, automatic reconnects, or IPv6-only discovery.

## Known physical test setup

- Receiver: `Scott’s TV`
- Address observed during testing: `192.168.0.6`
- AirPlay port: `7000`
- Model: `AppleTV5,3`
- tvOS/build from `/info`: `26.6` / `23L773`
- Test computer and receiver: same `192.168.0.0/24` LAN

The address is compatibility evidence only. Runtime discovery must use mDNS; no address is hardcoded in the Python command or helper invocation.

## Runtime architecture

The application has two cooperating layers:

1. Python owns the CLI, mDNS discovery, receiver selection, display enumeration, DXcam capture, PyAV H.264 encoding, timestamps, and lifecycle cleanup.
2. `native/pycast-airplay.exe` owns modern AirPlay protocol work: RTSP control, HAP pair setup/verify, encrypted RTSP, FairPlay SAP, stream setup, encrypted video framing, feedback, timing, and data-channel heartbeats.

The boundary is intentionally narrow. Python starts the helper with the discovered address, port, and PIN, then sends framed H.264 access units to standard input:

```text
uint32 little-endian payload length
int64 little-endian Unix-nanosecond presentation timestamp
payload: one complete Annex-B H.264 access unit
```

This keeps discovery, capture, and protocol work independently testable.

## Normal command flow

From a fresh Windows checkout:

```powershell
git clone https://github.com/scott-vision/Windows2AppleTV.git
Set-Location .\Windows2AppleTV
.\scripts\setup.ps1
```

Normal mirroring is:

```powershell
.\scripts\mirror.ps1 -ReceiverName "Scott’s TV"
```

The direct equivalent is:

```powershell
.\.venv\Scripts\pycast.exe mirror "Scott’s TV"
```

The command discovers the receiver, requests a transient PIN, prompts for it, starts the helper, captures the selected display, encodes H.264, and streams until `Ctrl+C`. `-Seconds 30` is useful for a short test. A new machine may request a PIN even when the Apple TV says same-network clients do not need a user-facing password.

## Discovery and probing foundation

`src/pycast/discovery/` contains the receiver model, zeroconf discovery, plist parsing, HTTP `/info` probing, capability normalization, feature formatting, and exact/ambiguous selection. Discovery browses `_airplay._tcp.local.`, prefers IPv4, tolerates malformed TXT fields, and deduplicates by device ID or address/port.

```powershell
uv run pycast discover
uv run pycast probe "Scott’s TV"
```

The `/info` response uses safe standard-library `plistlib` handling for XML and binary plist data. Unknown capability fields are retained for diagnostics.

## Authentication and protocol decisions

There are two separate notions of “no password”:

- mDNS access-policy information controls whether the user sees a normal AirPlay password prompt;
- modern screen mirroring can still require transient PIN authorization, HAP pair setup/verify, FairPlay SAP, and encrypted media internally.

The physical Apple TV confirmed this distinction: same-network access was enabled, but screen mirroring still displayed a PIN and required the modern encrypted sequence.

The older Python pairing implementation in `src/pycast/airplay/auth/legacy.py` remains for legacy `vv=1` receivers. It is not used for the tested modern Apple TV. The native helper was chosen after early Python-only modern attempts produced receiver rejections and was the first path that completed HAP, FairPlay, and mirror setup.

## Physical receiver evidence

Non-secret evidence from the reference protocol run:

- `GET /info` returned HTTP 200 and an Apple binary plist.
- Model was `AppleTV5,3` and `screenStream` was advertised.
- `/pair-pin-start` returned HTTP 200.
- HAP pair setup and pair verify completed with the displayed PIN.
- FairPlay SAP setup completed.
- Mirror setup returned a receiver data port.
- The Windows display appeared on the Apple TV and capture ran at approximately 30 FPS.

This proves the project is past discovery/probing and authenticated session setup. It does not yet prove indefinite stable streaming.

## What was tried and what it taught us

1. Plain unauthenticated Python mirror: control `SETUP` was rejected with HTTP 403. “No password” does not mean plaintext screen mirroring is accepted.
2. Early direct HAP attempts: receiver proof/session errors occurred; they were not sufficiently compatible.
3. Reference native protocol path: HAP plus FairPlay succeeded and the TV displayed video, so the native helper became the protocol boundary.
4. Initial five-second test: zero frames were sent because the Python duration clock started before discovery, PIN entry, HAP, and FairPlay. The timer was moved to capture start.
5. Initial cleanup: Windows raised `Invalid argument` while closing the helper pipe. Cleanup now suppresses that expected close race and reports helper status.
6. Shared setup timeout: the helper reused a setup context for the session, causing roughly 15-second streams after setup consumed part of the deadline. The session lifetime was detached from the setup deadline.
7. Current transport issue: the laptop sent roughly 941–952 frames at about 30 FPS, then the Windows TCP data write failed with `WSAECONNABORTED` / “An established connection was aborted by the software in your host machine.” The helper exited with code 1 and no crash. The latest change replaces Go’s Windows vectored `net.Buffers.WriteTo` frame send with ordered ordinary writes. That change is pushed but still needs live validation.

The latest frame counts and roughly 32-second duration show that the earlier short-session timeout was fixed. The remaining socket abort could be a Windows send-path issue, receiver protocol rejection/backpressure, or another transport compatibility issue. Do not call it solved until a live run remains active beyond one minute.

## Current repository state

Latest pushed commit:

```text
The native/source bundle and rebuilt helper are included in the current HEAD
alongside the prior transport changes.
```

The repository includes Python source, hardware-independent tests, `uv.lock`, Windows CI, PowerShell setup/mirror launchers, the runnable helper at `native/pycast-airplay.exe`, and compatibility notes.

The helper is a generated Windows executable based on the LGPL-3.0-or-later AirPlay implementation. The relevant native source, `go.mod`, `go.sum`, license, provenance notes, and `native/build-helper.ps1` are now vendored under `native/source/`, so another Codex can inspect and rebuild the exact helper. A fresh laptop needs no Go installation for normal use because the tested executable is committed. Any helper rebuild must be deliberate, then the executable must be tested and committed.

## Safe next test

On the laptop:

```powershell
git pull
.\.venv\Scripts\pycast.exe mirror "Scott’s TV"
```

Leave it running for at least one minute. If it disconnects, record elapsed time, approximate frame count, helper exit code, the complete helper error line, whether the TV displayed video, and whether Firewall/VPN/Wi-Fi isolation was active.

Do not share raw native debug output without removing keys, seeds, nonces, and session material.

## Development checks

```powershell
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

The Python suite currently passes 22 tests. CI must remain independent of multicast networking, a physical Apple TV, and capture/audio hardware.

## Guidance for future changes

- Preserve the Python/native boundary unless there is a strong reason to move protocol code.
- Keep receiver addresses discovered at runtime; never encode `192.168.0.6` into production code.
- Keep `NoAudio: true` explicit until audio negotiation and transport are implemented.
- Treat a clean helper exit code as insufficient evidence; inspect duration, frames, TV output, and transport logs together.
- Prefer deterministic fake receivers or protocol fixtures before changing live timing or encryption.
- Keep credentials, HAP keys, FairPlay material, and debug traces out of GitHub.
- Update `docs/compatibility.md` whenever live receiver behavior is confirmed.
