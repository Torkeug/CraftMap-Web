"""Static shipwreck rare-loot-crate reference data (frontend/js/wrecks.js's
"Wrecks" tab) - derived from the game's own files by
game_data_extract/extract_shipwreck_loot.py, not hand-maintained, so unlike
deposits/recipes there's no SQLite table for this: it's just loaded once
from shipwreck_loot.json and cached in memory. See
game_data_extract/shipwreck_loot_integration.md for the original plan and
shipwreck_loot.json's own _meta block for how the drop odds are derived.

Path resolution mirrors main.py's own frontend-dir split (sys._MEIPASS when
frozen under PyInstaller, __file__'s directory when running from source) -
this data ships as bundled PyInstaller data alongside frontend/ (see
build.bat), not alongside the app's own install dir the way DB_PATH/
CONFIG_PATH do in paths.py, since it's read-only reference data baked into
the build rather than this install's own persisted state.

Both getters below return their FULL dataset (every sector / every item) in
one call rather than a names-only list plus a per-name detail lookup: the
frontend builds a browsable tree from the whole thing and filters/expands
it client-side as the user types, so a second round trip per node the user
expands would just be latency with no benefit - this data is small (~150KB
raw JSON) and static, unlike the recipe tree's own depth-limited/on-demand
scheme in resolver.py (which exists because a recipe tree can be deep and
its per-node cost is real DB/graph work, neither of which applies here).
"""

import json
import os
import sys

_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOOT_PATH = os.path.join(_BASE_DIR, "game_data_extract", "shipwreck_loot.json")

# secondaryMaterialPool entries are the game's own internal item ids, not
# display names (shipwreck_loot.json doesn't carry those - only
# game_data_extract/items.json does, which isn't bundled/loaded at runtime -
# see this module's own docstring on why only shipwreck_loot.json is). Only
# 12 distinct ids ever appear there across every sector, so a small
# hardcoded lookup (looked up once from items.json) is simpler than adding a
# second ~150KB runtime dependency + build.bat --add-data entry for a dozen
# names - same call CLAUDE.md's RESOURCE_SIZE_VARIANTS in db.py makes for
# other static, unlikely-to-change game data. PlumbingLoot has no real
# in-game display name (items.json lists it as a nameless "Virtual" type
# entry) - "Plumbing Scrap" is a humanized stand-in, not an authoritative
# in-game string.
SECONDARY_MATERIAL_NAMES = {
    "AluminiumIngot": "Aluminum Ingot",
    "Carbon": "a-Carbon",
    "CopperIngot": "Copper Ingot",
    "Graphene": "Graphene",
    "IronIngot": "Iron Ingot",
    "Kaolinite": "Kaolinite",
    "PlumbingLoot": "Plumbing Scrap",
    "Sandstone": "Silicate",
    "SiliciumIngot": "Silicon Ingot",
    "Sulfur": "Sulfur",
    "TitaniumIngot": "Titanium Ingot",
    "VanadiumIngot": "Vanadium Ingot",
}

_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(_LOOT_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def _wreck_site_lookup(data):
    """(category, item name, sector name) -> {expected_per_wreck,
    at_least_one_pct} from wreckSiteItemOdds, flattened to a lookup rather
    than reused as-is: wreckSiteItemOdds groups sectors by matching
    expectedPerWreck, which is a DIFFERENT grouping than itemDropOdds's own
    (matching pct) - a sector's crate-count mix affects expectedPerWreck but
    not pct, so the two group lists don't line up sector-for-sector. Only
    covers items where obtainable is true (see itemDropOdds's own field) -
    an unobtainable item has empty groups on both sides, so callers keyed
    off itemDropOdds's groups/sectors never look one up anyway."""
    lookup = {}
    for category, key in (("patch", "patches"), ("blueprint", "blueprints")):
        for item in data["wreckSiteItemOdds"][key]:
            for group in item["groups"]:
                for sector_name in group["sectors"]:
                    lookup[(category, item["name"], sector_name)] = {
                        "expected_per_wreck": group["expectedPerWreck"],
                        "at_least_one_pct": group["atLeastOnePct"],
                    }
    return lookup


def get_all_sectors():
    """Every sector's reachable loot-level mix plus every Patch/Blueprint
    obtainable there, reorganized from itemDropOdds (already computed
    per-item/per-sector-group there - see its own _meta.mechanism_notes)
    rather than re-deriving eligibility from patchPoolByLevel/
    blueprintPoolByLevel here too.

    crate_spawn_* answers a DIFFERENT question from loot_level_probability
    and the items list: whether a wreck in this sector contains a rare loot
    crate AT ALL (as opposed to only ordinary scrap), not what's in one
    given that it exists - see sectors[*].crateSpawn's own note in the raw
    JSON's _meta.mechanism_notes for the full derivation (a single wreck can
    hold more than one crate, so this is a count distribution, not a single
    spawn-or-not %).

    Each item row's own pct is itemDropOdds's (conditional on a crate
    already being open); expected_per_wreck/at_least_one_pct alongside it
    are wreckSiteItemOdds's (fold in the sector's own crate-count mix too -
    see _wreck_site_lookup and shipwreck_loot_integration.md)."""
    data = _load()
    wreck_site = _wreck_site_lookup(data)
    sector_items = {name: [] for name in (s["name"] for s in data["sectors"].values())}
    for category, key in (("patch", "patches"), ("blueprint", "blueprints")):
        for item in data["itemDropOdds"][key]:
            for group in item["groups"]:
                for sector_name in group["sectors"]:
                    if sector_name not in sector_items:
                        continue
                    site = wreck_site.get((category, item["name"], sector_name), {})
                    sector_items[sector_name].append(
                        {
                            "name": item["name"],
                            "category": category,
                            "level": item["level"],
                            "pct": group["pct"],
                            "expected_per_wreck": site.get("expected_per_wreck"),
                            "at_least_one_pct": site.get("at_least_one_pct"),
                        }
                    )

    sectors = []
    for sector in data["sectors"].values():
        items = sector_items[sector["name"]]
        items.sort(key=lambda i: (i["level"], -i["pct"], i["name"]))
        crate_spawn = sector["crateSpawn"]
        sectors.append(
            {
                "name": sector["name"],
                "explo_level": sector["exploLevel"],
                "max_loot_level": sector["maxLootLevel"],
                "loot_level_probability": sector["lootLevelProbability"],
                "secondary_material_pool": [
                    SECONDARY_MATERIAL_NAMES.get(m, m) for m in sector["secondaryMaterialPool"]
                ],
                "crate_spawn_at_least_one": crate_spawn["atLeastOne"],
                "crate_spawn_expected_count": crate_spawn["expectedCount"],
                "crate_spawn_count_distribution": crate_spawn["countDistribution"],
                "items": items,
            }
        )
    sectors.sort(key=lambda s: s["name"].lower())
    return sectors


def get_all_items():
    """Every Patch/Blueprint's own itemDropOdds entry (already the
    item-first shape - see shipwreck_loot_integration.md), tagged with its
    category since itemDropOdds keeps those in separate lists rather than
    on each item.

    best_expected_per_wreck/best_at_least_one_pct and each group.sectors
    entry's own expected_per_wreck/at_least_one_pct come from
    wreckSiteItemOdds - missing (None) for the handful of items marked
    obtainable: false, which wreckSiteItemOdds never lists at all (see
    _wreck_site_lookup). best_at_least_one_pct is the atLeastOnePct of
    whichever wreckSiteItemOdds group has the best expectedPerWreck, since
    that source has no top-level "best" field of its own the way bestPct
    already is for itemDropOdds."""
    data = _load()
    wreck_site = _wreck_site_lookup(data)
    wreck_site_items = {
        (category, item["name"]): item
        for category, key in (("patch", "patches"), ("blueprint", "blueprints"))
        for item in data["wreckSiteItemOdds"][key]
    }
    items = []
    for category, key in (("patch", "patches"), ("blueprint", "blueprints")):
        for item in data["itemDropOdds"][key]:
            site_item = wreck_site_items.get((category, item["name"]))
            best_group = (
                max(site_item["groups"], key=lambda g: g["expectedPerWreck"])
                if site_item
                else None
            )
            items.append(
                {
                    "name": item["name"],
                    "category": category,
                    "level": item["level"],
                    "best_pct": item["bestPct"],
                    "obtainable": item["obtainable"],
                    "best_expected_per_wreck": site_item["bestExpectedPerWreck"] if site_item else None,
                    "best_at_least_one_pct": best_group["atLeastOnePct"] if best_group else None,
                    "groups": [
                        {
                            "pct": g["pct"],
                            "sectors": [
                                {
                                    "name": sector_name,
                                    "expected_per_wreck": wreck_site.get(
                                        (category, item["name"], sector_name), {}
                                    ).get("expected_per_wreck"),
                                    "at_least_one_pct": wreck_site.get(
                                        (category, item["name"], sector_name), {}
                                    ).get("at_least_one_pct"),
                                }
                                for sector_name in g["sectors"]
                            ],
                        }
                        for g in item["groups"]
                    ],
                }
            )
    items.sort(key=lambda i: i["name"].lower())
    return items
