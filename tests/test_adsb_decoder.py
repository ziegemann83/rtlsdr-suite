"""Unit tests for the ADS-B message tracker (rtlsdr_suite.adsb_decoder)."""

from rtlsdr_suite.adsb_decoder import AdsbTracker


# Well-known public sample Mode-S/ADS-B messages used throughout pyModeS' own
# test suite and documentation.
CALLSIGN_MSG = "8D4840D6202CC371C32CE0576098"
VELOCITY_MSG = "8D485020994409940838175B284F"
POSITION_MSG_EVEN = "8D40621D58C382D690C8AC2863A7"


def test_feed_hex_ignores_garbage():
    tracker = AdsbTracker()
    assert tracker.feed_hex("") is None  # empty input isn't counted at all
    assert tracker.feed_hex("not-hex-at-all") is None  # non-hex, counted as an attempt
    assert tracker.feed_hex("ABCD") is None  # too short, counted as an attempt
    assert tracker.total_messages == 2
    assert tracker.valid_messages == 0


def test_feed_hex_strips_rtl_adsb_wrapping():
    tracker = AdsbTracker()
    icao = tracker.feed_hex(f"*{CALLSIGN_MSG.lower()};".lstrip("*").rstrip(";"))
    assert icao == "4840D6"


def test_callsign_message_updates_aircraft():
    tracker = AdsbTracker()
    icao = tracker.feed_hex(CALLSIGN_MSG)
    assert icao == "4840D6"
    assert icao in tracker.aircraft
    ac = tracker.aircraft[icao]
    assert ac.callsign == "KLM1023"
    assert ac.messages == 1


def test_velocity_message_updates_speed_track_vrate():
    tracker = AdsbTracker()
    icao = tracker.feed_hex(VELOCITY_MSG)
    ac = tracker.aircraft[icao]
    assert ac.speed is not None
    assert ac.track is not None
    assert ac.vertical_rate is not None


def test_position_message_updates_altitude():
    tracker = AdsbTracker()
    icao = tracker.feed_hex(POSITION_MSG_EVEN)
    ac = tracker.aircraft[icao]
    assert ac.altitude == 38000


def test_prune_removes_stale_aircraft():
    tracker = AdsbTracker(aircraft_timeout_s=0.0)
    icao = tracker.feed_hex(CALLSIGN_MSG)
    assert icao in tracker.aircraft
    tracker.prune()
    assert icao not in tracker.aircraft


def test_valid_message_counter_only_counts_df17_18():
    tracker = AdsbTracker()
    tracker.feed_hex(CALLSIGN_MSG)
    tracker.feed_hex(VELOCITY_MSG)
    assert tracker.total_messages == 2
    assert tracker.valid_messages == 2
