# RTL-SDR Suite

[![Tests](https://github.com/ziegemann83/rtlsdr-suite/actions/workflows/tests.yml/badge.svg)](https://github.com/ziegemann83/rtlsdr-suite/actions/workflows/tests.yml)
[![Build and release binaries](https://github.com/ziegemann83/rtlsdr-suite/actions/workflows/release.yml/badge.svg)](https://github.com/ziegemann83/rtlsdr-suite/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Eine kleine Desktop-Anwendung (Python + PySide6) für RTL-SDR-USB-Dongles mit sieben
Werkzeugen in einem Fenster:

1. **Spektrum / Wasserfall** – Live-Frequenzspektrum und scrollendes Wasserfalldiagramm,
   mit Presets für gängige Bänder (UKW, Flugfunk, ADS-B, 433 MHz ISM, POCSAG,
   868/915 MHz LoRa/Meshtastic), einstellbarer Farbskala (min/max dB) fürs Wasserfall,
   IQ-Rohaufzeichnung und Datei-Wiedergabe sowie Klick-ins-Spektrum, um den Empfänger
   direkt auf diese Frequenz abzustimmen.
2. **Empfänger** – Allgemeiner Empfang mit WFM (UKW-Radio), NFM, AM, USB und LSB,
   Lautstärke- und Squelch-Regler, Live-Audioausgabe, manuelle WAV-Aufnahme,
   automatische squelch-getriggerte Aufnahme (jede Übertragung wird als eigene
   Datei gespeichert), Ton-/Desktop-Alarm bei Signalerkennung, eine
   Mehrfrequenz-Scan-Liste, die automatisch weiterschaltet, bis ein Signal
   über der Squelch-Schwelle gefunden wird, sowie ein Speicher für benannte
   Frequenz-/Modus-Presets.
3. **ADS-B Flugzeug-Tracker** – Empfängt 1090-MHz-ADS-B-Signale, dekodiert ICAO,
   Rufzeichen, Höhe, Geschwindigkeit, Kurs, Steigrate und Position, zeigt alle
   aktiven Flugzeuge in einer Tabelle und einem einfachen Lat/Lon-Plot, kann
   Sichtungen fortlaufend als CSV loggen und eine interaktive Karte
   (Leaflet/OpenStreetMap) im Browser öffnen.
4. **433/868 MHz ISM-Scanner** – Empfängt und dekodiert kurzreichweitige
   ISM-Band-Geräte (Wetterstationen, Reifendrucksensoren, Funksteckdosen,
   Klingeln u. v. m.) über `rtl_433` und zeigt alle erkannten Geräte in einer
   Tabelle.
5. **POCSAG Pager** – Dekodiert POCSAG-Funkrufnachrichten (512/1200/2400 Baud)
   über eine `rtl_fm | multimon-ng`-Pipeline.
6. **NOAA-Wettersatellit (APT)** – Dekodiert live ein APT-Bild von den
   NOAA-15/18/19-Wettersatelliten auf 137 MHz und baut es Zeile für Zeile
   als Graustufenbild auf, das sich als PNG speichern lässt.
7. **Bandscanner** – Fährt einen Frequenzbereich mit einstellbarer Schrittweite
   ab, misst die Signalstärke pro Schritt und protokolliert jeden Treffer über
   einer Schwelle (Zeit, Frequenz, Pegel), exportierbar als CSV.

Da an einem USB-Dongle immer nur ein Programm gleichzeitig Daten abgreifen kann,
teilen sich alle sieben Tabs das Gerät: Es kann immer nur ein Tab gleichzeitig aktiv
sein (die App verhindert das automatisch und zeigt einen Hinweis, falls man das
versucht). Zuletzt genutzte Frequenz, Modus, Samplerate, Gain, Lautstärke, Squelch
und das ausgewählte Gerät werden automatisch gespeichert und beim nächsten Start
wieder geladen.

![Screenshot](assets/screenshot.png)

## Fertige Programme (ohne Python-Installation)

Unter [Releases](../../releases) gibt es fertig gebaute, eigenständige
Programme für Windows (`RTLSDRSuite-windows.exe`), macOS
(`RTLSDRSuite-macos`) und Linux (`RTLSDRSuite-linux`) – kein lokales Python
nötig. Es wird trotzdem weiterhin der RTL-SDR-Treiber (librtlsdr) benötigt,
siehe unten. Unter macOS muss die Datei beim ersten Start ggf. über
Rechtsklick → "Öffnen" freigegeben werden (Gatekeeper, da die Datei nicht
signiert ist). Unter Linux muss die Datei vor dem ersten Start ausführbar
gemacht werden: `chmod +x RTLSDRSuite-linux`.

Diese Binaries werden automatisch von GitHub Actions gebaut, sobald ein
Versions-Tag (`vX.Y.Z`) gepusht wird – siehe `.github/workflows/release.yml`.
Bei jedem Push auf `main` läuft außerdem automatisch die Testsuite
(`.github/workflows/tests.yml`). Diese CI-Binaries bündeln nur die
Python-Abhängigkeiten selbst; externe Kommandozeilenwerkzeuge wie `rtl_adsb`,
`rtl_433`, `rtl_fm` und `multimon-ng` müssen weiterhin separat installiert
werden (siehe "Voraussetzungen").

Alternativ gibt es unter [`installer/`](installer/) einen zweiten,
umfangreicheren Packaging-Weg mit plattformspezifischen Build-Skripten
(PyInstaller + Inno Setup für ein richtiges Windows-Installer-Paket
inklusive Startmenü-Eintrag, ein `.deb`- und `.tar.gz`-Build für Linux, sowie
ein Entwurf für macOS). Dieser Weg wurde für Windows und Linux gegen echte
RTL-SDR-Hardware getestet; das macOS-Skript ist bisher ungetestet. Details
dazu stehen in [`installer/README.md`](installer/README.md).

## Voraussetzungen

* Python 3.10 oder neuer (nur für den Start aus dem Quellcode nötig)
* Ein RTL-SDR-USB-Dongle (RTL2832U-Chipsatz) mit installierten Treibern
  (unter Windows z. B. über Zadig den WinUSB-Treiber installieren, siehe
  https://www.rtl-sdr.com/rtl-sdr-quick-start-guide/, und die `librtlsdr.dll`
  aus den unten genannten Binaries auf den `PATH`)
* Für den ADS-B-Tab und den POCSAG-Tab zusätzlich die `rtl-sdr`-Kommandozeilenwerkzeuge
  (liefern u. a. `rtl_adsb`, `rtl_test`, `rtl_fm`):
  - Linux: `sudo apt install rtl-sdr` (Debian/Ubuntu) oder das Äquivalent
    Ihrer Distribution
  - macOS: `brew install librtlsdr`
  - Windows: aktuelle Binaries von https://github.com/librtlsdr/librtlsdr/releases
    (die `rtl-sdr-blog`-Variante ist teils veraltet und liefert eine `librtlsdr.dll`,
    der neuere Funktionen wie `rtlsdr_set_dithering` fehlen) herunterladen und
    den Ordner zum `PATH` hinzufügen
* Für den ISM-Scanner-Tab zusätzlich `rtl_433`:
  https://github.com/merbanan/rtl_433/releases (Windows: die statisch
  gelinkte `..._64bit_static.exe` als `rtl_433.exe` verwenden, dann sind
  keine weiteren DLLs nötig)
* Für den POCSAG-Tab zusätzlich `multimon-ng`:
  https://github.com/EliasOenal/multimon-ng/releases (Windows-Build ist
  statisch gelinkt, keine weiteren DLLs nötig)

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
angeschlossen sind. Das zuletzt genutzte Gerät wird automatisch wieder
ausgewählt.

## Bedienung

### Spektrum / Waterfall
Preset wählen (oder Mittenfrequenz, Samplerate, FFT-Größe und Gain manuell
einstellen), dann "Start" klicken. Das obere Diagramm zeigt das aktuelle
Spektrum, das untere den zeitlichen Verlauf als Wasserfall. Die
868/915-MHz-LoRa/Meshtastic-Presets zeigen nur die Aktivität im Band (ob
gerade gesendet wird), da ein einfacher RTL-SDR-Dongle LoRas
Chirp-Spread-Spectrum-Pakete nicht dekodieren kann. Die Farbskala des
Wasserfalls (min/max dB) lässt sich über zwei Spinboxen anpassen. Ein Klick
ins Spektrum-Diagramm stimmt den Empfänger-Tab direkt auf die angeklickte
Frequenz ab und wechselt automatisch dorthin.

**IQ-Rohaufzeichnung/-Wiedergabe:** "Record IQ..." zeichnet die rohen
IQ-Samples des laufenden "Start"-Streams als `.cf32`-Datei (interleaved
float32 I/Q, also numpy `complex64`) plus einer `.json`-Metadatendatei
(Mittenfrequenz, Samplerate) auf – nützlich, um ein interessantes Signal
später offline (z. B. mit Universal Radio Hacker) zu analysieren oder um
einen Decoder ohne angeschlossene Hardware zu testen. "Play back file..."
liest eine solche `.cf32`-Datei zurück und speist sie wie einen Live-Stream
in Spektrum/Wasserfall ein (übernimmt Frequenz/Samplerate automatisch aus
der Metadatendatei, falls vorhanden); währenddessen ist "Start" (echte
Hardware) gesperrt und umgekehrt.

### Empfänger
Frequenz und Modus (WFM für UKW-Radio, NFM für Betriebsfunk/Amateurfunk-FM,
AM, USB/LSB für Kurzwelle) wählen, "Start" klicken. Lautstärke und Squelch
lassen sich live regeln. Mit "Record" wird die demodulierte Audiospur
gleichzeitig als WAV-Datei mitgeschnitten. Mit "Auto-record on squelch"
wird stattdessen automatisch bei jedem Öffnen des Squelch eine neue,
zeitgestempelte WAV-Datei im gewählten Ordner angelegt und beim Schließen
wieder geschlossen – praktisch für unbeaufsichtigten Betrieb. Über die
Scan-Liste (kommagetrennte MHz-Werte + Verweildauer in Sekunden) schaltet
der Empfänger automatisch durch mehrere Frequenzen, bis eines ein Signal
über der Squelch-Schwelle findet, und bleibt dort geparkt, solange das
Signal anliegt. "Alert on squelch open" spielt bei jedem Öffnen des Squelch
einen Systemton ab und zeigt (falls verfügbar) eine Desktop-Benachrichtigung
mit Frequenz und Pegel – rate-limitiert auf max. eine Benachrichtigung alle
2 Sekunden, damit ein flackerndes Grenzsignal nicht zuspammt. Über "+
Speichern" lässt sich die aktuelle Frequenz/Modus-Kombination als benannter
Preset ablegen; Presets werden per Doppelklick in der Liste geladen und über
"- Entfernen" wieder gelöscht.

Im WFM-Modus wird zusätzlich automatisch das RDS-Signal (Radio Data System,
57-kHz-Hilfsträger im UKW-Signal) mitdekodiert: Sendername und ggf. laufender
RadioText erscheinen unter der Statuszeile, sobald der Empfänger die
Bit-Synchronisation gefunden hat (kann je nach Signalstärke ein paar Sekunden
dauern). Die RDS-Dekodierung wurde mit einem synthetischen Testsignal
verifiziert (siehe `tests/test_rds.py`), aber noch nicht mit einer echten
Live-Übertragung – auf schwachen oder gestörten Sendern kann die
Bit-Synchronisation länger dauern oder ganz ausbleiben.

### ADS-B Tracker
"Start ADS-B receiver" startet im Hintergrund `rtl_adsb` (muss auf dem PATH
liegen, siehe oben) und dekodiert die empfangenen Rohnachrichten mit der
Bibliothek [pyModeS](https://github.com/junzis/pyModeS). Für eine stabile
Positionsermittlung sollte die Antenne freie Sicht zum Himmel haben; auf
1090 MHz sendende Flugzeuge werden typischerweise aus 50–400 km Entfernung
empfangen, je nach Antenne und Standort.

"CSV-Log starten" schreibt jede neue Positions-/Statusmeldung fortlaufend in
eine CSV-Datei (Zeitstempel, ICAO, Rufzeichen, Höhe, Geschwindigkeit, Kurs,
Steigrate, Position) zur späteren Auswertung. "Karte im Browser öffnen"
erzeugt eine temporäre HTML-Seite mit einer interaktiven Leaflet/OpenStreetMap-
Karte und allen aktuell bekannten Flugzeugpositionen (benötigt eine
Internetverbindung zum Laden der Kartenkacheln).

### 433/868 MHz ISM-Scanner
Frequenz-Preset wählen (433,92 MHz deckt die meisten europäischen
ISM-Geräte ab) und "Start ISM scanner" klicken. Startet im Hintergrund
`rtl_433 -F json` (muss auf dem PATH liegen) und zeigt jedes erkannte Gerät
mit Modell, ID, Temperatur/Luftfeuchte (falls vorhanden), Batteriestatus
und Nachrichtenzähler in der Tabelle. Geräte, die 10 Minuten lang nicht
mehr gesendet haben, werden automatisch aus der Liste entfernt.

### POCSAG Pager
Frequenz-Preset wählen und "Start POCSAG decoder" klicken. Startet im
Hintergrund `rtl_fm` (FM-Demodulation) gepiped in `multimon-ng`
(POCSAG512/1200/2400-Dekodierung); beide Tools müssen auf dem PATH liegen.
Dekodierte Nachrichten (Adresse, Funktionscode, Alpha-/Nummerntext)
erscheinen fortlaufend in der Tabelle.

### NOAA-Wettersatellit (APT)
Satellit wählen (NOAA-15/18/19, je nach aktuellem Überflug) und "Start APT
decode" klicken. Ein Überflug dauert ca. 10–15 Minuten; die Antenne braucht
möglichst freie Sicht zum Himmel (eine einfache V-Dipol- oder QFH-Antenne
reicht für ordentliche Ergebnisse). Das Bild baut sich Zeile für Zeile live
auf und lässt sich jederzeit über "Save PNG..." sichern. Gezeigt wird das
klassische *rohe*, 2080 Pixel breite APT-Bild (Kanal A + Kanal B +
Telemetrie nebeneinander), keine kalibrierte/zugeschnittene Ausgabe wie bei
spezialisierten Tools (z. B. WXtoImg oder `noaa-apt`).

### Bandscanner
Start-/Endfrequenz, Schrittweite, Verweildauer pro Schritt und
Erkennungsschwelle einstellen, dann "Start scan" klicken. Der Scanner fährt
den Bereich durch, misst pro Schritt die Signalstärke und protokolliert
jeden Treffer über der Schwelle in der Tabelle (Zeit, Frequenz, Pegel).
"Loop continuously" fährt den Bereich endlos durch; "Export CSV..."
schreibt das Protokoll in eine Datei. Praktisch, um vor dem gezielten
Abhören erstmal herauszufinden, welche Frequenzen in der eigenen Umgebung
überhaupt aktiv sind.

## Tests

```bash
pip install pytest
pytest tests/
```

Die Testsuite deckt die Signalverarbeitung (Spektrum, FM/AM/SSB-Demodulation,
Dezimierung) und die ADS-B-Nachrichtenverarbeitung mit bekannten
Beispielnachrichten ab. Sie läuft automatisch bei jedem Push über GitHub
Actions.

## Projektstruktur

```
rtlsdr_suite/
  main_window.py      Hauptfenster, Tab-Verwaltung, Geräte-Sharing (DeviceHub)
  spectrum_tab.py      Spektrum-/Wasserfall-Tab mit Presets, Farbskala, IQ-Aufzeichnung/-Wiedergabe, Klick-Tuning
  receiver_tab.py      Empfänger-Tab (Demodulation, Audio, Aufnahme, Auto-Record, Scan-Liste, Alarm, Presets)
  adsb_tab.py          ADS-B-Tab (rtl_adsb-Subprozess, Tabelle/Plot, CSV-Log, Karte)
  ism_tab.py           433/868 MHz ISM-Scanner-Tab (rtl_433-Subprozess + Tabelle)
  pocsag_tab.py        POCSAG-Pager-Tab (rtl_fm | multimon-ng-Pipeline + Tabelle)
  apt_tab.py           NOAA-Wettersatelliten-Tab (Live-Bildaufbau)
  apt_decoder.py       APT-Dekoder (FM-Diskriminator, Subcarrier-Envelope, Sync, PNG-Export)
  bandscanner_tab.py   Bandscanner/Logger-Tab (Frequenz-Sweep + CSV-Export)
  sdr_device.py        Hintergrund-Thread, der den RTL-SDR-Dongle über pyrtlsdr ausliest
  dsp.py               Spektrum-Schätzung und Demodulatoren (FM/AM/SSB)
  audio_out.py         Audioausgabe über sounddevice
  adsb_decoder.py      Buchführung über erkannte Flugzeuge auf Basis von pyModeS
  proc_utils.py        Hilfsfunktionen für Subprozesse (u. a. kein Konsolenfenster unter Windows)
  settings.py          Persistente Einstellungen und Presets (QSettings)
tests/                 Automatisierte Tests (pytest)
assets/                App-Icon und Screenshot
installer/             Plattformspezifische Build-Skripte (Windows/Linux/macOS), alternativ zu den CI-Binaries
main.py                Programmstart
requirements.txt       Python-Abhängigkeiten
```

## Bekannte Einschränkungen

* Es kann jeweils nur ein Tab gleichzeitig senden/empfangen, da nur ein
  Programm auf den USB-Dongle zugreifen kann.
* Die SSB-Demodulation filtert das unerwünschte Seitenband blockweise per FFT
  heraus; für den Amateurfunk-Alltag ausreichend, klingt an Blockgrenzen aber
  nicht ganz so sauber wie ein dedizierter SSB-Empfänger mit kontinuierlichem
  Filter.
* Der ADS-B-Tab benötigt das externe `rtl_adsb`-Tool, der ISM-Scanner das
  externe `rtl_433`-Tool und der POCSAG-Tab die externen Tools `rtl_fm` und
  `multimon-ng`; die jeweilige Rohdemodulation/-dekodierung wird bewusst
  nicht in Python neu implementiert, da die mitgelieferten
  C-Implementierungen deutlich schneller und robuster sind (insbesondere
  BCH-Fehlerkorrektur und Bit-Sync bei POCSAG sind fehleranfällig, wenn man
  sie selbst nachbaut).
* Die 868/915-MHz-Presets im Spektrum-Tab zeigen nur Aktivität im Band,
  keine echte LoRa/Meshtastic-Paketdekodierung – dafür bräuchte man
  spezialisierte LoRa-Hardware statt eines generischen RTL-SDR-Dongles.
* `librtlsdr.dll` unter Windows: `rtlsdr_set_freq_correction(dev, 0)` schlägt
  fehl, wenn der Korrekturwert bereits 0 ist (Standardzustand). `sdr_device.py`
  setzt die PPM-Korrektur deshalb nur, wenn sie sich vom aktuellen Wert
  unterscheidet.
* Der APT-Dekoder liefert das klassische *rohe* APT-Bild (2080 px breit,
  Kanal A/B/Telemetrie nebeneinander) ohne Kalibrierung, Kanal-Trennung oder
  Bildverbesserung; für publikationsreife Wettersatellitenbilder eignen sich
  spezialisierte Tools wie `noaa-apt` oder WXtoImg besser.
* Der Bandscanner misst die Signalstärke pro Frequenzschritt nur während der
  eingestellten Verweildauer (Standard 150 ms); sehr kurze/sporadische
  Übertragungen können zwischen zwei Scan-Durchläufen hindurchrutschen.
* Die Windows-/macOS-Binaries aus den GitHub-Actions-Releases sind nicht
  codesigniert (das würde ein kostenpflichtiges Zertifikat erfordern);
  SmartScreen bzw. Gatekeeper zeigen daher beim ersten Start eine Warnung.
* Der alternative Installer-Weg unter `installer/` wurde nur für Windows und
  Linux gegen echte Hardware getestet; das macOS-Build-Skript dort ist ein
  ungetesteter Entwurf.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
