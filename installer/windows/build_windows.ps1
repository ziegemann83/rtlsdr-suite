# Build a standalone RTL-SDR Suite installer for Windows.
#
# This is the exact process used to build, install, launch, and cleanly
# uninstall RTL-SDR-Suite-Setup.exe during development - verified working
# on real Windows with a real RTL-SDR dongle attached.
#
# Usage (from the rtlsdr_suite/ folder, with venv/ already set up per the
# main README's Installation section):
#   .\installer\windows\build_windows.ps1
#
# Requires:
#   - venv\ already created and `pip install -r requirements.txt` run
#   - rtl-sdr-bin-new\ present (librtlsdr.dll, rtl_adsb.exe, rtl_433.exe,
#     rtl_fm.exe, multimon-ng.exe, ... - see main README for where to get
#     each of these)
#   - Inno Setup 6 (installer will offer to download+install it silently if
#     ISCC.exe isn't found)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\.."  # repo root (rtlsdr_suite\)

Write-Host "== Installing PyInstaller into the venv =="
.\venv\Scripts\python.exe -m pip install pyinstaller -q

Write-Host "== Building with PyInstaller =="
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --name "RTL-SDR-Suite" main.py

if (-not (Test-Path "dist\RTL-SDR-Suite\RTL-SDR-Suite.exe")) {
    throw "Expected PyInstaller output not found at dist\RTL-SDR-Suite\RTL-SDR-Suite.exe"
}

Write-Host "== Locating Inno Setup compiler (ISCC.exe) =="
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    Write-Host "Inno Setup not found - downloading and installing silently..."
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/jrsoftware/issrc/releases/latest" -Headers @{ "User-Agent" = "build-script" }
    $asset = $rel.assets | Where-Object { $_.name -match '^innosetup-6\.\d+\.\d+\.exe$' } | Select-Object -First 1
    if (-not $asset) { throw "Could not find an Inno Setup 6.x installer asset on the latest GitHub release." }
    $installerPath = "$env:TEMP\innosetup.exe"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installerPath -UseBasicParsing
    Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
    if (-not (Test-Path $iscc)) { throw "Inno Setup install did not produce ISCC.exe at the expected path." }
}

Write-Host "== Compiling the installer =="
& $iscc "installer\windows\rtlsdr_suite.iss"

$setupExe = "dist_installer\RTL-SDR-Suite-Setup.exe"
if (Test-Path $setupExe) {
    Write-Host ""
    Write-Host "== Done: $setupExe =="
} else {
    throw "ISCC ran but the expected output $setupExe was not produced."
}
