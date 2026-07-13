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
