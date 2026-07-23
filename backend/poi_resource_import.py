"""Shared logic for importing the sibling spacecraft-memory-research repo's
wreck_tracker.py per-POI resource-node-count snapshot into resources.db's
poi_resource_nodes table - used by backend/api.py (piggybacked onto the
existing Api.get_live_wreck_snapshot poll, same as wreck_import.py's own
event-log import).

Whole-file read every call, NOT cursor-based like wreck_import.py: that
module's incremental-byte-offset design exists specifically for an
ever-growing append-only JSONL log, where "reread the whole file every
call" stops scaling at a high poll rate. poi_resource_counts.json is the
opposite shape - a small, fully OVERWRITTEN-every-cycle snapshot of
whichever planet the player is on right now (same pattern as
current_planet_wrecks.json/wreck_tracking.read_live_snapshot) - there is no
"already-consumed prefix" to track, the whole file is always the current
truth, so a cursor would just be dead weight here.
"""
import json
from pathlib import Path

from . import db

# Local-machine-only default - the sibling repo's own poller output, never
# copied into this repo (personal/per-Quadrant data, same treatment
# wreck_import.DEFAULT_EVENTS_PATH/tools/backfill_galaxy_resources.py's own
# DEFAULT_DUMP_PATH get).
DEFAULT_POI_COUNTS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "spacecraft-memory-research" / "poi_resource_counts.json"
)


def read_poi_resource_snapshot(path):
    """Whole-file read of the poller's overwritten POI-resource-count
    snapshot - None if missing/corrupt/mid-write, same treatment
    wreck_tracking.read_live_snapshot gives current_planet_wrecks.json
    (the poller writes both atomically via a temp-file rename, so a torn
    read shouldn't normally happen, but is handled the same as "not
    tracking yet" rather than raised either way)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def import_poi_resource_snapshot(path=None):
    """Reads the current snapshot and INSERT OR REPLACEs it into
    poi_resource_nodes. Returns (system_name, planet, row_count), or None
    if there's no snapshot yet, it's corrupt/mid-write, or the poller
    wasn't on a planet (system_name/planet_name null - e.g. mid-travel)
    when it last wrote. Whole-file reread every call is fine - the file is
    small (one planet's worth of poi_index x resource combinations) and
    this is only called at the same poll rate get_live_wreck_snapshot's own
    wreck_events import already tolerates."""
    path = Path(path) if path else DEFAULT_POI_COUNTS_PATH
    snapshot = read_poi_resource_snapshot(path)
    if not snapshot or not snapshot.get("system_name") or not snapshot.get("planet_name"):
        return None
    observed_at = snapshot.get("observed_at")
    rows = [
        (
            snapshot["system_name"],
            snapshot["planet_name"],
            entry["poi_index"],
            entry["resource_name"],
            entry["node_count"],
            observed_at,
        )
        for entry in snapshot.get("poi_resource_counts", [])
    ]
    if not rows:
        return None
    db.import_poi_resource_nodes(rows)
    return snapshot["system_name"], snapshot["planet_name"], len(rows)
