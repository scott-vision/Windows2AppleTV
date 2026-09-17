# Development notes

Install Python 3.12 and `uv`, then run `uv sync`. The package uses a `src/` layout and keeps Windows-native dependencies behind capture implementations so model and service tests can run without capture hardware.

The capture services depend on small protocols and timestamped data models. Use fake implementations in tests; do not make tests depend on a monitor, speaker, or microphone. DXcam and PyAudioWPatch belong in `capture/`, never in CLI handlers.

The current scope includes local codecs, AirPlay discovery/probing, HAP pairing, FairPlay setup, and the native encrypted video mirror path. The live mirror is video-only; audio transport, robust session recovery, and production packaging remain future work. Temporary capture artifacts belong in `.local/diagnostics/` and must never be committed.

AirPlay discovery is currently limited to browsing `_airplay._tcp.local.` with `zeroconf`. The `probe` command performs an unauthenticated HTTP `GET /info` request and parses the XML or binary property list with `plistlib`. It does not establish an AirPlay session, pair, authenticate, or transmit media.

Legacy pairing is implemented for receivers advertising `vv=1`. It uses `/pair-pin-start`, `/pair-setup-pin`, SRP-2048, and the receiver's four-digit PIN. The resulting identifier and private seed are stored with `keyring`; they are never printed in full. Newer HAP pairing (`vv=2`) remains a separate compatibility task.

Receivers that do not advertise the `pw` property are treated as same-network/no-password receivers for the user-facing access policy. Modern screen mirroring can still require a transient PIN, HAP authentication, and FairPlay internally; `mirror` handles that flow through the bundled native helper.

The Windows helper is `native/pycast-airplay.exe`. It is a generated native artifact included so a fresh Windows checkout can run without Go. Python handles discovery, display capture, H.264 encoding, and framed handoff to the helper. Do not replace the helper with an unrelated AirPlay binary without revalidating protocol compatibility.

For manual LAN checks, run `uv run pycast discover`, then `uv run pycast probe "<exact receiver name>"`. The computer and receiver must be on the same LAN with multicast DNS permitted. Record real-device results in `docs/compatibility.md`.
