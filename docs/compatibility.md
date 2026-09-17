# Compatibility record

Use this file to record physical receiver tests. Do not add pairing credentials, keys, or captured sensitive data.

## Test record

- Date:
- Apple TV model:
- tvOS version:
- Computer/Windows version:
- Network topology:
- `pycast discover` result:
- `pycast probe` result:
- Probe errors or firewall notes:
- Pairing status: receiver reports same-network access, but screen mirroring requested a transient PIN; HAP pairing and FairPlay setup succeeded with the native helper
- Streaming status: encrypted H.264 video mirror setup succeeded and the Windows display appeared on the receiver; the initial CLI run exposed a Windows pipe-cleanup error, now handled gracefully

## 2026-09-17 local validation

- Apple TV model: `AppleTV5,3`
- tvOS version/build: `26.6` / `23L773` (from `/info`)
- Computer/Windows version: Windows 11, Wi-Fi `192.168.0.7`
- Network topology: same `192.168.0.0/24` LAN; receiver `192.168.0.6`
- `pycast discover` result: found Scott's TV on `192.168.0.6:7000`
- `pycast probe` result: `/info` returned successfully; model, device ID, protocol version, status flags, and capability fields parsed
- Probe errors or firewall notes: none
- Pairing status: receiver reports same-network clients do not require a PIN; screen mirroring nevertheless displayed a transient PIN and completed HAP pairing/FairPlay setup
- Streaming status: encrypted H.264 mirror setup succeeded; the display appeared on Scott's TV at approximately 30 FPS

## Current limitations

- Discovery currently browses `_airplay._tcp.local.` only.
- IPv4 addresses are preferred; IPv6-only receivers are not yet selected.
- Multicast DNS may be blocked by VPNs, guest Wi-Fi, firewalls, or network isolation.
- Receiver capability fields vary by model and tvOS version; unknown fields are retained for diagnostics.
- The live mirror currently sends video only; system audio capture/transport is not wired into the encrypted session.
