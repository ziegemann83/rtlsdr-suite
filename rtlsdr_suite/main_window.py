"""Main application window: ties all the tabs together."""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QStatusBar,
)

from .sdr_device import SdrWorker
from .spectrum_tab import SpectrumTab
from .receiver_tab import ReceiverTab
from .adsb_tab import AdsbTab
from .ism_tab import IsmTab
from .pocsag_tab import PocsagTab
from .apt_tab import AptTab
from .bandscanner_tab import BandScannerTab
from .settings import get_settings


class DeviceHub:
    """Arbitrates access to the single physical RTL-SDR dongle between tabs.

    Only one tab can stream from the dongle at a time (it's one piece of USB
    hardware). Tabs call try_acquire()/release() around their start/stop
    actions instead of sharing a device handle directly.
    """

    def __init__(self):
        self.device_index = 0
        self._owner: str | None = None

    def try_acquire(self, owner: str) -> bool:
        if self._owner is not None and self._owner != owner:
            return False
        self._owner = owner
        return True

    def release(self, owner: str):
        if self._owner == owner:
            self._owner = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTL-SDR Suite")
        self.resize(1100, 750)
        self._set_app_icon()

        self.hub = DeviceHub()

        central = QWidget()
        root = QVBoxLayout(central)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("RTL-SDR device:"))
        self.device_combo = QComboBox()
        self._refresh_devices()
        device_row.addWidget(self.device_combo)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_devices)
        device_row.addWidget(refresh_btn)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        device_row.addStretch(1)
        root.addLayout(device_row)

        self.tabs = QTabWidget()
        self.spectrum_tab = SpectrumTab(self.hub)
        self.receiver_tab = ReceiverTab(self.hub)
        self.adsb_tab = AdsbTab(self.hub)
        self.ism_tab = IsmTab(self.hub)
        self.pocsag_tab = PocsagTab(self.hub)
        self.apt_tab = AptTab(self.hub)
        self.bandscanner_tab = BandScannerTab(self.hub)
        self.tabs.addTab(self.spectrum_tab, "Spectrum / Waterfall")
        self.tabs.addTab(self.receiver_tab, "Receiver (FM/AM/SSB)")
        self.tabs.addTab(self.adsb_tab, "ADS-B Tracker")
        self.tabs.addTab(self.ism_tab, "433/868 MHz ISM Scanner")
        self.tabs.addTab(self.pocsag_tab, "POCSAG Pager")
        self.tabs.addTab(self.apt_tab, "NOAA Weather Satellite")
        self.tabs.addTab(self.bandscanner_tab, "Band Scanner")
        root.addWidget(self.tabs)

        # Clicking on the spectrum plot tunes the receiver to that frequency
        # and jumps to the Receiver tab for convenience.
        self.spectrum_tab.tune_requested.connect(self._on_spectrum_tune_requested)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            "Only one tab can use the dongle at a time. "
            "ADS-B tracking requires 'rtl_adsb', the ISM scanner requires 'rtl_433', "
            "and the POCSAG tab requires 'rtl_fm' + 'multimon-ng' on your PATH."
        )

        self._load_device_setting()

    def _set_app_icon(self):
        # When frozen by PyInstaller (--onefile), bundled data lives under
        # sys._MEIPASS instead of next to this source file.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base_dir = meipass
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _on_spectrum_tune_requested(self, freq_mhz: float):
        self.receiver_tab.set_frequency_mhz(freq_mhz)
        self.tabs.setCurrentWidget(self.receiver_tab)

    def _refresh_devices(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        names = SdrWorker.list_devices()
        if not names:
            names = ["[0] (device list unavailable - device 0 will be used)"]
        self.device_combo.addItems(names)
        self.device_combo.blockSignals(False)

    def _load_device_setting(self):
        s = get_settings()
        saved_index = int(s.value("main/device_index", 0))
        if 0 <= saved_index < self.device_combo.count():
            self.device_combo.setCurrentIndex(saved_index)
        else:
            self.hub.device_index = 0

    def _on_device_changed(self, index: int):
        self.hub.device_index = max(0, index)
        get_settings().setValue("main/device_index", self.hub.device_index)

    def closeEvent(self, event):
        self.spectrum_tab.shutdown()
        self.receiver_tab.shutdown()
        self.adsb_tab.shutdown()
        self.ism_tab.shutdown()
        self.pocsag_tab.shutdown()
        self.apt_tab.shutdown()
        self.bandscanner_tab.shutdown()
        super().closeEvent(event)
