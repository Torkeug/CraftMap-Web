"""
Repeatable maintenance script: import the sibling spacecraft-memory-research
repo's event_log_db (SQLite, `wreck_events` table) into resources.db's own
wreck_events table. Thin CLI wrapper over backend/wreck_import.py, which
backend/api.py also calls directly for periodic auto-import while live
tracking is active (see Api.start_wreck_tracking) - this script exists for
a manual/offline import, same role tools/backfill_galaxy_resources.py plays
for the galaxy-wide dump.

Migrated 2026-08-04 off an earlier wreck_events.jsonl - see the sibling
repo's RESEARCH_LOG.md for why.

Usage:
    python tools/import_wreck_events.py
    python tools/import_wreck_events.py --events-db path/to/event_log.db
    python tools/import_wreck_events.py --dry-run   # report what would be
                                                        added, no writes
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend.db import init_db  # noqa: E402
from backend.wreck_import import DEFAULT_EVENTS_DB_PATH, load_rows, import_events_from_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events-db",
        default=str(DEFAULT_EVENTS_DB_PATH),
        help="event_log.db to import"
        " (default: ../spacecraft-memory-research/event_log.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many events were parsed without writing anything",
    )
    args = parser.parse_args()

    events_db_path = Path(args.events_db)
    if not events_db_path.exists():
        print(f"No event log found at {events_db_path}", file=sys.stderr)
        raise SystemExit(1)

    if args.dry_run:
        rows = load_rows(events_db_path)
        print(f"Parsed {len(rows)} events from {events_db_path} (dry run, nothing written).")
        return

    init_db()
    parsed, inserted = import_events_from_file(events_db_path)
    print(f"Imported {inserted} new wreck events ({parsed - inserted} already present) from {events_db_path}.")


if __name__ == "__main__":
    main()
