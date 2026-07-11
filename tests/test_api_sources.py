"""Tests for backend.api.Api's basic-resource / resource-sources methods -
the raw materials (get_basic_resources) that get added to the recipe
combo's Used-In lookup, and the dedicated Sources tab's resource_sources
CRUD (get/set_resource_sources, get_all_resource_source_names,
get_resources_with_sources). Same no-pywebview, isolated-temp-DB approach
as test_api.py.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config as config_module, db as db_module  # noqa: E402
from backend.api import Api  # noqa: E402

DEFAULT_STATIONS = [{"station": "Station", "auto": None, "manual": None}]


@pytest.fixture
def api(tmp_path, monkeypatch):
    test_db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    db_module.init_db()
    return Api()


def test_get_basic_resources_excludes_recipe_outputs(api):
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
    basics = api.get_basic_resources()
    json.dumps(basics)
    # Iron Ore is only ever an ingredient - Iron Bar is also a recipe output,
    # so it's crafted, not "basic".
    assert basics == ["Iron Ore"]


def test_get_basic_resources_includes_byproduct_only_outputs(api):
    # Azurite Stone's recipe yields Azurite Stone (primary) and Malachite
    # Stone (byproduct) - Malachite Stone has no recipe of its own name, so
    # it should still count as "basic" (mined, not craftable by that name).
    api.save_recipe(
        None,
        "Azurite Stone",
        outputs=[
            {"name": "Azurite Stone", "qty": 2},
            {"name": "Malachite Stone", "qty": 8},
        ],
        ingredients=[{"name": "Copper Ingot", "qty": 50}],
        stations=DEFAULT_STATIONS,
    )
    api.save_recipe(
        None,
        "Copper Ingot (Malachite Stone)",
        outputs=[{"name": "Copper Ingot", "qty": 4}],
        ingredients=[{"name": "Malachite Stone", "qty": 4}],
        stations=DEFAULT_STATIONS,
    )
    basics = api.get_basic_resources()
    json.dumps(basics)
    assert "Malachite Stone" in basics
    # Copper Ingot is still excluded - it IS a primary output (of the
    # "Copper Ingot (Malachite Stone)" recipe).
    assert "Copper Ingot" not in basics


def test_resource_sources_round_trip(api):
    assert api.get_resource_sources("a-Carbon") == []
    assert (
        api.set_resource_sources(
            "a-Carbon",
            [
                {"name": "Coal Clump", "concentration": 25.0},
                {"name": "Vitreous Carbon", "concentration": None},
            ],
        )
        is True
    )
    sources = api.get_resource_sources("a-Carbon")
    json.dumps(sources)
    # Highest concentration first; nulls sort last.
    assert sources == [
        {"name": "Coal Clump", "concentration": 25.0},
        {"name": "Vitreous Carbon", "concentration": None},
    ]


def test_set_resource_sources_replaces_and_dedupes(api):
    api.set_resource_sources("a-Carbon", [{"name": "Coal Clump", "concentration": None}])
    api.set_resource_sources(
        "a-Carbon",
        [
            {"name": "Vitreous Carbon", "concentration": 10},
            {"name": "Vitreous Carbon", "concentration": 10},
            {"name": "", "concentration": None},
        ],
    )
    assert api.get_resource_sources("a-Carbon") == [
        {"name": "Vitreous Carbon", "concentration": 10}
    ]


def test_get_all_resource_source_names(api):
    api.set_resource_sources("a-Carbon", [{"name": "Coal Clump", "concentration": None}])
    api.set_resource_sources("Iron Ore", [{"name": "Ferric Stone", "concentration": None}])
    names = api.get_all_resource_source_names()
    json.dumps(names)
    assert names == ["Coal Clump", "Ferric Stone"]


def test_get_resources_with_sources(api):
    api.set_resource_sources("a-Carbon", [{"name": "Coal Clump", "concentration": None}])
    resources = api.get_resources_with_sources()
    json.dumps(resources)
    assert resources == ["a-Carbon"]
