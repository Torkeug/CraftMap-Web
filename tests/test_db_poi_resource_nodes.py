"""Tests for backend.db's poi_resource_nodes table - exact, on-planet-
confirmed per-POI resource node counts (see backend/poi_resource_import.py
and the sibling spacecraft-memory-research repo's wreck_tracker.py). Same
isolated-temp-DB approach as test_db_galaxy_resources.py."""

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


def test_import_poi_resource_nodes_is_replace_not_ignore(db):
    rows = [("Sys1", "PlanetA", "poi0", "Elmerite", 30, "2026-07-20T00:00:00+00:00")]
    db.import_poi_resource_nodes(rows)
    # A later, better on-planet observation of the same (system, planet,
    # poi_index, resource) should overwrite, not be silently ignored like
    # import_galaxy_resources - see that function's own docstring.
    db.import_poi_resource_nodes(
        [("Sys1", "PlanetA", "poi0", "Elmerite", 34, "2026-07-23T00:00:00+00:00")]
    )
    conn = db_module.sqlite3.connect(db_module.DB_PATH)
    row = conn.execute(
        "SELECT node_count, observed_at FROM poi_resource_nodes"
        " WHERE system_name='Sys1' AND planet='PlanetA' AND poi_index='poi0' AND resource='Elmerite'"
    ).fetchone()
    conn.close()
    assert row == (34, "2026-07-23T00:00:00+00:00")


def test_import_poi_resource_nodes_unique_constraint_keeps_one_row(db):
    db.import_poi_resource_nodes([("Sys1", "PlanetA", "poi0", "Elmerite", 30, "t1")])
    db.import_poi_resource_nodes([("Sys1", "PlanetA", "poi0", "Elmerite", 31, "t2")])
    conn = db_module.sqlite3.connect(db_module.DB_PATH)
    count = conn.execute(
        "SELECT COUNT(*) FROM poi_resource_nodes"
        " WHERE system_name='Sys1' AND planet='PlanetA' AND poi_index='poi0' AND resource='Elmerite'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_get_poi_resource_node_counts_for_resource_scopes_by_resource_name(db):
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Elmerite", 30, "t1"),
        ("Sys1", "PlanetA", "general", "Elmerite", 6, "t1"),
        ("Sys2", "PlanetB", "poi1", "Elmerite", 12, "t2"),
        ("Sys1", "PlanetA", "poi0", "Iron", 99, "t1"),
    ])
    rows = db.get_poi_resource_node_counts_for_resource("Elmerite")
    assert sorted(rows) == sorted([
        ("Sys1", "PlanetA", "poi0", 30, "t1"),
        ("Sys1", "PlanetA", "general", 6, "t1"),
        ("Sys2", "PlanetB", "poi1", 12, "t2"),
    ])


def test_get_poi_resource_node_counts_for_resource_returns_empty_when_unseen(db):
    assert db.get_poi_resource_node_counts_for_resource("Nonexistent") == []
