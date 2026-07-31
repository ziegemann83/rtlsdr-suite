"""ADS-B message bookkeeping on top of pyModeS (v3 API, PipeDecoder).

Raw Mode-S / ADS-B demodulation (finding the 1090 MHz preambles and slicing
bits out of the raw IQ stream) is left to the well tested `rtl_adsb` tool
that ships with the rtl-sdr driver package - reimplementing that bit-level
demodulator from scratch in Python would be slower and far more fragile
than the C reference implementation. This module takes the raw hex frames
`rtl_adsb` prints, feeds them through pyModeS's stateful PipeDecoder (which
handles CRC checking and even/odd CPR position pairing), and keeps a small
"aircraft database" (position, callsign, altitude, speed, ...) keyed by
ICAO address for the GUI table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pyModeS as pms


@dataclass
class Aircraft:
    icao: str
    callsign: str = ""
    altitude: float | None = None
    speed: float | None = None
    track: float | None = None
    vertical_rate: float | None = None
    lat: float | None = None
    lon: float | None = None
    last_seen: float = field(default_factory=time.time)
    messages: int = 0


class AdsbTracker:
    """Feed raw hex Mode-S messages in; get a live {icao: Aircraft} table out."""

    def __init__(self, aircraft_timeout_s: float = 120.0):
        self.aircraft: dict[str, Aircraft] = {}
        self.aircraft_timeout_s = aircraft_timeout_s
        self.total_messages = 0
        self.valid_messages = 0
        self._decoder = pms.PipeDecoder(pair_window=10.0, local_ref_window=30.0)

    def feed_hex(self, msg: str) -> str | None:
        """Process one raw hex ADS-B/Mode-S message. Returns the ICAO if updated."""
        msg = msg.strip().lower()
        if not msg or len(msg) not in (14, 28):
            return None
        self.total_messages += 1

        try:
            result = self._decoder.decode(msg, timestamp=time.time())
        except Exception:
            return None

        if not result or not result.get("crc_valid"):
            return None
        if result.get("df") not in (17, 18):
            return None

        icao = result.get("icao")
        if not icao:
            return None
        self.valid_messages += 1

        ac = self.aircraft.get(icao)
        if ac is None:
            ac = Aircraft(icao=icao)
            self.aircraft[icao] = ac
        ac.last_seen = time.time()
        ac.messages += 1

        callsign = result.get("callsign")
        if callsign:
            ac.callsign = callsign.replace("_", "").strip()

        if result.get("altitude") is not None:
            ac.altitude = result["altitude"]
        if result.get("latitude") is not None and result.get("longitude") is not None:
            ac.lat = result["latitude"]
            ac.lon = result["longitude"]
        if result.get("groundspeed") is not None:
            ac.speed = result["groundspeed"]
        if result.get("track") is not None:
            ac.track = result["track"]
        if result.get("vertical_rate") is not None:
            ac.vertical_rate = result["vertical_rate"]

        return icao

    def prune(self):
        """Drop aircraft we haven't heard from in a while."""
        now = time.time()
        stale = [
            icao for icao, ac in self.aircraft.items()
            if now - ac.last_seen > self.aircraft_timeout_s
        ]
        for icao in stale:
            del self.aircraft[icao]
