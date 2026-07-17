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


def _import_galaxy_row(system_name, planet, sector, resource):
    return (
        system_name, planet, sector, resource, 10, 1.0, "poi0", None, 0,
        "PlanetTemperate", "Temperate", None, None,
    )


def test_dropdown_values_include_unlogged_galaxy_data(db):
    db.import_galaxy_resources([_import_galaxy_row("Sys1", "PlanetA", "Sec1", "Iron")])
    assert db.distinct_values_where("resource", {}) == ["Iron"]
    assert db.distinct_values_where("sector", {}) == ["Sec1"]
    assert db.distinct_values_where("system_name", {}) == ["Sys1"]
    assert db.distinct_values_where("planet", {}) == ["PlanetA"]


def test_dropdown_values_merge_and_dedupe_deposits_with_galaxy(db):
    db.import_galaxy_resources([
        _import_galaxy_row("Sys1", "PlanetA", "Sec1", "Iron"),
        _import_galaxy_row("Sys1", "PlanetB", "Sec1", "Gold"),
    ])
    db.insert_row("Ore", "Iron", "Sec1", "Sys1", "PlanetA", "", "2026-01-01 00:00")
    db.insert_row("Ore", "Copper", "SecX", "SysX", "PlanetX", "", "2026-01-01 00:00")
    assert db.distinct_values_where("resource", {}) == ["Copper", "Gold", "Iron"]


def test_dropdown_values_cascade_constraint_only_applies_to_shared_columns(db):
    db.import_galaxy_resources([
        _import_galaxy_row("Sys1", "PlanetA", "Sec1", "Iron"),
        _import_galaxy_row("Sys2", "PlanetB", "Sec2", "Iron"),
    ])
    # galaxy_resources has no res_type column, so a res_type constraint
    # narrows the deposits side only - galaxy suggestions stay unfiltered.
    assert db.distinct_values_where("resource", {"res_type": "Ore"}) == ["Iron"]
    # sector is shared, so it genuinely narrows the galaxy side too.
    assert db.distinct_values_where("system_name", {"sector": "Sec1"}) == ["Sys1"]


def test_dropdown_values_resource_filters_by_deposit_vs_harvestable(db):
    db.import_galaxy_resources([
        _import_galaxy_row("Sys1", "PlanetA", "Sec1", "Iron Deposit"),
        _import_galaxy_row("Sys1", "PlanetA", "Sec1", "Quartz"),
        _import_galaxy_row(
            "Sys1", "PlanetA", "Sec1", "Coal Deposit / Iron Deposit / Titanium Deposit"
        ),
    ])
    assert db.distinct_values_where("resource", {"res_type": "Deposit"}) == [
        "Coal Deposit / Iron Deposit / Titanium Deposit",
        "Iron Deposit",
    ]
    assert db.distinct_values_where("resource", {"res_type": "Resources"}) == ["Quartz"]
    # An unrecognized/blank res_type (e.g. "Ore", "Plant") leaves results
    # unfiltered - DEPOSIT_TYPE_RESOURCE_NAMES has no coverage for those.
    assert db.distinct_values_where("resource", {"res_type": "Ore"}) == [
        "Coal Deposit / Iron Deposit / Titanium Deposit", "Iron Deposit", "Quartz",
    ]
