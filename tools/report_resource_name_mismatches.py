"""
Diagnostic, read-only: compares the resource names used in your own
manually-logged deposits against the automated galaxy_resources data,
flagging manual names with no exact match.

This matters beyond tidiness: get_deposits_for_ingredient (the query behind
the Galaxy sub-tab's LOGGED pin, see frontend/js/galaxy.js) matches on
EXACT resource-name equality against galaxy_resources' own node-type
namespace. A manual entry logged under a name galaxy_resources doesn't
have will never show as LOGGED even if it's the very same planet.

Checks, in order, per unmatched name (row counts shown throughout, not
just distinct-name counts - a single "unmatched name" can silently be many
deposit rows, e.g. every blank-resource "Shipwreck" entry collapses to one
name otherwise):

1. res_type in NON_MINERAL_TYPES: galaxy_resources is built entirely from
   PlanetResourceManager's mineral/ore counts (see
   tools/backfill_galaxy_resources.py) - it categorically cannot cover
   these categories, confirmed against this project's own data for both:
   "Plant" (farming) and "Shipwreck" (loot crates, tracked via a
   deliberately-blank resource field + a landmark note instead - see the
   Wrecks tab for actual shipwreck loot odds). Not a naming problem at all.

2. Candidate galaxy names are gathered (name + " Deposit" if that exact
   string exists; any prefix/substring match either direction - a much
   stronger signal for a shortened/informal name than edit-distance
   similarity) and then disambiguated using game_data_extract/
   resource_nodes.json's own props.itemType: confirmed directly against
   this project's data that "Deposit"-suffixed names are ALWAYS
   PlanetResource_Deposit (auto-drilled) and everything else gatherable is
   PlanetResource_RegularNode - and that this exactly matches the meaning
   of this app's own res_type field ("Deposit" vs "Resources"). So
   "Aluminum" (res_type=Resources) can ONLY be "Aluminum Reduction"
   (RegularNode) - "Aluminum Deposit" (Deposit-type) was never actually a
   real candidate once res_type is taken into account, even though a
   naive prefix match alone can't tell the two apart. When exactly one
   candidate survives this filter, it's reported as CONFIRMED, not a
   guess.

3. resource_sources lookup - the manual name may be a genuine RAW MATERIAL
   name (e.g. "Pyrite" as a crafting ingredient), not a node-type name at
   all; galaxy_resources can never match those directly by design, so this
   reports which of its known node types (if any) actually have galaxy
   data instead of proposing a rename.

4. difflib fuzzy match, cutoff raised to 0.8 - plain edit-distance ratio
   turned out too weak a signal on its own for this vocabulary (lots of
   short, similar-sounding mineral names): at an earlier 0.5 cutoff,
   "Pyrite" matched "Azurite"/"Patronite"/"Tenorite" (ratios 0.55-0.67) -
   useless as a discriminator. 0.8 keeps real near-exact spelling variants
   (e.g. "Sulfuric Stone" vs "Sulphuric Stone", 0.897). Also run through
   the same res_type/itemType check as step 2 - if it narrows to exactly
   one, that's reported as confirmed too, not just "maybe".

Never writes anything.

Usage:
    python tools/report_resource_name_mismatches.py
"""
import difflib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend import db  # noqa: E402
from backend.db import init_db  # noqa: E402

FUZZY_CUTOFF = 0.8
DEPOSIT_ITEM_TYPE = "PlanetResource_Deposit"

# res_type values confirmed (via this project's own data) to represent
# categories galaxy_resources' purely mineral/ore live-count data can
# never cover, regardless of naming - not a mismatch to fix.
NON_MINERAL_TYPES = {
    "Plant": "farming resources",
    "Shipwreck": "loot crates (see the Wrecks tab for actual odds) - "
    "resource is deliberately left blank, the landmark is in notes instead",
}


def load_node_item_types():
    path = REPO_ROOT / "game_data_extract" / "resource_nodes.json"
    nodes = json.loads(path.read_text(encoding="utf-8"))
    return {n["name"]: n.get("props", {}).get("itemType") for n in nodes if n.get("name")}


def prefix_matches(name, galaxy_names):
    low = name.lower()
    return sorted(
        g for g in galaxy_names
        if g.lower().startswith(low) or low.startswith(g.lower())
    )


def candidate_names(name, galaxy_names):
    """Every plausible galaxy name for a manual name, before type-based
    disambiguation."""
    candidates = set(prefix_matches(name, galaxy_names))
    guess = f"{name} Deposit"
    if guess in galaxy_names:
        candidates.add(guess)
    return sorted(candidates)


def resolve_by_type(candidates, types, node_item_types):
    """Narrows candidates using whether res_type says this manual entry
    SHOULD be a PlanetResource_Deposit node or not - see this module's own
    docstring for why that's a reliable signal, not a guess. Returns the
    single confirmed name, or None if it doesn't narrow to exactly one."""
    wants_deposit = "Deposit" in types
    typed = [
        c for c in candidates
        if node_item_types.get(c) is not None
        and (node_item_types.get(c) == DEPOSIT_ITEM_TYPE) == wants_deposit
    ]
    return typed[0] if len(typed) == 1 else None


def main():
    init_db()
    # (id, res_type, resource, sector, system_name, planet, notes, logged_at)
    rows = db.fetch_all("")
    rows_by_name = defaultdict(list)
    for r in rows:
        rows_by_name[r[2]].append(r)

    galaxy_names = set(db.get_galaxy_resource_names())
    node_item_types = load_node_item_types()
    unmatched_names = sorted((n for n in rows_by_name if n not in galaxy_names), key=str.lower)

    if not unmatched_names:
        print("Every manually-logged resource name has an exact match in galaxy_resources.")
        return

    unmatched_row_count = sum(len(rows_by_name[n]) for n in unmatched_names)
    print(
        f"{unmatched_row_count} of {len(rows)} deposit rows ({len(unmatched_names)} distinct"
        f" resource names) have no exact match among {len(galaxy_names)} known"
        f" galaxy_resources node names:\n"
    )
    for name in unmatched_names:
        entries = rows_by_name[name]
        types = {r[1] for r in entries}
        label = repr(name) if name else "(blank)"
        count_note = f" [{len(entries)} rows]" if len(entries) > 1 else ""

        non_mineral = types & NON_MINERAL_TYPES.keys()
        if non_mineral:
            reasons = "; ".join(f"{t} ({NON_MINERAL_TYPES[t]})" for t in sorted(non_mineral))
            print(f"  {label:35}{count_note} -> not applicable - {reasons}")
            continue

        candidates = candidate_names(name, galaxy_names)
        confirmed = resolve_by_type(candidates, types, node_item_types) if candidates else None
        if confirmed:
            print(f"  {label:35}{count_note} -> {confirmed!r}"
                  f" (confirmed via res_type={sorted(types)})")
            continue
        if candidates:
            hint = ", ".join(repr(c) for c in candidates)
            print(f"  {label:35}{count_note} -> unresolved candidates: {hint}")
            continue

        sources = db.get_resource_sources(name)
        if sources:
            node_names = [n for n, _ in sources]
            in_galaxy = [n for n in node_names if n in galaxy_names]
            print(f"  {label:35}{count_note} -> raw material; node types:")
            print(f"  {'':35}    {', '.join(repr(n) for n in node_names)}")
            if in_galaxy:
                hint = ", ".join(repr(n) for n in in_galaxy)
                print(f"  {'':35}    galaxy data exists for: {hint}")
            else:
                print(f"  {'':35}    none of those node types are in galaxy_resources yet")
            continue

        suggestions = difflib.get_close_matches(name, galaxy_names, n=3, cutoff=FUZZY_CUTOFF)
        if suggestions:
            confirmed = resolve_by_type(suggestions, types, node_item_types)
            if confirmed:
                print(f"  {label:35}{count_note} -> {confirmed!r}"
                      f" (confirmed via res_type={sorted(types)})")
            else:
                hint = ", ".join(repr(s) for s in suggestions)
                print(f"  {label:35}{count_note} -> maybe: {hint}")
        else:
            print(f"  {label:35}{count_note} -> no match found at all (res_type={sorted(types)})")


if __name__ == "__main__":
    main()
