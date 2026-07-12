"""Tests for backend.api.Api's deposit-tracker methods (Milestone 3).

No pywebview/browser involved - just instantiates Api() directly against
an isolated temp DB/config, the same way tests/test_recipes.py isolates
backend.db. Also asserts every return value survives json.dumps, since
that's the actual boundary crossed to reach the browser - a stray
non-serializable value here would otherwise only surface as a mysterious
frontend failure.
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


def test_add_and_list_deposit(api):
    assert api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "note") is True
    rows = api.get_deposits()
    json.dumps(rows)
    assert len(rows) == 1
    assert rows[0]["planet"] == "PlanetA"


def test_add_requires_planet(api):
    with pytest.raises(ValueError):
        api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "", "")


def test_add_rejects_duplicate(api):
    api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "")
    with pytest.raises(ValueError):
        api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "different")


def test_update_deposit(api):
    api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "")
    row_id = api.get_deposits()[0]["id"]
    assert api.update_deposit(row_id, "Ore", "Iron", "Sec1", "Sys1", "PlanetB", "x")
    dep = api.get_deposit(row_id)
    json.dumps(dep)
    assert dep["planet"] == "PlanetB"


def test_update_rejects_duplicate_with_another_row(api):
    api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "")
    api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetB", "")
    row_id = api.get_deposits()[0]["id"]
    with pytest.raises(ValueError):
        api.update_deposit(row_id, "Ore", "Iron", "Sec1", "Sys1", "PlanetB", "")


def test_delete_deposit(api):
    api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "")
    row_id = api.get_deposits()[0]["id"]
    assert api.delete_deposit(row_id) is True
    assert api.get_deposits() == []


def test_get_deposit_missing_returns_none(api):
    assert api.get_deposit(999) is None


def test_distinct_and_dropdown_values(api):
    api.add_deposit("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "")
    api.add_deposit("Gas", "Helium", "Sec1", "Sys1", "PlanetB", "")
    assert api.get_distinct_values("res_type") == ["Gas", "Ore"]
    assert api.get_dropdown_values("resource", {"res_type": "Ore"}) == ["Iron"]
    assert api.get_dropdown_values("resource", {}) == ["Helium", "Iron"]


def test_collapsed_nodes_round_trip(api):
    assert api.get_collapsed_nodes() == []
    assert api.set_collapsed_nodes(["type|Ore", "loc_sec|Sec1"]) is True
    assert api.get_collapsed_nodes() == ["type|Ore", "loc_sec|Sec1"]


def test_view_mode_round_trip(api):
    assert api.get_view_mode() == "resource"
    assert api.set_view_mode("location") is True
    assert api.get_view_mode() == "location"
