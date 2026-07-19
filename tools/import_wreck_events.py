"""
Repeatable maintenance script: import the sibling spacecraft-memory-research
repo's wreck_tracker.py JSONL event log into resources.db's wreck_events
table. Thin CLI wrapper over backend/wreck_import.py, which backend/api.py
also calls directly for periodic auto-import while live tracking is active
(see Api.start_wreck_tracking) - this script exists for a manual/offline
import, same role tools/backfill_galaxy_resources.py plays for the
galaxy-wide dump.

Usage:
    python tools/import_wreck_events.py
    python tools/import_wreck_events.py --events-path path/to/wreck_events.jsonl
    python tools/import_wreck_events.py --dry-run   # report what would be
                                                        added, no writes
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend.db import init_db  # noqa: E402
from backend.wreck_import import DEFAULT_EVENTS_PATH, load_rows, import_events_from_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events-path",
        default=str(DEFAULT_EVENTS_PATH),
        help="wreck_events.jsonl to import"
        " (default: ../spacecraft-memory-research/wreck_events.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many events were parsed without writing anything",
    )
    args = parser.parse_args()

    events_path = Path(args.events_path)
    if not events_path.exists():
        print(f"No event log found at {events_path}", file=sys.stderr)
        raise SystemExit(1)

    if args.dry_run:
        rows = load_rows(events_path)
        print(f"Parsed {len(rows)} events from {events_path} (dry run, nothing written).")
        return

    init_db()
    parsed, inserted = import_events_from_file(events_path)
    print(f"Imported {inserted} new wreck events ({parsed - inserted} already present) from {events_path}.")


if __name__ == "__main__":
    main()
