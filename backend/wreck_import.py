"""Shared logic for importing the sibling spacecraft-memory-research repo's
event_log_db (SQLite, `wreck_events` table) into resources.db's own
wreck_events table - used both by tools/import_wreck_events.py (manual CLI
run) and backend/api.py (periodic auto-import while live tracking is
active, see Api.get_live_wreck_snapshot).

Migrated 2026-08-04 off an earlier JSONL event log (wreck_events.jsonl) -
see the sibling repo's RESEARCH_LOG.md for why (the actual use case is a
time-windowed JOIN against inventory deltas, which needs both event
streams to be SQL-queryable). The cursor also changed shape accordingly:
an id (AUTOINCREMENT in the SOURCE db) instead of a byte offset into a
flat file - db.get/set_wreck_event_import_cursor persist the last-imported
id (keyed by source db path) across calls and app restarts, so a
steady-state call with nothing new to import is just one cheap indexed
`WHERE id > ?` query, regardless of how large the source table has grown.
"""
import sqlite3
from pathlib import Path

from . import db

# Local-machine-only default - the sibling repo's own poller output, never
# copied into this repo (personal/per-Quadrant data, same treatment
# tools/backfill_galaxy_resources.py's own DEFAULT_DUMP_PATH gets).
DEFAULT_EVENTS_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "spacecraft-memory-research" / "event_log.db"
)

_SELECT_COLUMNS = "system_name, planet_name, resource_id, event_type, wreck_size, wreck_tier, parent_id, x, y, z, observed_at"


def _normalize_rows(raw_rows):
    # planet_name is nullable in the source (live_tracker.py's own
    # planet-name resolution can transiently fail, e.g. mid-travel/
    # loading) but NOT NULL in resources.db's wreck_events (db.init_db) -
    # `INSERT OR IGNORE` against a NOT NULL column silently swallows the
    # constraint violation instead of raising, so a real event just
    # vanishes with no error anywhere if this isn't handled. Confirmed
    # live (pre-migration, same underlying gap): one whole system's worth
    # of sightings (82 rows) went missing this way before this fallback
    # existed. A sentinel keeps the row (same pattern as frontend/js/
    # wrecks.js's own "(unknown sector)" fallback) rather than losing it.
    return [
        (
            system_name,
            planet_name or "(unknown planet)",
            resource_id,
            event_type,
            wreck_size,
            wreck_tier,
            parent_id,
            x, y, z,
            observed_at,
        )
        for (system_name, planet_name, resource_id, event_type, wreck_size, wreck_tier, parent_id, x, y, z, observed_at)
        in raw_rows
    ]


def load_rows(events_db_path):
    """Full-table read - used by tools/import_wreck_events.py's --dry-run
    (reports the TOTAL event count, not just what's new since the cursor)
    and as the one-time initial read the very first time a given
    events_db_path is imported. Returns [] if the db/table doesn't exist
    yet (poller never run)."""
    path = Path(events_db_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        c = conn.execute(f"SELECT {_SELECT_COLUMNS} FROM wreck_events ORDER BY id")
        return _normalize_rows(c.fetchall())
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet (fresh db, poller never run a node cycle)
    finally:
        conn.close()


def load_new_rows(events_db_path, last_id):
    """Reads only rows with id > last_id. Returns (rows, new_last_id). If
    the source db doesn't exist yet, or the table is empty/missing,
    returns ([], last_id) unchanged - same "nothing new yet" treatment
    load_rows gives a not-yet-existing poller output."""
    path = Path(events_db_path)
    if not path.exists():
        return [], last_id
    conn = sqlite3.connect(str(path))
    try:
        c = conn.execute(
            f"SELECT id, {_SELECT_COLUMNS} FROM wreck_events WHERE id > ? ORDER BY id",
            (last_id,),
        )
        fetched = c.fetchall()
    except sqlite3.OperationalError:
        return [], last_id
    finally:
        conn.close()
    if not fetched:
        return [], last_id
    new_last_id = fetched[-1][0]
    rows = _normalize_rows(row[1:] for row in fetched)  # drop the id column
    return rows, new_last_id


def import_events_from_file(events_db_path=None):
    """Returns (parsed_count, inserted_count) for whatever's NEW since the
    last call (not the source table's total row count - see load_rows for
    that). init_db() is the caller's responsibility (main.py already
    calls it at startup; tools/import_wreck_events.py calls it itself for
    standalone runs). Name kept as import_events_from_file (not renamed to
    ..._from_db) - existing callers (backend/api.py, tests) already treat
    this as "import whatever's new from the configured source," and the
    source happening to be a SQLite db now rather than a JSONL file is an
    internal detail, not a signature change worth propagating."""
    path = Path(events_db_path) if events_db_path else DEFAULT_EVENTS_DB_PATH
    last_id = db.get_wreck_event_import_cursor(str(path))
    rows, new_last_id = load_new_rows(path, last_id)
    if new_last_id != last_id:
        db.set_wreck_event_import_cursor(str(path), new_last_id)
    if not rows:
        return 0, 0
    inserted = db.import_wreck_events(rows)
    return len(rows), inserted
