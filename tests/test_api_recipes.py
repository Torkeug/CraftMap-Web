"""Tests for backend.api.Api's recipe-panel methods (Milestone 4).

Same no-pywebview, isolated-temp-DB approach as test_api.py - instantiate
Api() directly and assert every return value survives json.dumps, since
that's the actual boundary crossed to reach the browser.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config as config_module, db as db_module, resolver  # noqa: E402
from backend.api import Api  # noqa: E402

DEFAULT_STATIONS = [{"station": "Station", "auto": None, "manual": None}]


@pytest.fixture
def api(tmp_path, monkeypatch):
    test_db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)
    # resolver.py has its own separate `DB_PATH` name bound at import time
    # (`from .paths import DB_PATH`) - patching db_module.DB_PATH alone
    # doesn't affect it, so get_recipe_breakdown would silently read the
    # real shared production DB instead of this test's isolated one.
    monkeypatch.setattr(resolver, "DB_PATH", test_db_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    db_module.init_db()
    return Api()


def test_save_and_list_recipe(api):
    rid = api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 2}],
        ingredients=[{"name": "Iron Ore", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    json.dumps(rid)
    recipes = api.get_all_recipes()
    json.dumps(recipes)
    assert recipes == [{"id": rid, "name": "Iron Bar"}]
    assert api.get_recipe_by_name("Iron Bar") == rid
    assert api.get_recipe_outputs(rid) == [{"name": "Iron Bar", "qty": 2}]
    assert api.get_recipe_ingredients(rid) == [{"name": "Iron Ore", "qty": 3}]
    assert api.get_recipe_stations(rid) == [
        {"station": "Station", "auto": None, "manual": None}
    ]


def test_update_existing_recipe_keeps_same_id(api):
    rid = api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 2}],
        ingredients=[{"name": "Iron Ore", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    rid2 = api.save_recipe(
        rid,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 4}],
        ingredients=[{"name": "Iron Ore", "qty": 6}],
        stations=DEFAULT_STATIONS,
    )
    assert rid2 == rid
    assert api.get_recipe_outputs(rid) == [{"name": "Iron Bar", "qty": 4}]


def test_delete_recipe(api):
    rid = api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 2}],
        ingredients=[{"name": "Iron Ore", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    assert api.delete_recipe(rid) is True
    assert api.get_all_recipes() == []


def test_recipe_breakdown_is_json_serializable_tree(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 2}],
        ingredients=[{"name": "Iron Ore", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    tree = api.get_recipe_breakdown("Iron Bar", qty_needed=4)
    json.dumps(tree)
    assert tree["is_recipe"] is True
    assert tree["output_qty"] == 2
    ore = tree["children"][0]
    assert ore["name"] == "Iron Ore"
    assert ore["qty"] == 6  # ceil(4/2)=2 crafts * 3 ore


def test_get_breakdown_view_combines_output_checked_and_tree(api):
    rid = api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 2}],
        ingredients=[{"name": "Iron Ore", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    view = api.get_breakdown_view(rid, qty_needed=4)
    json.dumps(view)
    assert view["output_name"] == "Iron Bar"
    assert view["checked"] == []
    assert view["tree"]["output_qty"] == 2
    assert view["tree"]["children"][0]["name"] == "Iron Ore"


def test_get_breakdown_view_unknown_recipe_returns_empty(api):
    view = api.get_breakdown_view(999)
    assert view == {"output_name": "", "checked": [], "tree": None}


def test_get_breakdown_view_truncates_deep_chains(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    rid = api.save_recipe(
        None,
        "Gear",
        outputs=[{"name": "Gear", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    rid2 = api.save_recipe(
        None,
        "Axle",
        outputs=[{"name": "Axle", "qty": 1}],
        ingredients=[{"name": "Gear", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )

    view = api.get_breakdown_view(rid2, qty_needed=1)
    json.dumps(view)
    tree = view["tree"]
    assert tree["truncated"] is False  # depth 0: Axle
    gear = tree["children"][0]
    assert gear["truncated"] is False  # depth 1: Gear
    iron_bar = gear["children"][0]
    assert iron_bar["truncated"] is True  # depth 2: cut off here
    assert iron_bar["children"] == []
    assert iron_bar["qty"] == 6  # metadata/scaling still correct despite truncation


def test_get_recipe_subtree_resumes_from_truncated_node(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    rid = api.save_recipe(
        None,
        "Gear",
        outputs=[{"name": "Gear", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    rid2 = api.save_recipe(
        None,
        "Axle",
        outputs=[{"name": "Axle", "qty": 1}],
        ingredients=[{"name": "Gear", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    view = api.get_breakdown_view(rid2, qty_needed=1)
    iron_bar = view["tree"]["children"][0]["children"][0]
    assert iron_bar["truncated"] is True

    subtree = api.get_recipe_subtree(
        iron_bar["name"], iron_bar["qty"], ["Axle", "Gear"]
    )
    json.dumps(subtree)
    assert subtree["truncated"] is False
    assert subtree["children"][0]["name"] == "Iron Ore"
    # iron_bar["qty"]=6 needed -> ceil(6/1)=6 crafts * 2 ore each = 12
    assert subtree["children"][0]["qty"] == 12


def test_alt_pref_round_trip(api):
    assert api.get_alt_prefs() == {}
    assert api.set_alt_pref("Iron Ore", 42) is True
    assert api.get_alt_prefs() == {"Iron Ore": 42}


def test_station_pref_round_trip(api):
    assert api.get_station_prefs() == {}
    assert api.set_station_pref("Iron Bar", "Smelter", "manual") is True
    prefs = api.get_station_prefs()
    json.dumps(prefs)
    assert prefs == {"Iron Bar": {"station": "Smelter", "mode": "manual"}}


def test_recipes_using_ingredient(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    rows = api.get_recipes_using_ingredient("Iron Ore")
    json.dumps(rows)
    assert rows == [
        {
            "recipe_id": api.get_recipe_by_name("Iron Bar"),
            "recipe_name": "Iron Bar",
            "qty": 2,
            "output_name": "Iron Bar",
            "output_qty": 1,
        }
    ]


def test_all_ingredient_options_includes_produced_and_raw(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    options = api.get_all_ingredient_options()
    assert options == ["Iron Bar", "Iron Ore"]


def test_get_deposits_for_ingredient(api):
    api.add_deposit("Ore", "Iron Ore", "Sec1", "Sys1", "PlanetA", "")
    locs = api.get_deposits_for_ingredient("Iron Ore")
    json.dumps(locs)
    assert locs == [{"sector": "Sec1", "system_name": "Sys1", "planet": "PlanetA"}]
