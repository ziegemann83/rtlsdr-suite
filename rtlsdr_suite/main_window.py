"""Main application window: ties the Spectrum, Receiver and ADS-B tabs together."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QStatusBar,
)

from .sdr_device import SdrWorker
from .spectrum_tab import SpectrumTab
from .receiver_tab import ReceiverTab
from .adsb_tab import AdsbTab


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
        self.tabs.addTab(self.spectrum_tab, "Spectrum / Waterfall")
        self.tabs.addTab(self.receiver_tab, "Receiver (FM/AM/SSB)")
        self.tabs.addTab(self.adsb_tab, "ADS-B Tracker")
        root.addWidget(self.tabs)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            "Only one tab can use the dongle at a time. "
            "ADS-B tracking requires the 'rtl_adsb' command line tool to be installed."
        )

    def _refresh_devices(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        names = SdrWorker.list_devices()
        if not names:
            names = ["[0] (device list unavailable - device 0 will be used)"]
        self.device_combo.addItems(names)
        self.device_combo.blockSignals(False)
        self.hub.device_index = 0

    def _on_device_changed(self, index: int):
        self.hub.device_index = max(0, index)

    def closeEvent(self, event):
        self.spectrum_tab.shutdown()
        self.receiver_tab.shutdown()
        self.adsb_tab.shutdown()
        super().closeEvent(event)
