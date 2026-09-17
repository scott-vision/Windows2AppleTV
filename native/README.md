# Native AirPlay session helper

`pycast-airplay.exe` is the Windows-native AirPlay session engine used by the
screen mirror command. It contains the HAP pair-verify, encrypted RTSP,
FairPlay SAP, and encrypted video transport implementation needed by modern
Apple TV receivers. Python remains responsible for discovery, DXcam capture,
and H.264 encoding; framed access units are sent to this helper over stdin.

The helper is built from the LGPL-3.0-or-later AirPlay implementation in the
`doubletake` reference tree. Its source/build notes are kept outside the
runtime path because the helper is a generated native artifact.
