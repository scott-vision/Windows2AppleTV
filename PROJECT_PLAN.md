# Windows → Apple TV Screen Mirroring

## Project Goal

Build a Python-first Windows application that mirrors a Windows display **with system audio** directly to an Apple TV using the Apple TV's built-in AirPlay receiver.

The project must:

- run on Windows 10/11 x64;
- require **no application to be installed on the Apple TV**;
- discover Apple TVs automatically on the local network;
- support Apple TV pairing, authentication, and credential persistence;
- mirror one Windows display in real time;
- capture Windows system/output audio via WASAPI loopback;
- transmit synchronized video and audio through AirPlay;
- use H.264 video initially;
- use ALAC audio where supported;
- target 1080p30 first, then 1080p60;
- operate entirely on the local network;
- eventually ship as a normal Windows executable;
- remain contained within a **single GitHub repository**.

The project is Python-first, but it does **not** need to be "100% pure Python." Native-backed Python libraries should be used where they materially improve reliability or performance, especially for capture, codecs, and cryptography.

The AirPlay sender itself should belong to this repository. The project should **not** simply wrap a paid mirroring application or require an external mirroring program to be installed.

---

# Scope

## Version 1 target

| Area | Target |
|---|---|
| Host OS | Windows 10/11 x64 |
| Receiver | Apple TV with built-in AirPlay receiver |
| Apple TV companion app | None |
| Displays | One selected Windows monitor |
| Video codec | H.264 |
| Video resolution | Up to 1920×1080 |
| Initial frame rate | 30 fps |
| Later frame rate | 60 fps |
| Audio source | Windows system/output audio |
| Audio transport | AirPlay screen audio |
| Preferred audio codec | ALAC |
| Discovery | mDNS / Bonjour |
| Authentication | Apple TV PIN/password pairing |
| Credential persistence | Windows secure credential storage |
| Network | Local LAN only |
| Initial UI | CLI |
| Later UI | Native-feeling desktop GUI |
| DRM-protected playback | Explicitly unsupported |

## Explicitly out of scope for the initial implementation

Do not initially attempt:

- 4K;
- HDR;
- HEVC;
- multiple simultaneous displays;
- multiple Apple TVs;
- microphone mixing;
- remote/WAN casting;
- DRM-protected video capture;
- elaborate GUI work;
- installer work before the core streaming path works.

These can be considered after the 1080p H.264 + system-audio path is stable.

---

# Core Engineering Principle

The system should be designed as independent subsystems:

1. **AirPlay protocol**
2. **Windows video capture**
3. **Windows audio capture**
4. **Video/audio codecs**
5. **A/V synchronization**
6. **Application/session orchestration**
7. **Diagnostics**
8. **CLI / later GUI**

The AirPlay implementation must not depend directly on DXcam, WASAPI, or any specific capture backend.

Likewise, the capture layer should not know anything about AirPlay packet formats.

This separation is critical for testing, debugging, and possible future Linux/macOS support.

---

# High-Level Architecture

```text
                         ┌─────────────────────┐
                         │     Python app      │
                         │ CLI / later GUI     │
                         └──────────┬──────────┘
                                    │
                 ┌──────────────────┴──────────────────┐
                 │                                     │
         AirPlay protocol                         Media pipeline
                 │                                     │
     ┌───────────┼────────────┐             ┌──────────┴───────────┐
     │           │            │             │                      │
 discovery    pairing       RTSP         VIDEO                  AUDIO
     │           │            │             │                      │
 zeroconf      HAP/SRP     session         DXcam             WASAPI loopback
                 │            │             │                      │
            FairPlay SAP      │           PyAV                   PyAV
                 │            │             │                      │
            encryption        │         H.264 encode            ALAC encode
                 └──────┬─────┘             │                      │
                        │                   framing                 RTP
                        │                     │                      │
                        └──────────────┬──────┴───────────┬─────────┘
                                       │                  │
                                shared clock         A/V scheduler
                                       │                  │
                                       └────────┬─────────┘
                                                │
                                                ▼
                                            Apple TV
```

---

# Recommended Technology Choices

## Python

Target:

```text
Python 3.12
```

Python 3.12 provides a conservative compatibility target for the native-backed libraries likely to be used.

Use `uv` for environment and dependency management unless there is a clear technical reason not to.

---

# Video Capture

Preferred initial library:

```text
DXcam
```

Use DXcam for Windows desktop capture.

Reasons:

- built for high-rate Windows capture;
- uses native Windows capture APIs;
- produces NumPy-compatible frames;
- integrates cleanly with PyAV;
- avoids using OpenCV as a screen-capture abstraction.

The video capture layer must expose a generic interface, for example:

```python
class VideoCapture:
    def start(self) -> None: ...

    def grab(self) -> CapturedVideoFrame | None: ...

    def stop(self) -> None: ...
```

The AirPlay pipeline must consume this interface, not DXcam directly.

---

# Audio Capture

Use Windows **WASAPI loopback** to capture the sound being sent to the selected Windows output device.

Preferred initial library:

```text
PyAudioWPatch
```

The audio capture layer should expose a generic interface such as:

```python
class AudioCapture:
    def start(self) -> None: ...

    def read(self) -> CapturedAudioChunk: ...

    def stop(self) -> None: ...
```

The implementation must:

- enumerate Windows output devices;
- identify the default output;
- locate the corresponding WASAPI loopback input;
- expose PCM frames with timestamps;
- survive ordinary audio-device changes cleanly where possible.

Do not couple WASAPI code directly to the AirPlay audio transport.

---

# Video Encoding

Use:

```text
PyAV / FFmpeg
```

Initial codec:

```text
H.264
```

For early development, prefer software encoding because it removes hardware-specific variables while validating the AirPlay protocol.

Initial encoder:

```text
libx264
```

Later add automatic hardware acceleration:

1. NVIDIA NVENC
2. Intel Quick Sync
3. AMD AMF
4. fallback to libx264

The encoder should be abstracted:

```python
class VideoEncoder:
    def encode(self, frame: CapturedVideoFrame) -> list[EncodedVideoPacket]: ...

    def flush(self) -> list[EncodedVideoPacket]: ...
```

The encoder must expose enough information for:

- SPS/PPS handling;
- keyframe identification;
- timestamps;
- codec configuration;
- AirPlay NAL framing.

---

# Audio Encoding

Preferred initial codec:

```text
ALAC
```

Do not assume every receiver advertises exactly the same audio capabilities.

The AirPlay capability negotiation layer should parse the receiver's advertised screen-audio formats and select a supported format.

Initial target:

```text
ALAC
16-bit
stereo
44.1 kHz or 48 kHz
```

PyAV should be used for:

- resampling;
- channel conversion;
- audio encoding.

The audio encoder should expose an interface such as:

```python
class AudioEncoder:
    def encode(self, chunk: CapturedAudioChunk) -> list[EncodedAudioPacket]: ...
```

---

# AirPlay Discovery

Use:

```text
zeroconf
```

Discover Apple TV receivers through mDNS / Bonjour.

At minimum inspect:

```text
_airplay._tcp
```

and any other relevant advertised services required for receiver capabilities or audio.

Represent discovered receivers as structured objects:

```python
@dataclass
class AirPlayDevice:
    name: str
    address: str
    port: int
    device_id: str | None
    model: str | None
    features: int | None
    properties: dict[str, str]
```

Discovery must be independent from pairing and session establishment.

---

# AirPlay Protocol

This is the highest-risk subsystem.

The repository should implement the sender-side protocol rather than shelling out to a proprietary application.

Use existing open-source implementations as **protocol references**, particularly:

- `omarroth/doubletake`
- `postlund/pyatv`
- other credible AirPlay protocol documentation and implementations

`doubletake` is especially useful because it implements real AirPlay screen mirroring and screen audio against modern Apple TVs.

The implementation is expected to require support for several of the following areas:

- mDNS discovery;
- `/info` capability retrieval;
- RTSP-style AirPlay control;
- binary plist handling;
- PIN pairing;
- HAP / SRP authentication;
- encrypted control sessions;
- FairPlay SAP;
- mirroring key derivation;
- ChaCha20-Poly1305 or other required session crypto;
- screen mirroring SETUP negotiation;
- screen-audio SETUP negotiation;
- timing negotiation;
- H.264 mirror framing;
- RTP audio transport;
- connection teardown.

Do not implement all of this in one module.

Suggested hierarchy:

```text
airplay/
├── client.py
├── device.py
├── rtsp.py
├── plist.py
├── session.py
├── auth/
│   ├── hap.py
│   ├── srp.py
│   ├── pairing.py
│   └── credentials.py
├── fairplay/
│   ├── sap.py
│   ├── keys.py
│   └── constants.py
├── mirror/
│   ├── framing.py
│   ├── crypto.py
│   └── transport.py
├── audio/
│   ├── rtp.py
│   ├── crypto.py
│   └── transport.py
└── timing/
    ├── clock.py
    ├── ntp.py
    ├── ptp.py
    └── scheduler.py
```

Do not blindly copy undocumented constants without documenting where they came from and what they appear to represent.

---

# Pairing and Credential Storage

The expected user experience is:

```text
Apple TV found:
  Living Room

Connecting...

Enter code shown on TV: 4721

Pairing successful.

Mirroring Display 1...
```

Credentials should persist so the Apple TV does not require re-pairing every time.

Use Windows secure credential storage through:

```text
keyring
```

Do not store long-lived pairing secrets in plaintext configuration files.

A non-secret device metadata cache may use `platformdirs` for its location.

---

# AirPlay Session State Machine

Session state should be explicit.

Suggested state machine:

```text
DISCOVERING
    ↓
FOUND
    ↓
CONNECTING
    ↓
PAIRING ──────────┐
    ↓              │
AUTHENTICATED ◄────┘
    ↓
NEGOTIATING
    ↓
VIDEO_READY
    ↓
AUDIO_READY
    ↓
STREAMING
    ↓
STOPPING
    ↓
DISCONNECTED
```

Represent this in code, for example with an `Enum`.

Do not represent connection state through unrelated booleans such as:

```python
connected = True
paired = True
streaming = False
```

A formal state model will make reconnection and error handling much easier.

---

# A/V Synchronization

Audio must be a first-class part of the architecture from the beginning.

Do not initially build a video architecture that later has audio bolted onto it.

Use a shared monotonic local clock:

```python
time.perf_counter_ns()
```

Every captured video frame and audio chunk should receive a timestamp as close to acquisition as practical.

Conceptually:

```text
capture timestamp
      ↓
shared timeline
      ↓
   ┌──┴───┐
   │      │
 video   audio
   │      │
presentation timestamps
   │      │
   └──┬───┘
      ↓
AirPlay clock mapping
```

The synchronization layer should be responsible for:

- mapping local timestamps to AirPlay presentation time;
- buffering;
- queue depths;
- frame dropping;
- audio drift correction;
- presentation latency;
- audio/video offset;
- receiver timing information.

Do not allow the audio and video pipelines to independently invent presentation timestamps.

---

# Diagnostics

Diagnostics are a core feature, not a later convenience.

The application should eventually report values such as:

```text
Capture FPS:          30.0
Encode FPS:           30.0
Capture→encode:       8.2 ms
Video queue:          1 frame
Audio queue:          14 ms
Target video latency: 75 ms
Target audio latency: 85 ms
Dropped frames:       0
RTT:                  4.1 ms
```

Use Python logging with structured context.

Avoid uncontrolled `print()` debugging inside protocol code.

A diagnostics layer should make it possible to enable:

- RTSP request/response tracing;
- packet counters;
- queue sizes;
- timing statistics;
- connection state transitions;
- capture timing;
- encode timing;
- dropped-frame counters.

Never log secret pairing credentials or encryption keys by default.

---

# Suggested Repository Structure

```text
.
├── src/
│   └── pycast/
│       ├── __init__.py
│       ├── app/
│       │   ├── cli.py
│       │   ├── controller.py
│       │   └── state.py
│       ├── discovery/
│       │   ├── __init__.py
│       │   ├── mdns.py
│       │   ├── device.py
│       │   └── capabilities.py
│       ├── airplay/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── rtsp.py
│       │   ├── plist.py
│       │   ├── session.py
│       │   ├── auth/
│       │   │   ├── __init__.py
│       │   │   ├── hap.py
│       │   │   ├── srp.py
│       │   │   ├── pairing.py
│       │   │   └── credentials.py
│       │   ├── fairplay/
│       │   │   ├── __init__.py
│       │   │   ├── sap.py
│       │   │   ├── keys.py
│       │   │   └── constants.py
│       │   ├── mirror/
│       │   │   ├── __init__.py
│       │   │   ├── framing.py
│       │   │   ├── crypto.py
│       │   │   └── transport.py
│       │   ├── audio/
│       │   │   ├── __init__.py
│       │   │   ├── rtp.py
│       │   │   ├── crypto.py
│       │   │   └── transport.py
│       │   └── timing/
│       │       ├── __init__.py
│       │       ├── clock.py
│       │       ├── ntp.py
│       │       ├── ptp.py
│       │       └── scheduler.py
│       ├── capture/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── dxcam_capture.py
│       │   ├── audio.py
│       │   └── wasapi.py
│       ├── codecs/
│       │   ├── __init__.py
│       │   ├── h264.py
│       │   ├── alac.py
│       │   ├── resample.py
│       │   └── capabilities.py
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── video_pipeline.py
│       │   ├── audio_pipeline.py
│       │   ├── av_sync.py
│       │   └── cast_session.py
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── credentials.py
│       │   └── settings.py
│       └── diagnostics/
│           ├── __init__.py
│           ├── metrics.py
│           ├── logging.py
│           └── packet_trace.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── protocol/
│   ├── fixtures/
│   └── receiver/
├── docs/
│   ├── architecture.md
│   ├── airplay-protocol.md
│   ├── development.md
│   └── compatibility.md
├── tools/
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── LICENSE
├── README.md
├── PROJECT_PLAN.md
└── pyproject.toml
```

This is a target structure, not a requirement to create every empty module on the first commit.

Prefer creating modules when they have a real responsibility rather than generating dozens of empty files.

---

# CLI

Use:

```text
Typer
Rich
```

The initial CLI should eventually support commands similar to:

```bash
pycast discover
pycast devices
pycast probe "Living Room"
pycast pair "Living Room"
pycast displays
pycast audio-devices
pycast cast "Living Room"
pycast cast "Living Room" --display 1
pycast cast "Living Room" --display 1 --audio-device default
pycast stop
```

During early development, commands may be added incrementally.

---

# GUI

Do not build the GUI until the core sender works.

Eventually use:

```text
PySide6
```

Expected UI:

- system-tray application;
- Apple TV selector;
- monitor selector;
- audio-device selector;
- Cast;
- Stop;
- PIN dialog;
- resolution/FPS options;
- codec status;
- diagnostics view.

The GUI must orchestrate the same core APIs as the CLI.

Do not put protocol or capture logic into Qt callbacks.

---

# Dependencies

Initial dependency direction:

```toml
[project]
requires-python = ">=3.12,<3.14"

dependencies = [
    "zeroconf",
    "cryptography",
    "pynacl",
    "dxcam[winrt]",
    "av",
    "numpy",
    "PyAudioWPatch",
    "typer",
    "rich",
    "pydantic",
    "platformdirs",
    "keyring",
]
```

Do not add dependencies without a reason.

Prefer well-maintained libraries with Windows wheels.

Avoid requiring users to manually install a full development toolchain merely to run the packaged application.

---

# Development Tooling

Use:

- `uv`
- `pytest`
- `pytest-asyncio` if required
- `ruff`
- `mypy`
- GitHub Actions

Recommended commands:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

CI must run on Windows.

Linux CI may also be used for protocol-only/unit tests where useful, but Windows is authoritative for the application.

---

# Testing Strategy

This project must not depend exclusively on manual tests against a physical Apple TV.

## Unit tests

Unit-test:

- RTSP serialization/parsing;
- binary plist handling;
- RTP header construction;
- sequence-number rollover;
- timestamp conversion;
- codec capability parsing;
- state transitions;
- encryption/decryption primitives where test vectors are available;
- packet framing;
- queue behaviour;
- A/V timestamp mapping.

## Fake AirPlay receiver

Build a local test receiver inside:

```text
tests/receiver/
```

This is an important architectural requirement.

The fake receiver should progressively support enough protocol behaviour to test:

```text
sender
  ↓
fake receiver
  ↓
pair
  ↓
encrypted control
  ↓
SETUP
  ↓
video transport
  ↓
audio transport
  ↓
timing validation
```

This makes substantial parts of the sender testable in GitHub Actions.

Do not wait until the entire protocol is implemented before creating test infrastructure.

## Physical Apple TV tests

A real Apple TV remains the ultimate compatibility target.

Maintain:

```text
docs/compatibility.md
```

with:

- Apple TV hardware model;
- tvOS version;
- pairing result;
- video result;
- audio result;
- observed latency;
- known issues.

---

# Media Test Strategy

For video transport bring-up, do not immediately stream the real desktop.

Use deterministic generated content first, such as:

- solid colours;
- colour bars;
- numbered frames;
- moving timestamp;
- alternating keyframes.

For audio:

- generated sine wave;
- periodic click;
- known-frequency tone.

For A/V sync testing, generate media containing:

- visible frame numbers;
- a visible flash;
- an audio click aligned to the flash.

This allows objective measurement of synchronization.

---

# Milestones

## M0 — Repository bootstrap

Deliver:

- Python 3.12 project;
- `uv`;
- `pyproject.toml`;
- package structure;
- Ruff;
- mypy;
- pytest;
- GitHub Actions Windows CI;
- CLI entry point;
- structured logging;
- architecture documentation.

No AirPlay implementation required yet.

Acceptance:

```bash
uv sync
uv run pycast --help
uv run ruff check .
uv run mypy src
uv run pytest
```

all succeed on a supported Windows development machine.

---

## M1 — Windows media capture

Implement independently:

### Video

- enumerate displays;
- capture selected monitor;
- obtain timestamps;
- report capture FPS;
- save diagnostic frames/video.

### Audio

- enumerate output/loopback devices;
- identify default system output;
- capture WASAPI loopback PCM;
- timestamp audio;
- save diagnostic WAV.

Acceptance:

- capture Windows desktop for 30 seconds without crashing;
- capture system audio for 30 seconds without crashing;
- timestamps are monotonic;
- no AirPlay code is involved.

---

## M2 — Local encoding pipeline

Implement:

- H.264 encoding through PyAV;
- ALAC encoding through PyAV;
- resampling/channel normalization;
- encoded packet timestamp propagation;
- diagnostic mux/write output.

Acceptance:

Capture desktop + system audio simultaneously and produce a local diagnostic media file with synchronized audio/video.

This validates the Windows media path before AirPlay is introduced.

---

## M3 — Apple TV discovery and probing

Implement:

- mDNS discovery;
- receiver representation;
- `/info` request;
- capability parsing;
- CLI discovery output.

Target interaction:

```text
$ pycast discover

Apple TV
--------
Name: Living Room
Address: 192.168.1.42
Model: AppleTV14,1
AirPlay: supported
Mirroring: supported
Video: H.264
Audio: ALAC
```

Acceptance:

A physical Apple TV can be discovered and probed without hardcoded IP addresses.

---

## M4 — Pairing and authenticated control

Implement:

- PIN pairing;
- HAP/SRP requirements;
- encrypted AirPlay control session;
- secure credential persistence;
- subsequent credential reuse.

Target:

```text
$ pycast pair "Living Room"

Enter PIN displayed on Apple TV: 3814

✓ Pairing successful
✓ Credentials stored securely
```

Acceptance:

- first connection produces correct PIN workflow;
- pairing succeeds;
- credentials are securely stored;
- second connection can authenticate without repeating pairing unless the receiver requires it.

---

## M5 — Mirroring session negotiation

Implement:

- FairPlay/SAP requirements;
- RTSP session establishment;
- mirror SETUP;
- timing channel;
- video transport sockets;
- required encryption/key derivation.

Do **not** connect the real desktop initially.

Acceptance:

A physical Apple TV accepts the session and remains connected long enough to begin receiving a deterministic test video stream.

---

## M6 — Video mirroring

First stream generated video.

Then integrate DXcam.

Acceptance:

- generated colour bars display on Apple TV;
- actual Windows desktop displays;
- 1080p30 is stable;
- frame loss and latency are measured;
- disconnect is clean.

---

## M7 — Screen audio

Implement:

- screen-audio capability negotiation;
- ALAC transport;
- RTP framing;
- audio encryption if required;
- timing relationship to video.

First send a generated audio tone.

Then integrate WASAPI loopback.

Acceptance:

- generated tone plays on Apple TV;
- Windows system audio plays;
- no companion Apple TV app is required.

---

## M8 — A/V synchronization

Implement:

- shared timeline;
- presentation timestamp mapping;
- queue management;
- measured presentation latency;
- drift correction;
- frame dropping policy;
- audio/video offset correction.

Acceptance:

Using a generated flash+click test, audio/video sync remains stable during a long session.

---

## M9 — Reliability

Cover:

- network interruption;
- Apple TV disconnect;
- sleep/wake;
- display-mode change;
- audio-device change;
- application stop;
- receiver refusal;
- pairing reset;
- firewall errors;
- task cancellation;
- resource cleanup.

---

## M10 — Performance

Add:

- NVENC;
- Quick Sync;
- AMF;
- automatic encoder selection;
- 1080p60;
- adaptive bitrate;
- additional zero-copy opportunities where practical.

Do not optimize before protocol correctness is established.

---

## M11 — GUI and packaging

Implement PySide6 GUI and produce a Windows distributable.

Possible packagers:

- PyInstaller;
- Nuitka.

Acceptance:

A user can install/run the application, select an Apple TV, select a display, select an audio device, click Cast, enter a PIN if required, and mirror desktop + system audio.

---

# Initial Performance Targets

These are goals, not hard protocol assumptions.

## Video

```text
1920×1080
30 fps initially
60 fps later
H.264
```

## Latency

Initial engineering target:

```text
< 150 ms perceived end-to-end latency
```

Then reduce where possible without compromising stability.

## Stability

Target:

```text
>= 60 minutes continuous mirroring without crash or A/V drift
```

for v1 readiness.

---

# Protocol Reference Policy

Open-source AirPlay projects may be used as technical references.

Primary references likely include:

```text
omarroth/doubletake
postlund/pyatv
```

Important rule:

**Understand before translating.**

For every adapted protocol component:

- identify the relevant AirPlay stage;
- document the message flow;
- add tests;
- explain constants;
- preserve source/license attribution where required.

Avoid producing an unmaintainable line-for-line Python transcription of another implementation.

---

# Licensing

Because protocol implementation may meaningfully adapt or translate LGPL-licensed sender code, the safest initial project license is:

```text
LGPL-3.0-or-later
```

If substantial implementation is derived from LGPL code, retain the required notices and attribution.

Do not casually relicense derived code as MIT/Apache.

If a permissive license becomes important later, reassess through a clean-room implementation strategy.

---

# Security

The project handles authentication credentials and cryptographic session material.

Rules:

- never commit receiver credentials;
- never commit captured pairing data;
- never log secret keys by default;
- store long-lived pairing credentials using OS secure credential storage;
- redact sensitive values in diagnostics;
- validate network input lengths;
- avoid unsafe deserialization;
- treat the receiver as an untrusted network peer for parser robustness.

---

# Coding Principles

1. Prefer typed dataclasses/Pydantic models for protocol structures.
2. Prefer explicit state machines to loosely related booleans.
3. Keep network I/O async where it materially simplifies concurrent control/timing/media work.
4. Keep CPU-heavy capture/codec operations away from the event loop.
5. Avoid global mutable state.
6. Make cancellation explicit.
7. Always clean up sockets, capture sessions, audio handles, and codec contexts.
8. Propagate timestamps explicitly.
9. Prefer dependency injection for components that need fake implementations in tests.
10. Every non-trivial protocol parser should have tests.
11. Do not optimize around hypothetical bottlenecks.
12. Do not create speculative abstractions with no current consumer.
13. Preserve clear boundaries between capture, codec, AirPlay, timing, and UI layers.

---

# Definition of the First Major Success

The first major protocol success is **not** desktop video.

It is this:

```text
$ pycast discover

Apple TV
--------
Name: Living Room
Address: 192.168.1.42
Model: AppleTV14,1
AirPlay: supported
Mirroring: supported
Video: H.264
Audio: ALAC
Paired: no

$ pycast pair "Living Room"

Enter PIN displayed on Apple TV: 3814

✓ Pairing successful
✓ Credentials saved securely

$ pycast probe "Living Room"

✓ Encrypted AirPlay control session established
✓ Mirroring session accepted
✓ Video transport negotiated
✓ Audio transport negotiated
✓ Timing channel established
```

Once this works, the hardest architectural barrier has been crossed.

---

# Definition of v1 Success

The user can:

1. start the application on Windows;
2. see Apple TVs on the local network;
3. select an Apple TV;
4. pair using the PIN shown on the television;
5. select a Windows display;
6. select/default the Windows output-audio device;
7. start casting;
8. see their Windows desktop on the Apple TV;
9. hear synchronized Windows system audio;
10. stop casting cleanly.

No Apple TV application is installed.

---

# First Agent Task

Use the following prompt for the first coding-agent session.

---

## Agent Prompt — Bootstrap and Validate the Windows Media Foundation of the Project

You are working inside a completely empty Git repository.

Read `PROJECT_PLAN.md` in full before making any changes. It is the authoritative architecture and scope document for this project.

The project goal is a Python-first Windows application that mirrors a Windows display plus Windows system audio directly to an Apple TV through the Apple TV's built-in AirPlay receiver. The final sender will live entirely in this repository.

For this first task, **do not attempt to implement AirPlay, pairing, FairPlay, RTSP mirroring, or Apple TV streaming yet**.

Your job is to establish a clean repository and prove the Windows-side media foundations.

### Objectives

Create the initial Python project and implement the first useful local capabilities:

1. repository bootstrap;
2. Windows display enumeration;
3. Windows desktop capture;
4. Windows output/loopback audio enumeration;
5. Windows WASAPI loopback capture;
6. basic diagnostics;
7. tests and CI.

### Project requirements

Use:

- Python 3.12;
- `uv`;
- `src/` package layout;
- package name `pycast`;
- Typer for the CLI;
- Rich for human-readable terminal output;
- DXcam for Windows video capture;
- PyAudioWPatch for WASAPI loopback audio capture;
- PyAV as a dependency for later encoding, but do not build the full encoder yet unless a tiny diagnostic use is helpful;
- Ruff;
- mypy;
- pytest;
- GitHub Actions with Windows CI.

Use `PROJECT_PLAN.md` as the architecture guide.

### Important architectural rules

Do not put DXcam or PyAudioWPatch calls directly in CLI handlers.

Create explicit interfaces/data structures in the capture layer so that the underlying capture implementations can later be replaced or faked in tests.

Every captured video frame and audio chunk must carry a monotonic acquisition timestamp based on `time.perf_counter_ns()` or an equivalent monotonic clock.

The CLI should call application/service-layer code rather than acting as the application architecture itself.

Do not create dozens of empty speculative modules merely because they are shown in the future target tree. Create only the structure required by this task plus clearly justified foundations.

Do not implement Apple TV networking yet.

### Required CLI commands

Implement at least:

```bash
pycast --help
pycast displays
pycast audio-devices
pycast capture-video
pycast capture-audio
pycast doctor
```

Expected behaviour:

#### `pycast displays`

Enumerate Windows displays/capture outputs and print enough information for the user to choose one later.

#### `pycast audio-devices`

Enumerate Windows output devices and corresponding WASAPI loopback devices where available.

Clearly identify the default output device if that can be determined reliably.

#### `pycast capture-video`

Perform a short diagnostic capture from a selected/default display.

Provide CLI arguments for at least:

```text
--display
--seconds
--fps
```

It does not need to save a complete video yet.

It should:

- capture frames;
- measure elapsed time;
- count frames;
- report achieved FPS;
- report dropped/empty capture attempts if known;
- optionally save one diagnostic frame to an ignored local diagnostics directory.

#### `pycast capture-audio`

Perform a short WASAPI loopback diagnostic capture.

Provide CLI arguments for at least:

```text
--device
--seconds
```

It should:

- capture PCM from the chosen/default loopback source;
- timestamp chunks;
- report sample rate/channels/format where available;
- report the captured duration;
- optionally save a diagnostic WAV file to an ignored local diagnostics directory.

The WAV writer can use the Python standard library where practical.

#### `pycast doctor`

Report:

- Python version;
- Windows version;
- whether the process is running on Windows;
- DXcam import/availability;
- PyAudioWPatch import/availability;
- PyAV import/availability;
- display count;
- audio output/loopback-device count;
- whether basic capture prerequisites appear available.

This command must not crash simply because a device or optional capability is unavailable. Report actionable failures.

### Data models

Create typed data models for concepts such as:

```text
DisplayInfo
AudioDeviceInfo
CapturedVideoFrame
CapturedAudioChunk
```

Exact names can differ if you have a better coherent design.

Avoid leaking raw library-specific objects throughout the application.

### Logging

Set up normal Python logging.

Support a verbose/debug CLI option.

Do not spam protocol-style debug output during normal use.

### Tests

Tests must cover logic that does not require real capture hardware.

At minimum test:

- data models;
- timestamp monotonicity helpers if introduced;
- device-selection logic;
- formatting/service behaviour where useful;
- error handling for zero displays/devices using fakes/mocks.

Design capture services so fake implementations can be injected into tests.

Do not make CI depend on an actual display or audio device being available.

### Windows CI

Create `.github/workflows/ci.yml`.

At minimum run on:

```text
windows-latest
Python 3.12
```

Run:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

If installation of one of the Windows media dependencies behaves differently in headless GitHub Actions, solve it cleanly rather than disabling all relevant checking.

### Repository files

Create at least:

```text
pyproject.toml
README.md
LICENSE
.gitignore
src/pycast/...
tests/...
.github/workflows/ci.yml
docs/development.md
```

Use LGPL-3.0-or-later for the initial `LICENSE` unless there is a compelling repository-specific blocker.

Keep `PROJECT_PLAN.md` intact except for small corrections if it contains an objective factual error discovered during implementation. If you change it, explain exactly why.

### README

The README should remain concise at this stage.

It should state:

- the project goal;
- current status;
- Windows-only development target;
- that Apple TV mirroring itself is not implemented yet;
- setup instructions;
- current CLI commands;
- how to run lint/typecheck/tests.

Do not claim features that do not exist.

### Diagnostics output

Add an ignored location such as:

```text
.local/diagnostics/
```

for temporary captured frames/WAVs and future packet traces.

Ensure it is excluded by `.gitignore`.

### Engineering quality

Use type hints throughout.

Keep functions focused.

Avoid giant CLI functions.

Avoid broad `except Exception:` unless at a top-level boundary where the exception is logged and converted into a user-facing error.

Do not suppress type errors globally.

Do not add unnecessary dependencies.

Do not add GUI code.

Do not add an external mirroring executable.

Do not implement AirPlay in this task.

### Validation

Before finishing, run the available local validation commands and fix failures.

At minimum:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

If the environment is Windows and capture devices are available, also manually exercise:

```bash
uv run pycast doctor
uv run pycast displays
uv run pycast audio-devices
```

and, where safe:

```bash
uv run pycast capture-video --seconds 3
uv run pycast capture-audio --seconds 3
```

Do not fabricate successful hardware results if the environment does not provide the required Windows devices.

### Final response

When done, report:

1. what you implemented;
2. the resulting repository structure;
3. validation commands run and their exact result;
4. any Windows/device-specific limitation encountered;
5. important architecture decisions;
6. the most logical next task.

The next task should probably be the local H.264 + ALAC encoding pipeline or Apple TV discovery, but do not implement either unless they are needed to complete this task.
