"""
Applies the renames tools/report_resource_name_mismatches.py identifies as
CONFIRMED (single-candidate matches, disambiguated via res_type - see that
script's own docstring for the full reasoning, including its fuzzy-match
fallback for real spelling variants like "Sulfuric Stone" vs "Sulphuric
Stone" - also only trusted once res_type narrows it to exactly one
candidate) directly to the deposits table, so get_deposits_for_ingredient's
exact-match LOGGED-pin lookup (see frontend/js/galaxy.js) can find them.
Only ever touches deposits.resource - never galaxy_resources (backfill-
only, see tools/backfill_galaxy_resources.py).

Also resolves grouped manual entries (e.g. "Coal/Vitriol", entered that way
because they're one physical drilling cluster - see this project's own
CLAUDE.md, depositGroupSizes) against galaxy_resources' own composite rows
(tools/backfill_galaxy_resources.py's "Coal Deposit / Vitriol Pool"-style
entries): splits the manual name on "/", resolves each token the same
confirmed way a single name would be, and renames to the matching composite
row's exact name IF one exists with precisely that member set - never
splits a grouped manual entry into separate rows (the group is real -
they're the same physical spot in-game).

Never touches: (blank)/Plant/Shipwreck rows (not naming mismatches, see
NON_MINERAL_TYPES), raw-material names (a rename would be wrong - the
manual entry already correctly names a crafting ingredient, not a node
type), or genuinely ambiguous names (multiple surviving candidates even
after the res_type filter, i.e. anything report_resource_name_mismatches.py
itself would only report as "maybe") - all left exactly as that script
reports them, for a human to resolve by hand.

Usage:
    python tools/fix_resource_name_mismatches.py            # dry run (default)
    python tools/fix_resource_name_mismatches.py --apply     # actually rename
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend import db  # noqa: E402
from backend.db import init_db  # noqa: E402
from tools.backfill_galaxy_resources import composite_resource_name  # noqa: E402
import difflib  # noqa: E402

from tools.report_resource_name_mismatches import (  # noqa: E402
    FUZZY_CUTOFF,
    NON_MINERAL_TYPES,
    candidate_names,
    load_node_item_types,
    resolve_by_type,
)


def resolve_name(name, types, galaxy_names, node_item_types):
    """The single-name resolution chain from
    report_resource_name_mismatches.py, steps 2 and 4 (prefix/substring
    candidates, then a fuzzy-match fallback for real spelling variants) -
    both gated on narrowing to exactly one res_type-confirmed candidate.
    Deliberately skips that script's step 3 (resource_sources raw-material
    lookup): a raw-material name is not a node-type mismatch to fix, it's
    a different namespace entirely - renaming it would be wrong."""
    candidates = candidate_names(name, galaxy_names)
    confirmed = resolve_by_type(candidates, types, node_item_types) if candidates else None
    if confirmed:
        return confirmed
    suggestions = difflib.get_close_matches(name, galaxy_names, n=3, cutoff=FUZZY_CUTOFF)
    return resolve_by_type(suggestions, types, node_item_types) if suggestions else None


def resolve_group(name, types, galaxy_names, node_item_types):
    """For a "Coal/Vitriol"-style manual name (optionally with a trailing
    "(N deposits)" note): resolves each slash-separated token the same
    confirmed way a standalone name would be, then checks whether
    galaxy_resources has a composite row for precisely that member set.
    Returns the composite row's exact name, or None if any token doesn't
    resolve to exactly one candidate or no such composite row exists."""
    label = name.split("(")[0].strip()
    if "/" not in label:
        return None
    tokens = [t.strip() for t in label.split("/") if t.strip()]
    if len(tokens) < 2:
        return None
    resolved = []
    for token in tokens:
        confirmed = resolve_name(token, types, galaxy_names, node_item_types)
        if not confirmed:
            return None
        resolved.append(confirmed)
    combo = composite_resource_name(resolved)
    return combo if combo in galaxy_names else None


def find_renames(rows_by_name, galaxy_names, node_item_types):
    """Returns {old_name: new_name} for every manual name confidently
    resolvable to an exact galaxy_resources name - single-candidate direct
    matches and whole-group composite matches alike."""
    renames = {}
    for name, entries in rows_by_name.items():
        if not name or name in galaxy_names:
            continue
        types = {r[1] for r in entries}
        if types & NON_MINERAL_TYPES.keys():
            continue

        confirmed = resolve_name(name, types, galaxy_names, node_item_types)
        if confirmed:
            renames[name] = confirmed
            continue

        group_match = resolve_group(name, types, galaxy_names, node_item_types)
        if group_match:
            renames[name] = group_match

    return renames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually perform the renames (default: dry run, report only)",
    )
    args = parser.parse_args()

    init_db()
    rows = db.fetch_all("")
    rows_by_name = defaultdict(list)
    for r in rows:
        rows_by_name[r[2]].append(r)

    galaxy_names = set(db.get_galaxy_resource_names())
    node_item_types = load_node_item_types()
    renames = find_renames(rows_by_name, galaxy_names, node_item_types)

    if not renames:
        print("No confidently-resolvable name mismatches found.")
        return

    total_rows = sum(len(rows_by_name[n]) for n in renames)
    verb = "Renaming" if args.apply else "Would rename"
    print(f"{verb} {total_rows} deposit rows across {len(renames)} resource names:\n")
    for old, new in sorted(renames.items(), key=lambda pair: pair[0].lower()):
        count = len(rows_by_name[old])
        note = f" [{count} rows]" if count > 1 else ""
        print(f"  {old!r:35}{note} -> {new!r}")

    if not args.apply:
        print("\nDry run - no changes made. Re-run with --apply to write these renames.")
        return

    print()
    for old, new in renames.items():
        updated = db.rename_deposit_resource(old, new)
        print(f"  Updated {updated} row(s): {old!r} -> {new!r}")


if __name__ == "__main__":
    main()
