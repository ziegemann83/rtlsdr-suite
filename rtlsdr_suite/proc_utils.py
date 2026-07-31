"""Small helper shared by every tab that shells out to an external tool
(rtl_adsb, rtl_433, rtl_fm, multimon-ng, ...).

On Windows, a console-subsystem .exe launched via subprocess.Popen from a
GUI app (our PyInstaller --windowed build has no console of its own) pops
up a visible console window for the child process. Since these tools run
continuously until the user clicks "Stop", that window just sits there for
as long as the tab is running - looking like the app is stuck, even though
everything is working normally underneath. CREATE_NO_WINDOW suppresses it.
"""

from __future__ import annotations

import subprocess
import sys

NO_WINDOW_KWARGS: dict = {}
if sys.platform == "win32":
    NO_WINDOW_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW
