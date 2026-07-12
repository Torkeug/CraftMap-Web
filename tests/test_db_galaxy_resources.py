"""Tests for backend.db's galaxy_resources table - no Api layer yet (no
frontend consumes this table), so these exercise backend.db directly against
an isolated temp DB, the same way tests/test_api.py isolates it for Api."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db as db_module  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    return db_module


def test_import_is_idempotent(db):
    rows = [(
        "Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0", None, 0,
        "PlanetTemperate", "Temperate", None, None,
    )]
    assert db.import_galaxy_resources(rows) == 1
    assert db.import_galaxy_resources(rows) == 0


def test_get_galaxy_sources_ranks_by_effective_density_not_pure_poi_alone(db):
    db.import_galaxy_resources([
        # general, no poi_area_density - falls back to plain density
        (
            "Sys1", "PlanetA", "Sec1", "Graphite", 100, 1.0, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        # pure-POI but its poi_area_density is LOWER than PlanetA's density -
        # a real "worse spot", should NOT outrank PlanetA just for being POI
        (
            "Sys2", "PlanetB", "Sec1", "Graphite", 90, 0.40, "poi0,poi1", 0.5, 0,
            "PlanetHot1", "Hot", "PlanetHot1", "Hot",
        ),
        # pure-POI with poi_area_density HIGHER than every general row here -
        # the actual point: a small, tightly-packed POI can legitimately win
        (
            "Sys3", "PlanetC", "Sec1", "Graphite", 20, 0.15, "poi0", 4.7, 1,
            "PlanetTemperate", "Temperate", None, None,
        ),
        # mixed general+poi - can't be area-adjusted (unsplittable), falls
        # back to plain density like a general-only row
        (
            "Sys4", "PlanetD", "Sec1", "Graphite", 95, 0.90, "poi0,general", None, 0,
            "PlanetCold2", "Frozen", "PlanetCold2", "Frozen",
        ),
        # no poi_tags at all
        (
            "Sys5", "PlanetE", "Sec1", "Graphite", 10, 0.05, None, None, None,
            "PlanetTemperate", "Temperate", "PlanetWater", "Water presence",
        ),
    ])
    results = db.get_galaxy_sources_for_resource("Graphite")
    assert [r[1] for r in results] == ["PlanetC", "PlanetA", "PlanetD", "PlanetB", "PlanetE"]
    assert results[0][8] is True  # PlanetC is_asteroid
    assert results[1][8] is False  # PlanetA is_asteroid
    # temperature/temperature_name/attributes/attribute_names pass through untouched
    assert results[3][9:] == ("PlanetHot1", "Hot", "PlanetHot1", "Hot")  # PlanetB
    assert results[4][9:] == ("PlanetTemperate", "Temperate", "PlanetWater", "Water presence")  # PlanetE


def test_get_galaxy_sources_can_exclude_asteroids(db):
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Iron", 100, 5.0, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys2", "AST-1A2", "Sec1", "Iron", 200, 8.0, "general", None, 1,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    with_asteroids = db.get_galaxy_sources_for_resource("Iron")
    assert [r[1] for r in with_asteroids] == ["AST-1A2", "PlanetA"]

    without_asteroids = db.get_galaxy_sources_for_resource("Iron", include_asteroids=False)
    assert [r[1] for r in without_asteroids] == ["PlanetA"]


def test_get_galaxy_sources_for_missing_resource_returns_empty(db):
    assert db.get_galaxy_sources_for_resource("Nonexistent") == []
