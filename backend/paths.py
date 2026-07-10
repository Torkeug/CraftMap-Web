"""Shared data-file locations.

CraftMap-Web is a parallel project to the existing tkinter CraftMap app
(d:\\Documents\\Spacecraft\\craftmap) and deliberately shares its data
files rather than maintaining a separate copy - one source of truth for
recipes/deposits while both versions exist side by side. Don't run both
apps at the same time (SQLite file-level locking would contend on
concurrent writes).
"""

import os
import sys

# Mirrors craftmap/overlay.py's _APP_DIR frozen-vs-script split: a frozen
# PyInstaller --onefile exe extracts to a throwaway temp directory at
# runtime, so __file__ there points nowhere near this project's actual
# install location - sys.executable is the only reliable anchor once
# frozen. When running from source, __file__ IS the real anchor (and
# sys.executable would be the venv's python.exe, which tells us nothing
# about where this project lives).
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    _UP_LEVELS = ("..",)  # exe is expected to sit directly in craftmap-web/
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))  # .../craftmap-web/backend
    _UP_LEVELS = ("..", "..")

# The existing tkinter app's folder - craftmap-web's own directory's
# sibling. Not derived from this project's own install location beyond
# that, since the data intentionally lives in the other project's folder.
_CRAFTMAP_DIR = os.path.normpath(os.path.join(_APP_DIR, *_UP_LEVELS, "craftmap"))

DB_PATH = os.path.join(_CRAFTMAP_DIR, "resources.db")
CONFIG_PATH = os.path.join(_CRAFTMAP_DIR, "config.json")
