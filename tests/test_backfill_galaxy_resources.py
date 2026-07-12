"""Tests for tools/backfill_galaxy_resources.py's own parsing logic
(poi_surface conversion + load_rows) - not backend.db, which
tests/test_db_galaxy_resources.py already covers directly."""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.backfill_galaxy_resources import load_rows, poi_surface  # noqa: E402


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
