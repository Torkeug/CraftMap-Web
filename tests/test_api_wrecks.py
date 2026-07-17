"""Tests for backend.api.Api's shipwreck-loot methods (the "Wrecks" tab -
frontend/js/wrecks.js) - static, JSON-file-backed reference data, not
DB-backed, so unlike test_api_sources.py there's no isolated-temp-DB
fixture here; these read the real game_data_extract/shipwreck_loot.json
shipped with the repo. Both endpoints return their FULL dataset (the
frontend builds a browsable tree and filters it client-side - see
backend/shipwreck_loot.py's own module docstring).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.api import Api  # noqa: E402


def test_get_wreck_sectors_returns_every_sector_sorted():
    api = Api()
    sectors = api.get_wreck_sectors()
    json.dumps(sectors)
    names = [s["name"] for s in sectors]
    assert "Threshold" in names
    assert names == sorted(names, key=str.lower)


def test_get_wreck_sectors_items_grouped_and_sorted():
    api = Api()
    sectors = api.get_wreck_sectors()
    threshold = next(s for s in sectors if s["name"] == "Threshold")
    assert threshold["explo_level"] == 1
    assert threshold["max_loot_level"] == 4
    assert isinstance(threshold["secondary_material_pool"], list)
    assert threshold["items"], "Threshold should have at least one obtainable item"
    for item in threshold["items"]:
        assert item["category"] in ("patch", "blueprint")
        assert isinstance(item["level"], int)
        assert isinstance(item["pct"], (int, float))
        # every item here came from itemDropOdds's own groups, and
        # wreckSiteItemOdds covers every obtainable item (see
        # backend/shipwreck_loot.py's _wreck_site_lookup) - so both should
        # always be populated for a sector's own item rows.
        assert isinstance(item["expected_per_wreck"], (int, float))
        assert isinstance(item["at_least_one_pct"], (int, float))
    levels = [i["level"] for i in threshold["items"]]
    assert levels == sorted(levels)


def test_get_wreck_sectors_crate_spawn_odds():
    """crate_spawn_* answers a different question from loot_level_probability/
    items: whether a wreck has a rare loot crate at all, not what's in one -
    see backend/shipwreck_loot.py's get_all_sectors docstring."""
    api = Api()
    sectors = api.get_wreck_sectors()
    json.dumps(sectors)
    threshold = next(s for s in sectors if s["name"] == "Threshold")
    assert 0 <= threshold["crate_spawn_at_least_one"] <= 1
    assert threshold["crate_spawn_expected_count"] >= 0
    dist = threshold["crate_spawn_count_distribution"]
    assert isinstance(dist, dict) and dist
    assert abs(sum(dist.values()) - 1) < 1e-3


def test_get_wreck_items_returns_every_item_sorted():
    api = Api()
    items = api.get_wreck_items()
    json.dumps(items)
    assert items, "expected at least one Patch/Blueprint entry"
    names = [i["name"] for i in items]
    assert names == sorted(names, key=str.lower)
    for item in items:
        assert item["category"] in ("patch", "blueprint")
        assert isinstance(item["level"], int)
        assert isinstance(item["best_pct"], (int, float))
        assert isinstance(item["obtainable"], bool)
        for group in item["groups"]:
            assert isinstance(group["pct"], (int, float))
            assert isinstance(group["sectors"], list) and group["sectors"]
            for sector in group["sectors"]:
                assert isinstance(sector["name"], str)
                if item["obtainable"]:
                    assert isinstance(sector["expected_per_wreck"], (int, float))
                    assert isinstance(sector["at_least_one_pct"], (int, float))
        if item["obtainable"]:
            assert isinstance(item["best_expected_per_wreck"], (int, float))
            assert isinstance(item["best_at_least_one_pct"], (int, float))
        else:
            # wreckSiteItemOdds never lists an unobtainable item at all -
            # see backend/shipwreck_loot.py's _wreck_site_lookup.
            assert item["best_expected_per_wreck"] is None
            assert item["best_at_least_one_pct"] is None
            assert item["groups"] == []


def test_get_wreck_items_matches_sector_view():
    """Cross-check: an item obtainable at a given sector (per
    get_wreck_sectors) should report that same sector/pct/at_least_one_pct
    from get_wreck_items - both are reorganizations of the same
    itemDropOdds/wreckSiteItemOdds source data."""
    api = Api()
    sectors = api.get_wreck_sectors()
    threshold = next(s for s in sectors if s["name"] == "Threshold")
    sector_item = threshold["items"][0]

    items = api.get_wreck_items()
    item = next(i for i in items if i["name"] == sector_item["name"])
    matching = [
        (g["pct"], s["at_least_one_pct"])
        for g in item["groups"]
        for s in g["sectors"]
        if s["name"] == "Threshold"
    ]
    assert matching == [(sector_item["pct"], sector_item["at_least_one_pct"])]
