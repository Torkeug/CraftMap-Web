"""Tests for backend.api.Api's Craft Queue methods (Milestone 5).

Same no-pywebview, isolated-temp-DB approach as test_api.py/
test_api_recipes.py - instantiate Api() directly and assert every return
value survives json.dumps, since that's the actual boundary crossed to
reach the browser.
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
    monkeypatch.setattr(resolver, "DB_PATH", test_db_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    db_module.init_db()
    return Api()


def _make_iron_bar(api_, output_qty=2, ingredient_qty=3, stations=None):
    return api_.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": output_qty}],
        ingredients=[{"name": "Iron Ore", "qty": ingredient_qty}],
        stations=stations or DEFAULT_STATIONS,
    )


def test_add_and_list_queue(api):
    rid = _make_iron_bar(api)
    qid = api.add_to_queue(rid, 4)
    json.dumps(qid)
    jobs = api.get_craft_queue()
    json.dumps(jobs)
    assert jobs == [
        {
            "queue_id": qid,
            "recipe_id": rid,
            "recipe_name": "Iron Bar",
            "output_name": "Iron Bar",
            "qty": 4,
            "station": None,
            "combine": True,
            "station_mode": "auto",
        }
    ]


def test_add_to_queue_merges_same_recipe_and_station(api):
    rid = _make_iron_bar(api)
    qid1 = api.add_to_queue(rid, 2, "Forge")
    qid2 = api.add_to_queue(rid, 3, "Forge")
    assert qid1 == qid2
    jobs = api.get_craft_queue()
    assert len(jobs) == 1
    assert jobs[0]["qty"] == 5


def test_add_to_queue_different_station_is_separate_job(api):
    rid = _make_iron_bar(api)
    api.add_to_queue(rid, 2, "Forge")
    api.add_to_queue(rid, 2, "Smelter")
    assert len(api.get_craft_queue()) == 2


def test_update_queue_qty_and_station(api):
    rid = _make_iron_bar(api)
    qid = api.add_to_queue(rid, 1)
    assert api.update_queue_qty(qid, 7) is True
    assert api.update_queue_station(qid, "Forge", "manual") is True
    job = api.get_craft_queue()[0]
    assert job["qty"] == 7
    assert job["station"] == "Forge"
    assert job["station_mode"] == "manual"


def test_update_queue_combine(api):
    rid = _make_iron_bar(api)
    qid = api.add_to_queue(rid, 1)
    assert api.update_queue_combine(qid, False) is True
    assert api.get_craft_queue()[0]["combine"] is False


def test_remove_from_queue(api):
    rid = _make_iron_bar(api)
    qid = api.add_to_queue(rid, 1)
    assert api.remove_from_queue(qid) is True
    assert api.get_craft_queue() == []


def test_queue_checked_round_trip(api):
    rid = _make_iron_bar(api)
    qid = api.add_to_queue(rid, 1)
    assert api.get_queue_checked_paths(qid) == []
    assert api.set_queue_checked_many(qid, ["Iron Bar", "Iron Bar|Iron Ore"], True) is True
    checked = api.get_queue_checked_paths(qid)
    json.dumps(checked)
    assert set(checked) == {"Iron Bar", "Iron Bar|Iron Ore"}
    assert api.set_queue_checked_many(qid, ["Iron Bar"], False) is True
    assert api.get_queue_checked_paths(qid) == ["Iron Bar|Iron Ore"]


def test_clear_all_queue_checked(api):
    rid = _make_iron_bar(api)
    qid1 = api.add_to_queue(rid, 1, "Forge")
    qid2 = api.add_to_queue(rid, 1, "Smelter")
    api.set_queue_checked_many(qid1, ["Iron Bar"], True)
    api.set_queue_checked_many(qid2, ["Iron Bar"], True)
    assert api.clear_all_queue_checked() is True
    assert api.get_queue_checked_paths(qid1) == []
    assert api.get_queue_checked_paths(qid2) == []


def test_get_queue_breakdown_view_unknown_job_returns_empty(api):
    assert api.get_queue_breakdown_view(999) == {
        "output_name": "",
        "checked": [],
        "tree": None,
    }


def test_get_queue_breakdown_view_uses_persisted_qty(api):
    rid = _make_iron_bar(api, output_qty=2, ingredient_qty=3)
    qid = api.add_to_queue(rid, 4)
    view = api.get_queue_breakdown_view(qid)
    json.dumps(view)
    assert view["output_name"] == "Iron Bar"
    assert view["checked"] == []
    tree = view["tree"]
    assert tree["is_recipe"] is True
    assert tree["qty"] == 4
    ore = tree["children"][0]
    assert ore["name"] == "Iron Ore"
    assert ore["qty"] == 6  # ceil(4/2)=2 crafts * 3 ore


def test_get_queue_breakdown_view_applies_job_station_override(api):
    rid = _make_iron_bar(
        api,
        stations=[
            {"station": "Forge", "auto": 10, "manual": 20},
            {"station": "Smelter", "auto": 5, "manual": None},
        ],
    )
    qid = api.add_to_queue(rid, 1, "Smelter")
    view = api.get_queue_breakdown_view(qid)
    json.dumps(view)
    tree = view["tree"]
    assert tree["station"] == "Smelter"
    assert tree["auto_craft_seconds"] == 5
    assert tree["craft_mode"] == "auto"


def test_get_queue_breakdown_view_truncates_deep_chains(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
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
    qid = api.add_to_queue(rid2, 1)
    view = api.get_queue_breakdown_view(qid)
    json.dumps(view)
    gear = view["tree"]["children"][0]
    iron_bar = gear["children"][0]
    assert iron_bar["truncated"] is True
    assert iron_bar["children"] == []
    subtree = api.get_recipe_subtree(iron_bar["name"], iron_bar["qty"], ["Axle", "Gear"])
    assert subtree["truncated"] is False
    assert subtree["children"][0]["name"] == "Iron Ore"


def test_get_queue_totals_view_empty_queue(api):
    view = api.get_queue_totals_view()
    json.dumps(view)
    assert view == {
        "jobs_count": 0,
        "combined_count": 0,
        "all_items": {},
        "per_job": [],
    }


def test_get_queue_totals_view_aggregates_combined_jobs(api):
    # Two distinct jobs of the same recipe (different stations, so
    # add_to_queue's same-recipe-and-station merge doesn't collapse them
    # into one row - see test_add_to_queue_merges_same_recipe_and_station).
    rid = _make_iron_bar(
        api,
        output_qty=1,
        ingredient_qty=2,
        stations=[{"station": "Forge", "auto": None, "manual": None},
                  {"station": "Smelter", "auto": None, "manual": None}],
    )
    api.add_to_queue(rid, 3, "Forge")
    api.add_to_queue(rid, 5, "Smelter")
    view = api.get_queue_totals_view()
    json.dumps(view)
    assert view["jobs_count"] == 2
    assert view["combined_count"] == 2
    assert view["all_items"]["Iron Ore"]["qty"] == 16  # (3+5)*2
    assert view["all_items"]["Iron Ore"]["is_recipe"] is False
    # Iron Bar is each job's own root - occurrences deliberately exclude
    # the root (it's shown by the job's own header, not a demand on
    # anything), so it's absent from all_items entirely, not merely
    # excluded from some "crafted" bucket.
    assert "Iron Bar" not in view["all_items"]
    assert len(view["per_job"]) == 2
    # per_job only carries identity - a job's own items are fetched lazily
    # via get_queue_totals_job_view, only once its section is expanded, not
    # shipped eagerly for every job on every call.
    for job in view["per_job"]:
        assert set(job.keys()) == {"queue_id", "recipe_name", "qty"}


def test_get_queue_totals_view_excludes_uncombined_jobs(api):
    rid = _make_iron_bar(api, output_qty=1, ingredient_qty=2)
    qid = api.add_to_queue(rid, 3)
    api.update_queue_combine(qid, False)
    view = api.get_queue_totals_view()
    assert view["combined_count"] == 0
    assert view["all_items"] == {}
    assert len(view["per_job"]) == 1  # per-job list still includes it


def test_get_queue_totals_job_view_returns_own_breakdown_even_when_uncombined(api):
    rid = _make_iron_bar(api, output_qty=1, ingredient_qty=2)
    qid = api.add_to_queue(rid, 3)
    api.update_queue_combine(qid, False)
    job_view = api.get_queue_totals_job_view(qid)
    json.dumps(job_view)
    assert job_view["items"]["Iron Ore"]["qty"] == 6

    assert api.get_queue_totals_job_view(999) == {"items": {}}


def test_get_queue_totals_view_basic_crafted_layer(api):
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
    api.add_to_queue(rid, 2)
    view = api.get_queue_totals_view()
    json.dumps(view)
    assert view["all_items"]["Iron Bar"]["qty"] == 6  # 2 gears * 3 bars
    assert view["all_items"]["Iron Bar"]["is_recipe"] is True
    assert view["all_items"]["Iron Ore"]["qty"] == 12  # 6 bars * 2 ore
    assert view["all_items"]["Iron Bar"]["raw_names"] == ["Iron Ore"]


def test_get_queue_totals_view_marks_root_demand_and_crafted_names_for_nested_bom(api):
    # Battleship Hull -> 4x Steel Plate (direct) + 2x Titanium Frame, and
    # Titanium Frame itself also needs 1x Steel Plate - the "Option D"
    # merged-BOM-tree scenario: Steel Plate is demanded both directly by a
    # job root AND via another crafted item, so it must be a top-level
    # ("is_root_demand") entry with its own Steel Ingot nested beneath it,
    # while Steel Ingot itself (never a direct root ingredient) is not.
    api.save_recipe(
        None,
        "Steel Ingot",
        outputs=[{"name": "Steel Ingot", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
        None,
        "Steel Plate",
        outputs=[{"name": "Steel Plate", "qty": 1}],
        ingredients=[{"name": "Steel Ingot", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
        None,
        "Titanium Ingot",
        outputs=[{"name": "Titanium Ingot", "qty": 1}],
        ingredients=[{"name": "Titanium Ore", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
        None,
        "Titanium Frame",
        outputs=[{"name": "Titanium Frame", "qty": 1}],
        ingredients=[
            {"name": "Titanium Ingot", "qty": 2},
            {"name": "Steel Plate", "qty": 1},
        ],
        stations=DEFAULT_STATIONS,
    )
    hull_id = api.save_recipe(
        None,
        "Battleship Hull",
        outputs=[{"name": "Battleship Hull", "qty": 1}],
        ingredients=[
            {"name": "Steel Plate", "qty": 4},
            {"name": "Titanium Frame", "qty": 2},
        ],
        stations=DEFAULT_STATIONS,
    )
    api.add_to_queue(hull_id, 1)
    view = api.get_queue_totals_view()
    json.dumps(view)

    steel_plate = view["all_items"]["Steel Plate"]
    assert steel_plate["qty"] == 6  # 4 direct + 2 via Titanium Frame
    assert steel_plate["is_root_demand"] is True
    assert steel_plate["crafted_names"] == ["Steel Ingot"]
    sources = {s["parent_name"]: s["qty"] for s in steel_plate["sources"]}
    assert sources == {"Battleship Hull": 4, "Titanium Frame": 2}

    titanium_frame = view["all_items"]["Titanium Frame"]
    assert titanium_frame["is_root_demand"] is True
    assert titanium_frame["crafted_names"] == ["Steel Plate", "Titanium Ingot"]

    # Steel Ingot is only ever reached via Steel Plate, never directly by
    # the Hull's own root - it must nest under Steel Plate, not show up as
    # its own top-level Crafted row.
    steel_ingot = view["all_items"]["Steel Ingot"]
    assert steel_ingot["is_root_demand"] is False
    assert steel_ingot["qty"] == 18  # 6 plates * 3 ingot each


def test_get_queue_totals_view_sums_shared_item_across_jobs(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    gear_id = api.save_recipe(
        None,
        "Gear",
        outputs=[{"name": "Gear", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    widget_id = api.save_recipe(
        None,
        "Widget",
        outputs=[{"name": "Widget", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 1}],
        stations=DEFAULT_STATIONS,
    )
    api.add_to_queue(gear_id, 2)  # needs 6 Iron Bar
    api.add_to_queue(widget_id, 4)  # needs 4 Iron Bar
    view = api.get_queue_totals_view()
    json.dumps(view)
    # Iron Bar is a shared crafted ingredient of two different queued jobs
    # (Option D's merged view) - its tally must sum across both rather than
    # only keeping whichever job's entry was created first, and its
    # "sources" note should attribute qty back to each job's own root.
    assert view["all_items"]["Iron Bar"]["qty"] == 10
    assert view["all_items"]["Iron Ore"]["qty"] == 20
    sources = {s["parent_name"]: s["qty"] for s in view["all_items"]["Iron Bar"]["sources"]}
    assert sources == {"Gear": 6, "Widget": 4}


def test_get_queue_totals_view_partial_checked_reduces_remaining_qty(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    gear_id = api.save_recipe(
        None,
        "Gear",
        outputs=[{"name": "Gear", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    widget_id = api.save_recipe(
        None,
        "Widget",
        outputs=[{"name": "Widget", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 1}],
        stations=DEFAULT_STATIONS,
    )
    api.add_to_queue(gear_id, 2)  # needs 6 Iron Bar -> 12 Iron Ore
    widget_qid = api.add_to_queue(widget_id, 4)  # needs 4 Iron Bar -> 8 Iron Ore

    # Check off only Widget's own Iron Bar occurrence (not Gear's).
    api.set_queue_checked_many(widget_qid, ["Widget|Iron Bar"], True)
    view = api.get_queue_totals_view()
    json.dumps(view)
    # Remaining qty reflects only the unchecked (Gear) occurrence - not the
    # full 10, not zero.
    assert view["all_items"]["Iron Bar"]["qty"] == 6
    assert view["all_items"]["Iron Bar"]["fully_checked"] is False
    assert view["all_items"]["Iron Bar"]["any_checked"] is True
    # Checked branches are pruned entirely, same as _subtree_remaining_
    # seconds - Widget's own Iron Ore demand (already-checked branch)
    # drops out, leaving only Gear's.
    assert view["all_items"]["Iron Ore"]["qty"] == 12

    # Now check off Gear's occurrence too - Iron Bar is fully done and
    # Iron Ore never gets recorded from either now-pruned branch.
    api.set_queue_checked_many(
        [j for j in api.get_craft_queue() if j["recipe_id"] == gear_id][0]["queue_id"],
        ["Gear|Iron Bar"],
        True,
    )
    view = api.get_queue_totals_view()
    json.dumps(view)
    assert view["all_items"]["Iron Bar"]["qty"] == 0
    assert view["all_items"]["Iron Bar"]["fully_checked"] is True
    assert "Iron Ore" not in view["all_items"]


def test_set_totals_item_checked_cascades_across_jobs(api):
    api.save_recipe(
        None,
        "Iron Bar",
        outputs=[{"name": "Iron Bar", "qty": 1}],
        ingredients=[{"name": "Iron Ore", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    gear_id = api.save_recipe(
        None,
        "Gear",
        outputs=[{"name": "Gear", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    widget_id = api.save_recipe(
        None,
        "Widget",
        outputs=[{"name": "Widget", "qty": 1}],
        ingredients=[{"name": "Iron Bar", "qty": 1}],
        stations=DEFAULT_STATIONS,
    )
    gear_qid = api.add_to_queue(gear_id, 2)
    widget_qid = api.add_to_queue(widget_id, 4)

    occurrences = api.get_queue_totals_view()["all_items"]["Iron Bar"]["occurrences"]
    assert api.set_totals_item_checked(occurrences, True) is True
    # Cascades onto both jobs' own real path_keys, self + descendants.
    assert set(api.get_queue_checked_paths(gear_qid)) == {"Gear|Iron Bar", "Gear|Iron Bar|Iron Ore"}
    assert set(api.get_queue_checked_paths(widget_qid)) == {
        "Widget|Iron Bar",
        "Widget|Iron Bar|Iron Ore",
    }

    assert api.set_totals_item_checked(occurrences, False) is True
    assert api.get_queue_checked_paths(gear_qid) == []
    assert api.get_queue_checked_paths(widget_qid) == []


def test_get_queue_totals_view_marks_is_shared_for_non_root_demand_items(api):
    # Base Part is used by two different intermediate assemblies (Assembly
    # A, Assembly B), NEITHER of which is a job root itself - so Base Part
    # is genuinely shared (is_shared) without ever being root-demand,
    # unlike the earlier Steel Plate/Titanium Frame scenario where sharing
    # happened to coincide with a direct root ingredient.
    api.save_recipe(
        None,
        "Base Part",
        outputs=[{"name": "Base Part", "qty": 1}],
        ingredients=[{"name": "Raw Stuff", "qty": 1}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
        None,
        "Assembly A",
        outputs=[{"name": "Assembly A", "qty": 1}],
        ingredients=[{"name": "Base Part", "qty": 2}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
        None,
        "Assembly B",
        outputs=[{"name": "Assembly B", "qty": 1}],
        ingredients=[{"name": "Base Part", "qty": 3}],
        stations=DEFAULT_STATIONS,
    )
    top_id = api.save_recipe(
        None,
        "Top Thing",
        outputs=[{"name": "Top Thing", "qty": 1}],
        ingredients=[
            {"name": "Assembly A", "qty": 1},
            {"name": "Assembly B", "qty": 1},
        ],
        stations=DEFAULT_STATIONS,
    )
    qid = api.add_to_queue(top_id, 1)
    view = api.get_queue_totals_view()
    json.dumps(view)

    assert view["all_items"]["Assembly A"]["is_root_demand"] is True
    assert view["all_items"]["Assembly A"]["is_shared"] is False
    assert view["all_items"]["Assembly B"]["is_root_demand"] is True
    assert view["all_items"]["Assembly B"]["is_shared"] is False

    base_part = view["all_items"]["Base Part"]
    assert base_part["is_root_demand"] is False
    assert base_part["is_shared"] is True
    assert base_part["qty"] == 5  # 2 via Assembly A + 3 via Assembly B

    occ_by_parent = {}
    for occ in base_part["occurrences"]:
        assert set(occ.keys()) == {"queue_id", "path_key", "parent_name", "checked"}
        occ_by_parent.setdefault(occ["parent_name"], []).append(occ)
    assert set(occ_by_parent.keys()) == {"Assembly A", "Assembly B"}

    # Checking off only Assembly A's occurrence of Base Part must not
    # touch Assembly B's - the whole point of scoping a cross-reference's
    # checkbox to its own parent, rather than cascading every occurrence
    # of the item everywhere the way the item's own main row does.
    assert api.set_totals_item_checked(occ_by_parent["Assembly A"], True) is True
    assert set(api.get_queue_checked_paths(qid)) == {
        "Top Thing|Assembly A|Base Part",
        "Top Thing|Assembly A|Base Part|Raw Stuff",
    }
    view2 = api.get_queue_totals_view()
    assert view2["all_items"]["Base Part"]["qty"] == 3  # only Assembly B's 3 remain
    assert view2["all_items"]["Base Part"]["fully_checked"] is False
    assert view2["all_items"]["Base Part"]["any_checked"] is True
