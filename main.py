#!/usr/bin/env python3
"""Entry point for the RTL-SDR Suite desktop application.

Run with:
    python main.py
"""

import sys

from PySide6.QtWidgets import QApplication

from rtlsdr_suite.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RTL-SDR Suite")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
