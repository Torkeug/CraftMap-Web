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


def test_resource_family_resolves_symmetrically():
    assert db_module._resource_family("Coal Clump") == db_module._resource_family("Big Coal Clump")
    assert set(db_module._resource_family("Coal Clump")) == {"Coal Clump", "Big Coal Clump"}
    # a resource with no known size variant is its own singleton family
    assert db_module._resource_family("Iron") == ["Iron"]


def test_get_galaxy_sources_combines_size_variants_on_the_same_planet(db):
    db.import_galaxy_resources([
        # same planet, both variants purely tied to the SAME poi0 - the
        # combinable case: node_count/density sum, poi_area_density sums too
        (
            "Sys1", "PlanetA", "Sec1", "Coal Clump", 100, 1.0, "poi0", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys1", "PlanetA", "Sec1", "Big Coal Clump", 50, 0.5, "poi0", 1.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        # a different planet with only the base resource - unaffected
        (
            "Sys2", "PlanetB", "Sec1", "Coal Clump", 200, 2.5, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    # queryable by either the base name or the variant's own name
    for query_name in ("Coal Clump", "Big Coal Clump"):
        results = db.get_galaxy_sources_for_resource(query_name)
        by_planet = {r[1]: r for r in results}
        assert len(results) == 2
        combined = by_planet["PlanetA"]
        assert combined[3] == 150  # node_count summed
        assert combined[4] == pytest.approx(1.5)  # density summed
        assert combined[5] == "poi0"  # poi_tags union (identical on both rows)
        assert combined[6] is True  # pure_poi
        assert combined[7] == pytest.approx(3.0)  # poi_area_density summed (same footprint)
        assert by_planet["PlanetB"][3] == 200  # untouched single-variant planet


def test_get_galaxy_sources_leaves_poi_area_density_none_when_variants_have_different_poi_tags(db):
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Coal Clump", 100, 1.0, "poi0", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        # same planet, but this variant is scattered ("general") rather than
        # tied to poi0 - the two rows' poi_area_density figures are on
        # different area denominators and can't be honestly summed
        (
            "Sys1", "PlanetA", "Sec1", "Big Coal Clump", 50, 0.5, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    results = db.get_galaxy_sources_for_resource("Coal Clump")
    assert len(results) == 1
    combined = results[0]
    assert combined[3] == 150
    assert combined[5] == "general,poi0"  # union of both rows' tags
    assert combined[6] is False  # pure_poi - "general" is present
    assert combined[7] is None  # can't combine poi_area_density across differing footprints
