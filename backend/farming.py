"""Static Xenic Farm crop-variant reference data (frontend/js/farming.js's
"Farming" tab) - hand-transcribed from shipbuilder/tools/game_logic_notes.md
Findings 13/14 into game_data_extract/farming.json, not derived from a
runtime game-data dump the way shipwreck_loot.json is (see that finding's
own header for the data.cdb/decompile source) - so unlike
backend/shipwreck_loot.py there's no companion extract_*.py script; update
farming.json by hand if game_logic_notes.md gets a corrected finding.

Same path-resolution/bundling rationale as backend/shipwreck_loot.py
(read-only reference data baked into the build, not this install's own
persisted state) and same "return the whole dataset, filter/compute
client-side" call shape - the full crop list is a couple KB, and eligibility
against a chosen Temperature/Light dial pair is cheap enough to compute in
frontend/js/farming.js directly rather than adding a second API call.
"""

import json
import os
import sys

_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FARMING_PATH = os.path.join(_BASE_DIR, "game_data_extract", "farming.json")

_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(_FARMING_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def get_crops():
    return _load()["crops"]


def get_growth_death_mechanism():
    """The tick-based gate-checking/death-timer/Invasive-spread mechanic
    (game_logic_notes.md Finding 16) - applies identically to every variant
    of both crops (same Xenic Farm building), so it's a single shared note
    rather than data repeated on each variant - see farming.json's own
    _meta.growth_death_mechanism for the full text."""
    return _load()["_meta"]["growth_death_mechanism"]
