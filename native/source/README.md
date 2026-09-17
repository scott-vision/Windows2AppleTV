# Vendored native AirPlay helper source

This directory is the reproducible source for `..\pycast-airplay.exe`. It is
derived from the LGPL-3.0-or-later `doubletake` AirPlay implementation at:

https://github.com/omarroth/doubletake

The development snapshot used for the initial integration was upstream commit
`ae067228d76df011375164814b729932ed55ca2f`, with the framed-stdin helper,
Windows build fixes, and the session/send-path changes documented in the
project history. Keep this source and `go.mod`/`go.sum` together when making
native changes.

Rebuild from the repository root with:

```powershell
.\native\build-helper.ps1
```

Rebuilding is only needed when changing native protocol code. Run the normal
Python checks and perform a live Apple TV test before committing a replacement
EXE.
