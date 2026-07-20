"""Shared logic for importing the sibling spacecraft-memory-research repo's
wreck_tracker.py JSONL event log into resources.db's wreck_events table -
used both by tools/import_wreck_events.py (manual CLI run) and
backend/api.py (periodic auto-import while live tracking is active, see
Api.get_live_wreck_snapshot).

Incremental (cursor-based), not a whole-file reread every call - the live
HUD window (frontend/js/wreck-tracker-panel.js) polls
get_live_wreck_snapshot, and thus this import, at 5Hz, so "just reread the
whole file every time, it's small" (this module's earlier assumption)
stops being safe for anything but a short session. db.
get_wreck_event_import_offset/set_wreck_event_import_offset persist a byte
offset into the file (keyed by path) across calls and app restarts, so a
steady-state call with nothing new to import is just a stat() + a zero-byte
read, regardless of how large the file has grown.
"""
import json
from pathlib import Path

from . import db

# Local-machine-only default - the sibling repo's own poller output, never
# copied into this repo (personal/per-Quadrant data, same treatment
# tools/backfill_galaxy_resources.py's own DEFAULT_DUMP_PATH gets).
DEFAULT_EVENTS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "spacecraft-memory-research" / "wreck_events.jsonl"
)


def _parse_lines(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        # planet is NOT NULL in wreck_events (db.init_db) - wreck_tracker.py's
        # own planet-name resolution can transiently fail (returns null in
        # the JSONL, e.g. mid-travel/loading) and DOES still log the event
        # when that happens, but `INSERT OR IGNORE` against a NOT NULL
        # column silently swallows the constraint violation instead of
        # raising - a real event just vanishes with no error anywhere.
        # Confirmed live: one whole system's worth of sightings (82 rows)
        # went missing this way before this fallback existed. A sentinel
        # keeps the row (same pattern as frontend/js/wrecks.js's own
        # "(unknown sector)" fallback) rather than losing it outright.
        rows.append((
            ev.get("system_name"),
            ev.get("planet_name") or "(unknown planet)",
            ev.get("resource_id"),
            ev.get("event_type"),
            ev.get("x"),
            ev.get("y"),
            ev.get("z"),
            ev.get("observed_at"),
        ))
    return rows


def load_rows(events_path):
    """Full-file parse - used by tools/import_wreck_events.py's --dry-run
    (reports the file's TOTAL event count, not just what's new since the
    cursor) and as the one-time initial read the very first time a given
    events_path is imported. Malformed lines are skipped rather than
    aborting the whole import - the poller writes one line per event and
    flushes every cycle (see its own module docstring), so a torn last
    line from a mid-write process kill is the realistic failure mode, not
    systemic corruption."""
    if not events_path.exists():
        return []
    return _parse_lines(events_path.read_text(encoding="utf-8"))


def load_new_rows(events_path, start_offset):
    """Reads only newly-appended lines since start_offset (a byte offset
    into events_path). Returns (rows, new_offset). Only advances the
    offset up to the last COMPLETE line (one ending in a newline) - the
    poller is a separate, unsynchronized process, so a read could land
    mid-write; leaving a torn trailing partial line unconsumed for the
    next call is simpler and safer than trying to lock across two
    independent processes, and only ever delays a single event by one
    poll cycle at worst. If the file is smaller than start_offset (e.g.
    deleted and recreated, or a fresh run wiped it), the offset resets to
    0 rather than silently reading nothing forever."""
    if not events_path.exists():
        return [], start_offset
    size = events_path.stat().st_size
    if size < start_offset:
        start_offset = 0
    if size == start_offset:
        return [], start_offset
    with events_path.open("rb") as f:
        f.seek(start_offset)
        data = f.read()
    last_newline = data.rfind(b"\n")
    if last_newline == -1:
        return [], start_offset  # only a torn partial line available so far
    complete = data[: last_newline + 1]
    new_offset = start_offset + len(complete)
    rows = _parse_lines(complete.decode("utf-8", errors="replace"))
    return rows, new_offset


def import_events_from_file(events_path=None):
    """Returns (parsed_count, inserted_count) for whatever's NEW since the
    last call (not the file's total event count - see load_rows for
    that). init_db() is the caller's responsibility (main.py already
    calls it at startup; tools/import_wreck_events.py calls it itself for
    standalone runs)."""
    path = Path(events_path) if events_path else DEFAULT_EVENTS_PATH
    offset = db.get_wreck_event_import_offset(str(path))
    rows, new_offset = load_new_rows(path, offset)
    if new_offset != offset:
        db.set_wreck_event_import_offset(str(path), new_offset)
    if not rows:
        return 0, 0
    inserted = db.import_wreck_events(rows)
    return len(rows), inserted
