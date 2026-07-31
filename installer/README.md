# Installers

Build scripts and packaging config for standalone RTL-SDR Suite installers,
so end users don't need Python or `pip install -r requirements.txt` at all.

| Platform | Script | Output | Status |
|---|---|---|---|
| Windows | `windows/build_windows.ps1` (uses `windows/rtlsdr_suite.iss`) | `dist_installer\RTL-SDR-Suite-Setup.exe` | Built, installed, launched, uninstalled on real Windows + real dongle. Verified working. |
| Linux | `linux/build_linux.sh` | `dist_installer/rtl-sdr-suite_1.0.0_amd64.deb` and `.tar.gz` | Built, `apt install`ed, launched, `dpkg -r` removed. Verified working (headless/offscreen, no physical dongle in that environment). |
| macOS | `macos/build_macos.sh` | `dist/RTL-SDR-Suite.app` and `.dmg` | **Not tested** - no Mac was available to build/run it. See `macos/README.md` for likely trouble spots. |

## What each installer bundles

- **Windows**: the full Python/PySide6 app (via PyInstaller) *and* the
  external CLI tools (`rtl_adsb`, `rtl_433`, `rtl_fm`, `multimon-ng`,
  `librtlsdr.dll`, ...) in a `tools\` subfolder, which the installer adds to
  the user's `PATH`. Nothing else to install for the ADS-B/ISM/POCSAG tabs
  to work, beyond plugging in the dongle and installing its WinUSB driver
  (Zadig) once.
- **Linux**: the Python/PySide6 app only. The external CLI tools are *not*
  bundled - Linux has a native package manager for this (`apt install
  rtl-sdr` covers `rtl_adsb`/`rtl_fm`; `rtl_433` and `multimon-ng` may need
  to be installed from their own project releases or built from source
  depending on the distro). The `.deb`'s `Depends:`/`Recommends:` fields
  point this out at install time.
- **macOS**: same approach as Linux, via Homebrew (`brew install librtlsdr`,
  `brew install rtl_433`); `multimon-ng` usually needs building from source.

## A note on file size

Each build is roughly 65-135 MB (a full Qt + scipy + PySide6 application,
frozen). That's normal for this kind of bundle and too large to hand over as
a chat attachment here, which is why these are *build scripts* rather than
pre-built binaries in most cases - run the script once to get your own copy
of the actual installer/package.

## A bug found and fixed while building these

`pyModeS` (used by the ADS-B tab) reads its own package version via
`importlib.metadata` at import time. PyInstaller doesn't bundle that
dist-info metadata by default, so a naive frozen build crashes immediately
on startup with `PackageNotFoundError: No package metadata was found for
pyModeS`. Fixed with `--copy-metadata pyModeS` on the PyInstaller command
line (present in all three build scripts).
