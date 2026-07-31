"""Persistent application settings (last used frequency, mode, gain, ...)
and saved frequency presets, backed by QSettings (platform-native: registry
on Windows, plist on macOS, ini file on Linux)."""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings

ORG_NAME = "rtlsdr-suite"
APP_NAME = "RTLSDRSuite"


def get_settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


class ReceiverPresets:
    """Simple named list of (frequency_hz, mode) presets, persisted as JSON
    inside QSettings so it survives app restarts."""

    KEY = "receiver/presets"

    def __init__(self):
        self._settings = get_settings()

    def load(self) -> list[dict]:
        raw = self._settings.value(self.KEY, "[]")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, list):
                return data
        except (ValueError, TypeError):
            pass
        return []

    def save(self, presets: list[dict]):
        self._settings.setValue(self.KEY, json.dumps(presets))

    def add(self, name: str, freq_hz: float, mode: str):
        presets = self.load()
        presets.append({"name": name, "freq_hz": freq_hz, "mode": mode})
        self.save(presets)

    def remove(self, index: int):
        presets = self.load()
        if 0 <= index < len(presets):
            presets.pop(index)
            self.save(presets)
