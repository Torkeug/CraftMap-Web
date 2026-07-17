"""Tests for backend.api.Api's galaxy-data methods (frontend/js/galaxy.js)
- thin wrappers over backend.db's galaxy_resources functions, already
covered directly by tests/test_db_galaxy_resources.py. These only check
the Api-level shaping (dict keys, JSON-serializability) and the
exclude_asteroids param's inverted pass-through to db's include_asteroids.
Same no-pywebview, isolated-temp-DB approach as test_api.py.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config as config_module, db as db_module  # noqa: E402
from backend.api import Api  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    db_module.init_db()
    return Api()


def test_get_galaxy_resource_names(api):
    db_module.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Clay Shell", 100, 1.0, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 30, 0.5, "poi0", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    names = api.get_galaxy_resource_names()
    json.dumps(names)
    assert names == ["Aquamarine", "Clay Shell"]


def test_get_galaxy_sources_shapes_rows_as_dicts(api):
    db_module.import_galaxy_resources([
        (
            "Sysices", "Sysices I", "Jester", "Aquamarine", 36, 0.29, "poi0,poi1", 4.96, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    rows = api.get_galaxy_sources("Aquamarine")
    json.dumps(rows)
    assert rows == [
        {
            "system_name": "Sysices",
            "planet": "Sysices I",
            "sector": "Jester",
            "node_count": 36,
            "density": 0.29,
            "poi_tags": "poi0,poi1",
            "pure_poi": True,
            "poi_area_density": 4.96,
            "is_asteroid": False,
            "temperature": "PlanetTemperate",
            "temperature_name": "Temperate",
            "attributes": None,
            "attribute_names": None,
        }
    ]


def test_get_galaxy_sources_excludes_asteroids_by_default(api):
    db_module.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Iron", 100, 5.0, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys2", "AST-1A2", "Sec1", "Iron", 200, 8.0, "general", None, 1,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    # default matches js/galaxy.js's own default (asteroid checkbox unchecked)
    default_rows = api.get_galaxy_sources("Iron")
    assert [r["planet"] for r in default_rows] == ["PlanetA"]

    all_rows = api.get_galaxy_sources("Iron", exclude_asteroids=False)
    assert [r["planet"] for r in all_rows] == ["AST-1A2", "PlanetA"]


def test_get_galaxy_sources_for_unknown_node_returns_empty(api):
    assert api.get_galaxy_sources("Nonexistent") == []


def test_get_galaxy_system_names(api):
    db_module.import_galaxy_systems([
        ("Talion", 0, 0, 0, "Cisax"),
        ("Cisax", 1, 1, 1, "Talion"),
    ])
    names = api.get_galaxy_system_names()
    json.dumps(names)
    assert names == ["Cisax", "Talion"]


def test_get_galaxy_hop_distances(api):
    db_module.import_galaxy_systems([
        ("Talion", 0, 0, 0, "Cisax"),
        ("Cisax", 1, 1, 1, "Retyx"),
    ])
    dist = api.get_galaxy_hop_distances("Talion")
    json.dumps(dist)
    assert dist == {"Talion": 0, "Cisax": 1, "Retyx": 2}


def test_get_galaxy_hop_distances_for_unknown_system_returns_empty(api):
    assert api.get_galaxy_hop_distances("Nonexistent") == {}


def test_add_galaxy_note_infers_res_type_from_existing_deposits(api):
    # Every "Quartz" deposit already logged uses "Resources" - a new
    # galaxy-sourced note for the same resource must pick that up rather
    # than leaving res_type blank (which showed as "(Uncategorized)" in
    # the deposit tracker instead of grouping with the resource's other
    # entries).
    api.add_deposit("Resources", "Quartz", "Sec1", "Sys1", "PlanetA", "")
    api.add_galaxy_note("Quartz", "Sec1", "Sys1", "PlanetB", "found here")
    locs = api.get_deposits_for_ingredient("Quartz")
    json.dumps(locs)
    new_row = next(r for r in locs if r["planet"] == "PlanetB")
    assert db_module.get_deposit(new_row["id"])[0] == "Resources"
    assert new_row["notes"] == "found here"


def test_add_galaxy_note_defaults_to_resources_type(api):
    # No prior deposit exists for this resource at all - falls back to
    # "Resources" (what virtually every Galaxy-tab-tracked resource uses),
    # not a blank res_type.
    api.add_galaxy_note("Elmerite", "Sec1", "Sys1", "PlanetC", "found here")
    locs = api.get_deposits_for_ingredient("Elmerite")
    assert db_module.get_deposit(locs[0]["id"])[0] == "Resources"


def test_add_galaxy_note_defaults_deposit_style_names_to_deposit_type(api):
    # No prior "Coal Deposit" row exists yet either, but every "Deposit"-
    # typed resource in the data has "deposit" in its own name (Coal
    # Deposit, Dense Iron Deposit, ...) and no "Resources"-typed one does -
    # a resource logged here for the first time should still land on
    # "Deposit", not silently fall all the way to "Resources".
    api.add_galaxy_note("Coal Deposit", "Sec1", "Sys1", "PlanetD", "found here")
    locs = api.get_deposits_for_ingredient("Coal Deposit")
    assert db_module.get_deposit(locs[0]["id"])[0] == "Deposit"


def test_add_galaxy_note_prefers_existing_precedent_over_name_heuristic(api):
    # A resource whose name doesn't scream either category, but has
    # already been logged with a specific type - that precedent wins over
    # the name-based fallback.
    api.add_deposit("Plant", "Strange Thicket", "Sec1", "Sys1", "PlanetA", "")
    api.add_galaxy_note("Strange Thicket", "Sec1", "Sys1", "PlanetE", "found here")
    locs = api.get_deposits_for_ingredient("Strange Thicket")
    new_row = next(r for r in locs if r["planet"] == "PlanetE")
    assert db_module.get_deposit(new_row["id"])[0] == "Plant"


def test_add_galaxy_note_rejects_duplicate_regardless_of_res_type(api):
    # find_duplicate_deposit must be checked against the SAME res_type
    # add_galaxy_note is about to insert, not a hardcoded blank one - a
    # blank-only check would miss an existing "Resources"-typed row for
    # the same planet and let a duplicate through.
    api.add_deposit("Resources", "Quartz", "Sec1", "Sys1", "PlanetA", "")
    with pytest.raises(ValueError):
        api.add_galaxy_note("Quartz", "Sec1", "Sys1", "PlanetA", "dup")


def test_add_galaxy_note_requires_planet(api):
    with pytest.raises(ValueError):
        api.add_galaxy_note("Quartz", "Sec1", "Sys1", "", "")


def test_add_galaxy_note_requires_nonblank_note(api):
    with pytest.raises(ValueError):
        api.add_galaxy_note("Quartz", "Sec1", "Sys1", "PlanetA", "")
    with pytest.raises(ValueError):
        api.add_galaxy_note("Quartz", "Sec1", "Sys1", "PlanetA", "   ")
    assert api.get_deposits_for_ingredient("Quartz") == []
