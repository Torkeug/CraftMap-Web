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
    spawn-or-not %)."""
    data = _load()
    sector_items = {name: [] for name in (s["name"] for s in data["sectors"].values())}
    for category, key in (("patch", "patches"), ("blueprint", "blueprints")):
        for item in data["itemDropOdds"][key]:
            for group in item["groups"]:
                for sector_name in group["sectors"]:
                    if sector_name not in sector_items:
                        continue
                    sector_items[sector_name].append(
                        {
                            "name": item["name"],
                            "category": category,
                            "level": item["level"],
                            "pct": group["pct"],
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
    on each item."""
    data = _load()
    items = [
        {
            "name": item["name"],
            "category": category,
            "level": item["level"],
            "best_pct": item["bestPct"],
            "obtainable": item["obtainable"],
            "groups": [
                {"pct": g["pct"], "sectors": g["sectors"]} for g in item["groups"]
            ],
        }
        for category, key in (("patch", "patches"), ("blueprint", "blueprints"))
        for item in data["itemDropOdds"][key]
    ]
    items.sort(key=lambda i: i["name"].lower())
    return items
