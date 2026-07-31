#!/usr/bin/env bash
# Build a standalone RTL-SDR Suite.app + .dmg on macOS.
#
# NOT TESTED ON REAL MACOS HARDWARE - this was written and validated for
# correctness against the Windows/Linux builds of this same project (which
# use the identical PyInstaller command modulo the OS-specific bits below),
# but nobody has actually run it on a Mac yet. Please report back if
# something doesn't work; the two likeliest trouble spots are noted below.
#
# Usage:
#   cd rtlsdr_suite/
#   ./installer/macos/build_macos.sh
#
# Requires: Xcode command line tools (for codesigning tools), Python 3.10+,
# and (optionally) `create-dmg` (brew install create-dmg) for a nicer .dmg;
# falls back to `hdiutil` (always present on macOS) if create-dmg is absent.

set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root (rtlsdr_suite/)

APP_NAME="RTL-SDR Suite"
BIN_NAME="RTL-SDR-Suite"
VERSION="1.0.0"

echo "== Setting up a build venv =="
python3 -m venv .build_venv_macos
source .build_venv_macos/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

echo "== Building with PyInstaller =="
# --copy-metadata pyModeS: pyModeS reads its own version via importlib.metadata
# at import time; PyInstaller doesn't bundle dist-info metadata by default,
# which makes the frozen app crash on startup with PackageNotFoundError.
# (Confirmed necessary on Linux; almost certainly needed here too since it's
# the same Python-level issue, not OS-specific - this is trouble spot #1 if
# the app crashes immediately on first launch.)
pyinstaller --noconfirm --windowed --name "$BIN_NAME" \
    --copy-metadata pyModeS \
    --osx-bundle-identifier "com.rtlsdrsuite.app" \
    main.py

APP_BUNDLE="dist/${BIN_NAME}.app"
if [ ! -d "$APP_BUNDLE" ]; then
    echo "ERROR: expected app bundle not found at $APP_BUNDLE" >&2
    exit 1
fi

echo "== Ad-hoc codesigning (so Gatekeeper doesn't immediately reject it) =="
# Trouble spot #2: without ANY signature, recent macOS refuses to even open
# the app ("is damaged and can't be opened"). Ad-hoc signing (no paid Apple
# Developer account needed) usually avoids that, but the user may still need
# to right-click -> Open the first time, or run:
#   xattr -cr "/Applications/RTL-SDR Suite.app"
# if Gatekeeper still complains after moving it to /Applications.
codesign --force --deep --sign - "$APP_BUNDLE" || \
    echo "WARNING: ad-hoc codesign failed or was skipped; app may need 'xattr -cr' after install."

echo "== Packaging external command-line tools =="
# rtl_adsb/rtl_fm/rtl_test etc: brew install librtlsdr
# rtl_433: brew install rtl_433 (or build from https://github.com/merbanan/rtl_433)
# multimon-ng: usually needs building from source on macOS (brew has no
#   official formula as of writing) - see https://github.com/EliasOenal/multimon-ng
# These are intentionally NOT bundled into the .app the way the Windows
# installer bundles prebuilt .exe binaries, since Homebrew is the natural
# distribution channel on macOS and static macOS binaries of these tools
# aren't reliably available. The README (copied into the .dmg below)
# documents the exact brew commands.
mkdir -p dist/dmg_root
cp -R "$APP_BUNDLE" "dist/dmg_root/${APP_NAME}.app"
cp README.md "dist/dmg_root/README.md"
ln -sf /Applications "dist/dmg_root/Applications"

echo "== Building .dmg =="
DMG_PATH="dist/${BIN_NAME}-${VERSION}-macOS.dmg"
rm -f "$DMG_PATH"
if command -v create-dmg >/dev/null 2>&1; then
    create-dmg \
        --volname "$APP_NAME" \
        --app-drop-link 450 150 \
        "$DMG_PATH" \
        "dist/dmg_root/${APP_NAME}.app" || \
        echo "create-dmg failed, falling back to hdiutil"
fi
if [ ! -f "$DMG_PATH" ]; then
    hdiutil create -volname "$APP_NAME" -srcfolder "dist/dmg_root" -ov -format UDZO "$DMG_PATH"
fi

deactivate
echo ""
echo "== Done =="
echo "App bundle: $APP_BUNDLE"
echo "Disk image: $DMG_PATH"
echo ""
echo "Before distributing, please actually launch the .app once (double-click,"
echo "or 'open dist/${BIN_NAME}.app') to confirm it starts - this script has"
echo "not been run on real macOS hardware, only reasoned about by analogy to"
echo "the already-tested Windows and Linux builds of this same project."
