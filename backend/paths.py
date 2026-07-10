"""Shared data-file locations.

resources.db/config.json live alongside this app's own installation
directory - this used to be a tkinter app's sibling folder while CraftMap-
Web was a parallel, side-by-side rewrite, but that tkinter app has since
been retired and this project took over as the one and only CraftMap.
"""

import os
import sys

# Mirrors the retired tkinter app's own _APP_DIR frozen-vs-script split: a
# frozen PyInstaller --onefile exe extracts to a throwaway temp directory
# at runtime, so __file__ there points nowhere near this project's actual
# install location - sys.executable is the only reliable anchor once
# frozen. When running from source, __file__ IS the real anchor (and
# sys.executable would be the venv's python.exe, which tells us nothing
# about where this project lives).
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(_APP_DIR, "resources.db")
CONFIG_PATH = os.path.join(_APP_DIR, "config.json")
