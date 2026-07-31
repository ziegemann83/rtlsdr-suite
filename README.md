# RTL-SDR Suite

Eine kleine Desktop-Anwendung (Python + PySide6) für RTL-SDR-USB-Dongles mit drei
Werkzeugen in einem Fenster:

1. **Spektrum / Wasserfall** – Live-Frequenzspektrum und scrollendes Wasserfalldiagramm.
2. **Empfänger** – Allgemeiner Empfang mit WFM (UKW-Radio), NFM, AM, USB und LSB,
   Lautstärke- und Squelch-Regler, Live-Audioausgabe und Aufnahme als WAV-Datei.
3. **ADS-B Flugzeug-Tracker** – Empfängt 1090-MHz-ADS-B-Signale, dekodiert ICAO,
   Rufzeichen, Höhe, Geschwindigkeit, Kurs, Steigrate und Position und zeigt alle
   aktiven Flugzeuge in einer Tabelle sowie einem einfachen Lat/Lon-Plot an.

Da an einem USB-Dongle immer nur ein Programm gleichzeitig Daten abgreifen kann,
teilen sich die drei Tabs das Gerät: Es kann immer nur ein Tab gleichzeitig aktiv
sein (die App verhindert das automatisch und zeigt einen Hinweis, falls man das
versucht).

## Fertige Programme (ohne Python-Installation)

Unter [Releases](../../releases) gibt es fertig gebaute, eigenständige
Programme für Windows (`RTLSDRSuite-windows.exe`) und macOS
(`RTLSDRSuite-macos`) – kein lokales Python nötig. Es wird trotzdem weiterhin
der RTL-SDR-Treiber (librtlsdr) benötigt, siehe unten, und unter macOS muss
die Datei beim ersten Start ggf. über Rechtsklick → "Öffnen" freigegeben
werden (Gatekeeper, da die Datei nicht signiert ist).

Diese Binaries werden automatisch von GitHub Actions gebaut, sobald ein
Versions-Tag (`vX.Y.Z`) gepusht wird – siehe
`.github/workflows/release.yml`.

## Voraussetzungen

* Python 3.10 oder neuer (nur für den Start aus dem Quellcode nötig)
* Ein RTL-SDR-USB-Dongle (RTL2832U-Chipsatz) mit installierten Treibern
  (unter Windows z. B. über Zadig den WinUSB-Treiber installieren, siehe
  https://www.rtl-sdr.com/rtl-sdr-quick-start-guide/)
* Für den ADS-B-Tab zusätzlich die `rtl-sdr`-Kommandozeilenwerkzeuge
  (liefern u. a. `rtl_adsb`, `rtl_test`, `rtl_fm`):
  - Linux: `sudo apt install rtl-sdr` (Debian/Ubuntu) oder das Äquivalent
    Ihrer Distribution
  - macOS: `brew install librtlsdr`
  - Windows: die vorgebauten Binaries von osmocom/rtl-sdr herunterladen und
    den Ordner zum `PATH` hinzufügen

## Installation

```bash
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows (PowerShell):
venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## Start

```bash
python main.py
```

Beim Start sollte der Dongle bereits eingesteckt sein. Über "Refresh" in der
Kopfzeile lässt sich die Geräteliste neu einlesen, falls mehrere Dongles
angeschlossen sind.

## Bedienung

### Spektrum / Waterfall
Mittenfrequenz, Samplerate, FFT-Größe und Gain einstellen, dann "Start"
klicken. Das obere Diagramm zeigt das aktuelle Spektrum, das untere den
zeitlichen Verlauf als Wasserfall.

### Empfänger
Frequenz und Modus (WFM für UKW-Radio, NFM für Betriebsfunk/Amateurfunk-FM,
AM, USB/LSB für Kurzwelle) wählen, "Start" klicken. Lautstärke und Squelch
lassen sich live regeln. Mit "Record" wird die demodulierte Audiospur
gleichzeitig als WAV-Datei mitgeschnitten.

### ADS-B Tracker
"Start ADS-B receiver" startet im Hintergrund `rtl_adsb` (muss auf dem PATH
liegen, siehe oben) und dekodiert die empfangenen Rohnachrichten mit der
Bibliothek [pyModeS](https://github.com/junzis/pyModeS). Für eine stabile
Positionsermittlung sollte die Antenne freie Sicht zum Himmel haben; auf
1090 MHz sendende Flugzeuge werden typischerweise aus 50–400 km Entfernung
empfangen, je nach Antenne und Standort.

## Projektstruktur

```
rtlsdr_suite/
  main_window.py     Hauptfenster, Tab-Verwaltung, Geräte-Sharing (DeviceHub)
  spectrum_tab.py     Spektrum-/Wasserfall-Tab
  receiver_tab.py     Empfänger-Tab (Demodulation, Audio, Aufnahme)
  adsb_tab.py         ADS-B-Tab (rtl_adsb-Subprozess + Tabelle/Karte)
  sdr_device.py       Hintergrund-Thread, der den RTL-SDR-Dongle über pyrtlsdr ausliest
  dsp.py              Spektrum-Schätzung und Demodulatoren (FM/AM/SSB)
  audio_out.py        Audioausgabe über sounddevice
  adsb_decoder.py      Buchführung über erkannte Flugzeuge auf Basis von pyModeS
main.py               Programmstart
requirements.txt       Python-Abhängigkeiten
```

## Bekannte Einschränkungen

* Es kann jeweils nur ein Tab gleichzeitig senden/empfangen, da nur ein
  Programm auf den USB-Dongle zugreifen kann.
* Die SSB-Demodulation nutzt die einfache Phasing-Methode ohne scharfe
  Seitenband-Filterung; für den Amateurfunk-Alltag ausreichend, aber nicht so
  sauber wie ein dedizierter SSB-Empfänger.
* Der ADS-B-Tab benötigt das externe `rtl_adsb`-Tool; die Rohdemodulation der
  IQ-Daten wird bewusst nicht in Python neu implementiert, da die mitgelieferte
  C-Implementierung deutlich schneller und robuster ist.
