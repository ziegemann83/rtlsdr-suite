#!/usr/bin/env bash
# Build a standalone Linux binary, a .deb package, and a portable tar.gz for
# RTL-SDR Suite. This is the exact process that was built, installed
# (dpkg -i), launched, and cleanly uninstalled (dpkg -r) during development -
# it is verified working, just too large (~135 MB per artifact) to hand over
# as a chat attachment, so run this to produce your own copies.
#
# Usage:
#   cd rtlsdr_suite/
#   chmod +x installer/linux/build_linux.sh
#   ./installer/linux/build_linux.sh
#
# Output (in dist_installer/):
#   rtl-sdr-suite_1.0.0_amd64.deb      - for Debian/Ubuntu (and derivatives)
#   rtl-sdr-suite-linux-x64.tar.gz     - portable, any x86_64 Linux distro

set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root (rtlsdr_suite/)

VERSION="1.0.0"
BIN_NAME="rtl-sdr-suite"
OUT_DIR="dist_installer"

echo "== Setting up a build venv =="
python3 -m venv .build_venv_linux
source .build_venv_linux/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

echo "== Building with PyInstaller =="
rm -rf build dist
# --copy-metadata pyModeS: pyModeS reads its own version via importlib.metadata
# at import time; PyInstaller doesn't bundle dist-info metadata by default,
# which makes the frozen app crash on startup with PackageNotFoundError.
# Found and fixed exactly this way while building this project.
pyinstaller --noconfirm --onedir --windowed --name "$BIN_NAME" \
    --copy-metadata pyModeS \
    main.py

if [ ! -f "dist/${BIN_NAME}/${BIN_NAME}" ]; then
    echo "ERROR: expected build output not found" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

echo "== Building portable tar.gz =="
tar -czf "${OUT_DIR}/rtl-sdr-suite-linux-x64.tar.gz" -C dist "$BIN_NAME"
echo "  -> ${OUT_DIR}/rtl-sdr-suite-linux-x64.tar.gz"
echo "     Run with: tar -xzf rtl-sdr-suite-linux-x64.tar.gz && ./rtl-sdr-suite/rtl-sdr-suite"

echo "== Building .deb package =="
PKGROOT="/tmp/rtl-sdr-suite-deb-build/rtl-sdr-suite_${VERSION}_amd64"
rm -rf "$PKGROOT"
mkdir -p "$PKGROOT/DEBIAN" "$PKGROOT/opt/rtl-sdr-suite" "$PKGROOT/usr/bin" \
         "$PKGROOT/usr/share/applications" "$PKGROOT/usr/share/doc/rtl-sdr-suite"

cp -r "dist/${BIN_NAME}"/* "$PKGROOT/opt/rtl-sdr-suite/"
cp README.md "$PKGROOT/usr/share/doc/rtl-sdr-suite/README.md"

cat > "$PKGROOT/usr/bin/rtl-sdr-suite" <<'WRAPPER'
#!/bin/sh
exec /opt/rtl-sdr-suite/rtl-sdr-suite "$@"
WRAPPER
chmod +x "$PKGROOT/usr/bin/rtl-sdr-suite"

cat > "$PKGROOT/usr/share/applications/rtl-sdr-suite.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=RTL-SDR Suite
Comment=Spectrum, receiver, ADS-B, ISM, POCSAG, APT and band scanner for RTL-SDR dongles
Exec=/opt/rtl-sdr-suite/rtl-sdr-suite
Icon=utilities-terminal
Terminal=false
Categories=HamRadio;Utility;
DESKTOP

DEB_SIZE=$(du -sk "$PKGROOT" | cut -f1)
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: rtl-sdr-suite
Version: ${VERSION}
Section: hamradio
Priority: optional
Architecture: amd64
Installed-Size: ${DEB_SIZE}
Depends: libxcb-cursor0, libportaudio2, libusb-1.0-0
Recommends: rtl-sdr
Maintainer: RTL-SDR Suite <noreply@example.com>
Description: Desktop GUI for RTL-SDR USB dongles
 Spectrum/waterfall, general receiver (WFM/NFM/AM/USB/LSB), ADS-B aircraft
 tracker, 433/868 MHz ISM scanner, POCSAG pager decoder, NOAA APT weather
 satellite decoder, and a band scanner/logger, all in one window.
 .
 The ADS-B tab needs rtl_adsb (package rtl-sdr), the ISM scanner needs
 rtl_433, and the POCSAG tab needs rtl_fm (package rtl-sdr) plus
 multimon-ng. Install rtl-sdr via apt; rtl_433 and multimon-ng may need to
 be built from source or installed from their project releases depending
 on your distribution - see /usr/share/doc/rtl-sdr-suite/README.md.
EOF

dpkg-deb -Zgzip --build --root-owner-group "$PKGROOT" "${OUT_DIR}/rtl-sdr-suite_${VERSION}_amd64.deb"
echo "  -> ${OUT_DIR}/rtl-sdr-suite_${VERSION}_amd64.deb"
echo "     Install with: sudo apt install ./rtl-sdr-suite_${VERSION}_amd64.deb"
echo "     (apt, not dpkg -i, so it pulls in Depends: automatically)"

deactivate
echo ""
echo "== Done. Both artifacts are in ${OUT_DIR}/ =="
