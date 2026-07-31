# macOS build (untested on real hardware)

This build script was written by analogy to the already-tested Windows
(PyInstaller + Inno Setup) and Linux (PyInstaller + .deb/tar.gz) builds of
this project, but there is no Mac available in the environment that built
this project, so **`build_macos.sh` has never actually been run**. Please
try it and report back what breaks.

## Prerequisites

```bash
xcode-select --install        # command line tools, for codesign
brew install python@3.11      # or any Python 3.10+
brew install librtlsdr        # provides rtl_adsb, rtl_fm, rtl_test, rtl_sdr
brew install rtl_433          # for the ISM scanner tab
# multimon-ng (POCSAG tab) usually has no official Homebrew formula -
# build from source: https://github.com/EliasOenal/multimon-ng
brew install create-dmg       # optional, nicer .dmg; falls back to hdiutil
```

## Build

```bash
cd rtlsdr_suite
chmod +x installer/macos/build_macos.sh
./installer/macos/build_macos.sh
```

Produces `dist/RTL-SDR-Suite.app` and `dist/RTL-SDR-Suite-1.0.0-macOS.dmg`.

## Known likely trouble spots

1. **`PackageNotFoundError` for pyModeS on first launch.** pyModeS reads its
   own version via `importlib.metadata` at import time; PyInstaller doesn't
   bundle that metadata by default. This exact bug was hit and fixed on the
   Linux build with `--copy-metadata pyModeS`, which the script already
   includes - but if it still happens, that's the first thing to check.
2. **Gatekeeper: "app is damaged and can't be opened."** Without a paid
   Apple Developer signing certificate, only ad-hoc codesigning is possible
   (which the script does). If macOS still refuses to open it after moving
   to `/Applications`, run:
   ```bash
   xattr -cr "/Applications/RTL-SDR Suite.app"
   ```
   or right-click the app -> Open (instead of double-click) the first time.
3. **Audio output (sounddevice/PortAudio):** should bundle automatically via
   PyInstaller's sounddevice hook the same way it did on Windows/Linux, but
   this hasn't been verified on macOS specifically - if the Receiver tab's
   audio doesn't work in the built app while `python main.py` works fine
   from source, this is the first place to look.
4. **RTL-SDR USB driver:** macOS needs no special driver like Windows'
   WinUSB (libusb talks to the dongle directly), but if `rtl_test` (from
   `brew install librtlsdr`) doesn't see the dongle, unplug/replug it and
   check `system_profiler SPUSBDataType` for the RTL2832U device.

If you hit any of these (or something else), you can paste the exact error
back and it can be fixed properly - this script just hasn't had a real
build/run cycle against actual macOS + hardware yet, unlike the Windows and
Linux installers which were both built, installed, launched, and
uninstalled end-to-end on real machines before being called done.
