"""Tests for tools/backfill_galaxy_resources.py's own parsing logic
(poi_surface conversion + load_rows) - not backend.db, which
tests/test_db_galaxy_resources.py already covers directly."""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.backfill_galaxy_resources import (  # noqa: E402
    composite_rows_for_planet,
    load_rows,
    load_system_rows,
    poi_surface,
)


def test_poi_surface_matches_known_reference_value():
    # angle_from_distance(0.1231817752122879) == asin(0.1231817752122879)
    # (size < 1, so k=0) - a real poiSizes value pulled from an actual
    # Vexion I dump, cross-checked against the formula by hand.
    size = 0.1231817752122879
    angle = math.asin(size)
    expected = (angle * 2) ** 2 * 5 / (4 * math.pi)
    assert poi_surface(size) == expected


def test_load_rows_computes_poi_area_density_only_for_pure_poi_with_known_sizes(tmp_path):
    dump = [
        {
            "system_name": "Sys1",
            "planet_name": "PlanetA",
            "sector_name": "Sec1",
            "resourceCounts": {"Gray Quartz": 13, "Ferric Stone": 1201},
            "resourceDensities": {"Gray Quartz": 0.103, "Ferric Stone": 9.56},
            "resourcesByPoi": {
                "poi0": ["Gray Quartz"],
                "general": ["Ferric Stone"],
                "poi1": ["Ferric Stone"],
            },
            "poiSizes": {"poi0": 0.1231817752122879},
            "isAsteroid": True,
            "temperature": "PlanetHot2",
            "temperatureName": "Very Hot",
            "attributes": ["PlanetHot2"],
            "attributeNames": ["Very Hot"],
        },
    ]
    dump_path = tmp_path / "galaxy_resources.json"
    dump_path.write_text(json.dumps(dump), encoding="utf-8")

    rows = load_rows(dump_path)
    by_resource = {r[3]: r for r in rows}

    gray_quartz = by_resource["Gray Quartz"]
    assert gray_quartz[6] == "poi0"  # poi_tags
    # built from density (0.103), not raw count (13) - see poi_surface's
    # own docstring for why density is what stays comparable across rows
    expected_density = 0.103 / poi_surface(0.1231817752122879)
    assert gray_quartz[7] == expected_density  # poi_area_density
    assert gray_quartz[8] is True  # isAsteroid passed through as-is
    assert gray_quartz[9:] == ("PlanetHot2", "Very Hot", "PlanetHot2", "Very Hot")

    # Ferric Stone is tied to poi1 AND general - not purely POI-anchored,
    # so poi_area_density must stay None even though it also has a poi tag.
    ferric_stone = by_resource["Ferric Stone"]
    assert ferric_stone[6] == "general,poi1"
    assert ferric_stone[7] is None


def test_load_rows_leaves_poi_area_density_none_when_a_poi_size_is_missing(tmp_path):
    dump = [
        {
            "system_name": "Sys1",
            "planet_name": "PlanetA",
            "sector_name": "Sec1",
            "resourceCounts": {"Gray Quartz": 13},
            "resourceDensities": {"Gray Quartz": 0.103},
            "resourcesByPoi": {"poi0": ["Gray Quartz"], "poi1": ["Gray Quartz"]},
            # poi1's size wasn't captured (e.g. elem_ptr missing in the dump) -
            # can't compute a total surface without it, so this must stay None
            # rather than silently understating the true combined area.
            "poiSizes": {"poi0": 0.12},
        },
    ]
    dump_path = tmp_path / "galaxy_resources.json"
    dump_path.write_text(json.dumps(dump), encoding="utf-8")

    rows = load_rows(dump_path)
    assert rows[0][3] == "Gray Quartz"
    assert rows[0][7] is None


ALL_DEPOSIT_TYPES = {
    "Coal Deposit": "PlanetResource_Deposit",
    "Iron Deposit": "PlanetResource_Deposit",
    "Titanium Deposit": "PlanetResource_Deposit",
    "Vitriol Deposit": "PlanetResource_Deposit",
}


def test_composite_rows_for_planet_joins_names_and_takes_min_across_members():
    deposit_group_sizes = [
        {
            "resGroup": "GD_3_IronTitaniumCarbon",
            "sizes": [
                {"resource": "Coal Deposit", "min": 1, "max": 3},
                {"resource": "Iron Deposit", "min": 1, "max": 3},
                {"resource": "Titanium Deposit", "min": 1, "max": 3},
            ],
        },
    ]
    counts = {"Coal Deposit": 40, "Iron Deposit": 12, "Titanium Deposit": 25}
    densities = {"Coal Deposit": 2.1, "Iron Deposit": 0.5, "Titanium Deposit": 1.3}

    combos = composite_rows_for_planet(deposit_group_sizes, counts, densities, ALL_DEPOSIT_TYPES)

    assert combos == [
        ("Coal Deposit / Iron Deposit / Titanium Deposit", 12, 0.5),
    ]


def test_composite_rows_for_planet_skips_single_member_and_missing_counts():
    deposit_group_sizes = [
        # Only one distinct resource - not a real composite.
        {"resGroup": "GD_1_Coal", "sizes": [{"resource": "Coal Deposit"}]},
        # A member with no live count data on this planet - can't confirm
        # both actually spawned here, so this must not synthesize a row.
        {
            "resGroup": "GD_2_CoalVitriol",
            "sizes": [{"resource": "Coal Deposit"}, {"resource": "Vitriol Deposit"}],
        },
    ]
    counts = {"Coal Deposit": 40}
    densities = {"Coal Deposit": 2.1}

    assert composite_rows_for_planet(deposit_group_sizes, counts, densities, ALL_DEPOSIT_TYPES) == []


def test_composite_rows_for_planet_dedupes_same_member_set():
    deposit_group_sizes = [
        {
            "resGroup": "GD_A",
            "sizes": [{"resource": "Coal Deposit"}, {"resource": "Iron Deposit"}],
        },
        {
            "resGroup": "GD_B",
            "sizes": [{"resource": "Iron Deposit"}, {"resource": "Coal Deposit"}],
        },
    ]
    counts = {"Coal Deposit": 10, "Iron Deposit": 5}
    densities = {"Coal Deposit": 1.0, "Iron Deposit": 0.4}

    combos = composite_rows_for_planet(deposit_group_sizes, counts, densities, ALL_DEPOSIT_TYPES)
    assert len(combos) == 1


def test_composite_rows_for_planet_skips_non_deposit_members():
    # resGroup co-spawn data also covers regular hand-gathered nodes and
    # geysers, not just Deposit-type auto-extractor clusters - grouping
    # those the same way was a real bug (they're a different kind of fact,
    # not "one extractor covers both"), so anything with a non-Deposit
    # member must be skipped entirely.
    deposit_group_sizes = [
        {
            "resGroup": "GD_RegularOnly",
            "sizes": [{"resource": "Cinnabar"}, {"resource": "Malachite"}],
        },
        {
            "resGroup": "GD_Mixed",
            "sizes": [{"resource": "Coal Deposit"}, {"resource": "Mercury Geyser"}],
        },
    ]
    counts = {"Cinnabar": 10, "Malachite": 8, "Coal Deposit": 40, "Mercury Geyser": 3}
    densities = {"Cinnabar": 0.1, "Malachite": 0.2, "Coal Deposit": 2.1, "Mercury Geyser": 0.05}
    node_item_types = {
        "Cinnabar": "PlanetResource_RegularNode",
        "Malachite": "PlanetResource_RegularNode",
        "Coal Deposit": "PlanetResource_Deposit",
        "Mercury Geyser": "PlanetResource_Geyser",
    }

    assert composite_rows_for_planet(deposit_group_sizes, counts, densities, node_item_types) == []


def test_load_rows_appends_composite_row_with_no_poi_tags(tmp_path):
    dump = [
        {
            "system_name": "Sys1",
            "planet_name": "PlanetA",
            "sector_name": "Sec1",
            "resourceCounts": {"Coal Deposit": 40, "Iron Deposit": 12},
            "resourceDensities": {"Coal Deposit": 2.1, "Iron Deposit": 0.5},
            "depositGroupSizes": [
                {
                    "resGroup": "GD_2_CoalIron",
                    "sizes": [{"resource": "Coal Deposit"}, {"resource": "Iron Deposit"}],
                },
            ],
        },
    ]
    dump_path = tmp_path / "galaxy_resources.json"
    dump_path.write_text(json.dumps(dump), encoding="utf-8")

    rows = load_rows(dump_path)
    by_resource = {r[3]: r for r in rows}

    combo = by_resource["Coal Deposit / Iron Deposit"]
    assert combo[4] == 12  # node_count - min across members
    assert combo[5] == 0.5  # density - min across members
    assert combo[6] is None  # poi_tags
    assert combo[7] is None  # poi_area_density


def test_load_system_rows_includes_planets_with_no_resource_counts(tmp_path):
    # A system-only entry (no resourceCounts at all) must still contribute
    # its position/neighbor data - it's a real jump-hop even with no
    # mineral data of its own, unlike load_rows' own resourceCounts-gated
    # skip logic.
    dump = [
        {
            "system_name": "Sys1",
            "planet_name": "PlanetA",
            "systemPosition": {"x": 1.5, "y": -2.0, "z": 3.0},
            "nearSystemNames": ["Sys2", "Sys3"],
        },
    ]
    dump_path = tmp_path / "galaxy_resources.json"
    dump_path.write_text(json.dumps(dump), encoding="utf-8")

    rows = load_system_rows(dump_path)
    assert rows == [("Sys1", 1.5, -2.0, 3.0, "Sys2,Sys3")]


def test_load_system_rows_dedupes_by_system_first_seen_wins(tmp_path):
    dump = [
        {
            "system_name": "Sys1",
            "planet_name": "PlanetA",
            "systemPosition": {"x": 1.0, "y": 1.0, "z": 1.0},
            "nearSystemNames": ["Sys2"],
        },
        {
            "system_name": "Sys1",
            "planet_name": "PlanetB",
            "systemPosition": {"x": 999, "y": 999, "z": 999},
            "nearSystemNames": ["SomethingElse"],
        },
    ]
    dump_path = tmp_path / "galaxy_resources.json"
    dump_path.write_text(json.dumps(dump), encoding="utf-8")

    rows = load_system_rows(dump_path)
    assert rows == [("Sys1", 1.0, 1.0, 1.0, "Sys2")]
