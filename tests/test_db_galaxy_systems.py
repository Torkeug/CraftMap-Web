"""Tests for backend.db's galaxy_systems table (jump-hop distance for the
Galaxy sub-tab's "current system" sort - see tools/backfill_galaxy_resources.py
and backend.db.get_galaxy_hop_distances' own docstrings) - isolated temp DB,
same pattern as tests/test_db_galaxy_resources.py."""

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


def test_import_is_replace_not_ignore(db):
    db.import_galaxy_systems([("Sys1", 1.0, 2.0, 3.0, "Sys2")])
    assert db.get_galaxy_hop_distances("Sys1") == {"Sys1": 0, "Sys2": 1}
    # Sys1 gains a second neighbor in a later import - REPLACE should pick
    # up the fresher, more complete neighbor list, not freeze on the first
    # one ever seen.
    db.import_galaxy_systems([("Sys1", 1.0, 2.0, 3.0, "Sys2,Sys3")])
    assert db.get_galaxy_hop_distances("Sys1") == {"Sys1": 0, "Sys2": 1, "Sys3": 1}


def test_get_galaxy_system_names_sorted(db):
    db.import_galaxy_systems([
        ("Talion", 0, 0, 0, None),
        ("Cisax", 1, 1, 1, None),
    ])
    assert db.get_galaxy_system_names() == ["Cisax", "Talion"]


def test_hop_distances_bfs_across_multiple_hops(db):
    # Sys1 - Sys2 - Sys3 - Sys4, a plain chain
    db.import_galaxy_systems([
        ("Sys1", 0, 0, 0, "Sys2"),
        ("Sys2", 1, 0, 0, "Sys1,Sys3"),
        ("Sys3", 2, 0, 0, "Sys2,Sys4"),
        ("Sys4", 3, 0, 0, "Sys3"),
    ])
    dist = db.get_galaxy_hop_distances("Sys1")
    assert dist == {"Sys1": 0, "Sys2": 1, "Sys3": 2, "Sys4": 3}


def test_hop_distances_treats_edges_as_bidirectional(db):
    # Sys2's own near_system_names lists Sys1, but Sys1's row never lists
    # Sys2 back - the graph must still connect them both ways, since a jump
    # lane works in both directions in-game.
    db.import_galaxy_systems([
        ("Sys1", 0, 0, 0, None),
        ("Sys2", 1, 0, 0, "Sys1"),
    ])
    assert db.get_galaxy_hop_distances("Sys1") == {"Sys1": 0, "Sys2": 1}


def test_hop_distances_unknown_system_returns_empty(db):
    db.import_galaxy_systems([("Sys1", 0, 0, 0, None)])
    assert db.get_galaxy_hop_distances("NoSuchSystem") == {}


def test_hop_distances_does_not_revisit_shorter_paths(db):
    # A small loop: Sys1 connects to both Sys2 and Sys3, which both also
    # connect to Sys4 - Sys4 must resolve to the SHORTEST hop count (2), not
    # get overwritten by whichever branch's queue entry happens to pop last.
    db.import_galaxy_systems([
        ("Sys1", 0, 0, 0, "Sys2,Sys3"),
        ("Sys2", 1, 0, 0, "Sys1,Sys4"),
        ("Sys3", 1, 1, 0, "Sys1,Sys4"),
        ("Sys4", 2, 0, 0, "Sys2,Sys3"),
    ])
    assert db.get_galaxy_hop_distances("Sys1")["Sys4"] == 2
