"""Tests for backend.poi_resource_import - reads the sibling
spacecraft-memory-research repo's wreck_tracker.py per-POI resource-count
snapshot file and upserts it into resources.db's poi_resource_nodes table.
Whole-file read every call (no cursor, unlike wreck_import.py) - see that
module's own docstring for why."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db as db_module  # noqa: E402
from backend import poi_resource_import  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    return db_module


def _write_snapshot(path, **overrides):
    snapshot = {
        "observed_at": "2026-07-23T00:00:00+00:00",
        "system_name": "Sys1",
        "planet_name": "PlanetA",
        "poi_resource_counts": [
            {"poi_index": "poi0", "resource_id": "GElmerite", "resource_name": "Elmerite", "node_count": 30},
            {"poi_index": "general", "resource_id": "GElmerite", "resource_name": "Elmerite", "node_count": 6},
        ],
    }
    snapshot.update(overrides)
    path.write_text(json.dumps(snapshot), encoding="utf-8")


def test_import_poi_resource_snapshot_reads_and_upserts(db, tmp_path):
    path = tmp_path / "poi_resource_counts.json"
    _write_snapshot(path)
    result = poi_resource_import.import_poi_resource_snapshot(path)
    assert result == ("Sys1", "PlanetA", 2)
    rows = db.get_poi_resource_node_counts_for_resource("Elmerite")
    assert sorted(rows) == sorted([
        ("Sys1", "PlanetA", "poi0", 30, "2026-07-23T00:00:00+00:00"),
        ("Sys1", "PlanetA", "general", 6, "2026-07-23T00:00:00+00:00"),
    ])


def test_import_poi_resource_snapshot_missing_file_returns_none(db, tmp_path):
    assert poi_resource_import.import_poi_resource_snapshot(tmp_path / "nope.json") is None


def test_import_poi_resource_snapshot_corrupt_file_returns_none(db, tmp_path):
    path = tmp_path / "poi_resource_counts.json"
    path.write_text("not json", encoding="utf-8")
    assert poi_resource_import.import_poi_resource_snapshot(path) is None


def test_import_poi_resource_snapshot_no_planet_returns_none(db, tmp_path):
    # system_name/planet_name resolve to null when the poller's tracked
    # player is mid-travel/loading - matches wreck_import._parse_lines'
    # own handling of the same transient failure mode.
    path = tmp_path / "poi_resource_counts.json"
    _write_snapshot(path, system_name=None, planet_name=None)
    assert poi_resource_import.import_poi_resource_snapshot(path) is None


def test_import_poi_resource_snapshot_upserts_on_repeat_import(db, tmp_path):
    path = tmp_path / "poi_resource_counts.json"
    _write_snapshot(path)
    poi_resource_import.import_poi_resource_snapshot(path)
    _write_snapshot(path, observed_at="2026-07-24T00:00:00+00:00", poi_resource_counts=[
        {"poi_index": "poi0", "resource_id": "GElmerite", "resource_name": "Elmerite", "node_count": 34},
    ])
    poi_resource_import.import_poi_resource_snapshot(path)
    rows = db.get_poi_resource_node_counts_for_resource("Elmerite")
    # poi0 updated to the fresher count; the earlier "general" row (absent
    # from this second snapshot) is untouched, not deleted - a snapshot only
    # ever REPLACEs the (poi_index, resource) pairs it actually lists.
    assert sorted(rows) == sorted([
        ("Sys1", "PlanetA", "poi0", 34, "2026-07-24T00:00:00+00:00"),
        ("Sys1", "PlanetA", "general", 6, "2026-07-23T00:00:00+00:00"),
    ])
