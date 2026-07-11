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
    levels = [i["level"] for i in threshold["items"]]
    assert levels == sorted(levels)


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


def test_get_wreck_items_matches_sector_view():
    """Cross-check: an item obtainable at a given sector (per
    get_wreck_sectors) should report that same sector/pct from
    get_wreck_items - both are reorganizations of the same itemDropOdds
    source data."""
    api = Api()
    sectors = api.get_wreck_sectors()
    threshold = next(s for s in sectors if s["name"] == "Threshold")
    sector_item = threshold["items"][0]

    items = api.get_wreck_items()
    item = next(i for i in items if i["name"] == sector_item["name"])
    matching_pct = [g["pct"] for g in item["groups"] if "Threshold" in g["sectors"]]
    assert matching_pct == [sector_item["pct"]]
