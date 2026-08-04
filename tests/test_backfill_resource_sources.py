"""Tests for tools/backfill_resource_sources.py's node_yields (and its
expected_qty formula in particular) - not backend.db, which
tests/test_api_sources.py covers directly.

The expected_qty formula was reverse engineered from the game's own
compiled Haxe bytecode (ResourceUtils.hx:getItemsExpectations, via hlbc) -
these fixtures are cross-checked against real resource_nodes.json entries
and, for Aluminum Reduction, against a real value the game's own
Encyclopedia UI displays ("Aluminum Nugget 20.02")."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.backfill_resource_sources import node_yields  # noqa: E402

ITEMS = {"AluminiumNugget": {"name": "Aluminum Nugget"}}


def test_node_yields_matches_encyclopedia_value_for_aluminum_reduction():
    # Real fixture (game_data_extract/resource_nodes.json's
    # "AluCluster_UnderwaterNative" entry) - the Encyclopedia UI shows
    # "Aluminum Nugget 20.02" for this exact node.
    node = {
        "id": "AluCluster_UnderwaterNative",
        "name": "Aluminum Reduction",
        "generation": {
            "amounts": [
                {"proba": 0},
                {"proba": 0},
                {"proba": 5},
                {"proba": 45},
                {"proba": 45},
                {"proba": 5},
            ],
            "secondaryMax": 1,
            "secondaryProba": 0.05,
            "size": 15,
        },
        "items": [
            {"item": "AluminiumNugget", "qtyMin": 5, "qtyMax": 7, "kind": 0, "proba": 10},
            {"kind": 1, "item": "Aquamarine", "proba": 20, "qtyMin": 1, "qtyMax": 3},
            {"kind": 1, "item": "Emerald", "proba": 1, "qtyMin": 1, "qtyMax": 1},
        ],
    }
    results = list(node_yields(node, ITEMS))
    name, label, concentration, expected_qty = results[0]
    assert name == "Aluminum Nugget"
    assert label == "Aluminum Reduction"
    assert concentration == 100.0
    assert round(expected_qty, 2) == 20.02


def test_node_yields_flat_avg_qty_when_no_generation_amounts():
    # Plant/seed-style nodes (e.g. Spacekorn Root) have no
    # generation.amounts distribution at all - the game just shows each
    # item's own flat average qty, unweighted by proba.
    node = {
        "name": "Spacekorn Root",
        "generation": {"flatTerrain": True, "size": 1.5},
        "items": [
            {"kind": 0, "item": "SpaceWheat_Seed", "proba": 10, "qtyMin": 1, "qtyMax": 1},
        ],
    }
    items = {"SpaceWheat_Seed": {"name": "Spacekorn Seed"}}
    results = list(node_yields(node, items))
    assert results == [("Spacekorn Seed", "Spacekorn Root", 100.0, 1.0)]


def test_node_yields_geyser_uses_flat_quantity():
    node = {"name": "Water Geyser", "props": {"geyser": {"fluid": "Water", "quantity": 100}}}
    items = {"Water": {"name": "Water"}}
    results = list(node_yields(node, items))
    assert results == [("Water", "Water Geyser", 100.0, 100)]


def test_node_yields_deposit_has_no_expected_qty():
    # Deposits are auto-mined at a per-hour rate (a different unit
    # entirely) - the game doesn't compute a per-harvest expected_qty for
    # them, so neither do we.
    node = {"name": "Aluminum Deposit", "props": {"depositItem": "AluminiumNugget"}}
    results = list(node_yields(node, ITEMS))
    assert results == [("Aluminum Nugget", "Aluminum Deposit", 100.0, None)]
