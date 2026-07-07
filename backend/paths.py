"""Shared data-file locations.

CraftMap-Web is a parallel project to the existing tkinter CraftMap app
(d:\\Documents\\Spacecraft\\craftmap) and deliberately shares its data
files rather than maintaining a separate copy - one source of truth for
recipes/deposits while both versions exist side by side. Don't run both
apps at the same time (SQLite file-level locking would contend on
concurrent writes).
"""

import os

# The existing tkinter app's folder - craftmap-web's own directory's
# sibling. Not derived from this project's own install location, since
# the data intentionally lives in the other project's folder.
_CRAFTMAP_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "craftmap")
)

DB_PATH = os.path.join(_CRAFTMAP_DIR, "resources.db")
CONFIG_PATH = os.path.join(_CRAFTMAP_DIR, "config.json")
