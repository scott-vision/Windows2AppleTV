# Native AirPlay session helper

`pycast-airplay.exe` is the Windows-native AirPlay session engine used by the
screen mirror command. It contains the HAP pair-verify, encrypted RTSP,
FairPlay SAP, and encrypted video transport implementation needed by modern
Apple TV receivers. Python remains responsible for discovery, DXcam capture,
and H.264 encoding; framed access units are sent to this helper over stdin.

The helper is built from the vendored LGPL-3.0-or-later AirPlay implementation
under `native/source/`. Its source, Go module lockfile, and build script are
committed so native changes are inspectable and reproducible on another
Windows machine. Normal use still requires no Go installation because the
tested executable is committed.

To rebuild after installing Go 1.25 or newer:

```powershell
.\native\build-helper.ps1
```
