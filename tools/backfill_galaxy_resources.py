"""
Repeatable maintenance script: import a galaxy-wide resource-type snapshot
into resources.db's galaxy_resources table, from the sibling
spacecraft-memory-research repo's dump_galaxy_resources.py output (reads a
live SpaceCraft.exe process's exploration history, not extracted from
data.cdb). Unlike everything in game_data_extract/ (universal,
data.cdb-derived reference data meant to be committed), this dump is
personal and per-Quadrant - it reflects one player's own playthrough and
goes stale as they explore further - so it is never copied into this repo,
the same treatment resources.db itself already gets (see .gitignore).

Only INSERT OR IGNOREs against galaxy_resources' own
UNIQUE(system_name, planet, resource) constraint, so rerunning this after
further exploration (a fresh dump covers more explored planets over time)
just adds new rows - does not touch any other table.

Only imports resourceCounts/resourceDensities - the exact, live per-resource
counts (see the dump's own docstring), not the coarser resGroup-level
resourceNodeCountEstimates. Planets with no resourceCounts (not yet
generated client-side) are silently skipped, not imported as empty/
placeholder rows.

Usage:
    python tools/backfill_galaxy_resources.py
    python tools/backfill_galaxy_resources.py --dump-path path/to/galaxy_resources.json
    python tools/backfill_galaxy_resources.py --dry-run   # report what would be
                                                             # added, no writes
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend import db  # noqa: E402
from backend.db import init_db  # noqa: E402

# Local-machine-only default - the sibling repo's own dump output, never
# copied into this repo (see this module's own docstring).
DEFAULT_DUMP_PATH = (
    REPO_ROOT.parent / "spacecraft-memory-research" / "galaxy_resources.json"
)


def load_rows(dump_path):
    planets = json.loads(dump_path.read_text(encoding="utf-8"))
    rows = []
    for p in planets:
        system_name = p.get("system_name")
        planet = p.get("planet_name")
        counts = p.get("resourceCounts") or {}
        if not system_name or not planet or not counts:
            continue
        sector = p.get("sector_name")
        densities = p.get("resourceDensities") or {}
        for resource, count in counts.items():
            rows.append(
                (system_name, planet, sector, resource, count, densities.get(resource))
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-path",
        default=str(DEFAULT_DUMP_PATH),
        help="galaxy_resources.json dump to import"
        " (default: ../spacecraft-memory-research/galaxy_resources.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many rows would be added without writing anything",
    )
    args = parser.parse_args()

    dump_path = Path(args.dump_path)
    if not dump_path.exists():
        print(f"No dump found at {dump_path}", file=sys.stderr)
        raise SystemExit(1)

    init_db()
    rows = load_rows(dump_path)

    if args.dry_run:
        existing = db.get_galaxy_resource_keys()
        new_rows = [r for r in rows if (r[0], r[1], r[3]) not in existing]
        print(
            f"Would add {len(new_rows)} of {len(rows)} parsed resource rows"
            f" ({len(rows) - len(new_rows)} already present) from {dump_path}."
        )
        return

    inserted = db.import_galaxy_resources(rows)
    print(
        f"Imported {inserted} new resource rows"
        f" ({len(rows) - inserted} already present) from {dump_path}."
    )


if __name__ == "__main__":
    main()
