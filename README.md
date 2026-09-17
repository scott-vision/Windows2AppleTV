# pycast

`pycast` mirrors a Windows display to an Apple TV over the local network. The current live path discovers the receiver with mDNS, requests the receiver PIN, performs HAP pairing and FairPlay setup, and sends H.264 video through an encrypted AirPlay session. System audio is not yet included in the live mirror path.

## Move to another Windows laptop

Clone the repository, install Python 3.12 and [uv](https://docs.astral.sh/uv/), then run:

```powershell
Set-Location 'C:\path\to\Windows2AppleTV'
.\scripts\setup.ps1
```

The native AirPlay helper is included at `native\pycast-airplay.exe`; no Go installation or native build is required for normal use. If PowerShell blocks local scripts, use `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1`.

After setup, the simplest mirror command is:

```powershell
Set-Location 'C:\path\to\Windows2AppleTV'; .\.venv\Scripts\pycast.exe mirror "Scott’s TV"
```

Or use the portable launcher, which finds the repository relative to the script:

```powershell
.\scripts\mirror.ps1 -ReceiverName "Scott’s TV"
```

The first connection displays a PIN on the Apple TV. Enter it when prompted. Press `Ctrl+C` to stop. Use `-Seconds 30` for a short test. The laptop and Apple TV must be on the same non-isolated LAN; allow Python/`pycast-airplay.exe` through Windows Firewall when prompted.

## Commands

```powershell
uv run pycast discover
uv run pycast probe "Scott’s TV"
uv run pycast mirror "Scott’s TV"
uv run pycast displays
uv run pycast audio-devices
uv run pycast capture-media
uv run pycast doctor
```

`discover` and `probe` are hardware-independent at test time but require LAN access when used live. Diagnostics are written below ignored `.local\diagnostics\`.

## Development checks

```powershell
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Pairing credentials are stored by the local credential store and must never be committed. Avoid running with debug logging when sharing logs because AirPlay protocol traces can contain session secrets. See [development notes](docs/development.md) and the [compatibility record](docs/compatibility.md).
