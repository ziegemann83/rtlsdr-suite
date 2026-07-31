# Changelog

Alle nennenswerten Änderungen an RTL-SDR Suite, chronologisch (neueste zuerst).

## v1.3.0 – RDS-Decodierung

- Neu: RDS-Decoder (Radio Data System) für den Empfänger-Tab im
  WFM-Modus. Zeigt Sendername und laufenden RadioText an, sobald die
  Bit-Synchronisation auf dem 57-kHz-Hilfsträger gefunden wurde.
- Eigenimplementierung nach EN 50067/IEC 62106 (CRC10-Blocksynchronisation,
  differentielle Biphase-/Manchester-Dekodierung, Gruppen 0A/2A).
- Mit einem synthetischen Testsignal verifiziert (`tests/test_rds.py`),
  **aber noch nicht mit echtem UKW-Empfang getestet** – auf schwachen
  oder gestörten Sendern kann die Synchronisation langsamer oder gar
  nicht einrasten.
- Release-Notes werden ab jetzt automatisch aus dieser CHANGELOG.md
  gezogen (deutscher Text) statt aus einem festen englischen Textblock.

## v1.2.0 – Sieben-Tab-Merge

- Vier zusätzliche Tabs zusammengeführt (ursprünglich lokal entwickelt):
  433/868 MHz ISM-Scanner (rtl_433), POCSAG-Pager-Decoder
  (rtl_fm + multimon-ng), NOAA-Wettersatelliten-APT-Decoder
  (137 MHz, PNG-Export) und Bandscanner/Logger.
- Installer-Skripte für Windows (PyInstaller + Inno Setup), Linux
  (.deb + tar.gz) und einen vorbereiteten (ungetesteten) macOS-Build
  übernommen.
- Hardware-Bugfixes übernommen: `freq_correction` wird nur bei
  tatsächlicher Änderung gesetzt (wurde sonst von librtlsdr abgelehnt);
  `QPixmap.scaledToWidth` nutzt jetzt das gültige
  `Qt.SmoothTransformation`-Enum statt eines ungültigen Int-Werts.
- App-Icon fehlte bisher in den PyInstaller-Onefile-Builds – wird jetzt
  per `--add-data` mitverpackt und über `sys._MEIPASS` korrekt gefunden.

## v1.1.0 – Bedienkomfort, Persistenz und Tests

- Frequenz-Presets im Empfänger-Tab (speichern/laden/entfernen).
- Klick ins Spektrum-Diagramm stimmt den Empfänger direkt auf die
  angeklickte Frequenz ab.
- Einstellbare Wasserfall-Farbskala (Min/Max in dB).
- ADS-B: CSV-Logging und Kartenansicht (Leaflet/OpenStreetMap) im
  Browser.
- Frequenz, Modus, Gerät, Lautstärke und Squelch werden jetzt zwischen
  Programmstarts gespeichert.
- Bugfix: Die SSB-Demodulation (USB/LSB) filterte bisher gar kein
  Seitenband heraus – beide Modi klangen identisch. Jetzt echte
  FFT-basierte Seitenbandtrennung.
- Automatisierte Testsuite (23 Tests) plus eigener Test-CI-Workflow.
- MIT-Lizenz, App-Icon und Screenshot im README ergänzt.

## v1.0.0 – Erste Version

- Erste veröffentlichte Version: Spektrum-/Wasserfall-Anzeige,
  allgemeiner Empfänger (WFM/NFM/AM/USB/LSB) und ADS-B-Flugzeug-Tracker
  in einer Anwendung.
- Standalone-Binaries für Windows, macOS und Linux über GitHub Actions.
