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
    api.set_queue_checked_many(0, ["__total__|Iron Ore"], True)
    assert api.clear_all_queue_checked() is True
    assert api.get_queue_checked_paths(qid1) == []
    assert api.get_queue_checked_paths(qid2) == []
    assert api.get_queue_checked_paths(0) == []


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
        "all_crafted": {},
        "all_raw": {},
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
    assert view["all_raw"] == {"Iron Ore": 16}  # (3+5)*2
    assert "Iron Bar" not in view["all_crafted"]  # Iron Bar is basic-crafted
    assert len(view["per_job"]) == 2


def test_get_queue_totals_view_excludes_uncombined_jobs(api):
    rid = _make_iron_bar(api, output_qty=1, ingredient_qty=2)
    qid = api.add_to_queue(rid, 3)
    api.update_queue_combine(qid, False)
    view = api.get_queue_totals_view()
    assert view["combined_count"] == 0
    assert view["all_raw"] == {}
    assert len(view["per_job"]) == 1  # per-job list still includes it


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
    assert view["all_crafted"]["Iron Bar"]["qty"] == 6  # 2 gears * 3 bars
    assert view["all_raw"]["Iron Ore"] == 12  # 6 bars * 2 ore
    assert view["all_crafted"]["Iron Bar"]["raw_names"] == ["Iron Ore"]


def test_get_queue_totals_view_sums_shared_basic_crafted_across_jobs(api):
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
    # Iron Bar is a shared basic-crafted ingredient of two different queued
    # jobs - its tally must sum across both rather than only keeping
    # whichever job's entry was created first.
    assert view["all_crafted"]["Iron Bar"]["qty"] == 10
    assert view["all_raw"]["Iron Ore"] == 20
