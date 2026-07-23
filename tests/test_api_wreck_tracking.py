"""Tests for backend.api.Api.get_live_wreck_snapshot's import piggybacks -
both wreck_import.import_events_from_file and (newer)
poi_resource_import.import_poi_resource_snapshot are called for their side
effects only and must never surface a failure as if live tracking itself
broke; the next successful poll's import just catches back up. Same
no-pywebview, isolated-temp-DB approach as test_api_galaxy.py."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config as config_module  # noqa: E402
from backend import db as db_module  # noqa: E402
from backend import poi_resource_import, wreck_import  # noqa: E402
from backend.api import Api  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    db_module.init_db()
    api = Api()
    # A script path just needs to look plausible enough to get past
    # get_live_wreck_snapshot's own "not configured yet" early return -
    # the script itself is never actually launched by this method.
    script_path = tmp_path / "wreck_tracker.py"
    script_path.write_text("", encoding="utf-8")
    api.set_wreck_tracker_settings(str(script_path))
    return api


def test_get_live_wreck_snapshot_returns_none_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    db_module.init_db()
    assert Api().get_live_wreck_snapshot() is None


def test_get_live_wreck_snapshot_swallows_poi_resource_import_failure(api, monkeypatch):
    def boom(_path=None):
        raise RuntimeError("simulated corrupt snapshot")

    monkeypatch.setattr(poi_resource_import, "import_poi_resource_snapshot", boom)
    # No current_planet_wrecks.json exists in this temp dir either, so the
    # method's own final read_live_snapshot call returns None too - the
    # point of this test is just that it does so WITHOUT raising.
    assert api.get_live_wreck_snapshot() is None


def test_get_live_wreck_snapshot_swallows_wreck_events_import_failure(api, monkeypatch):
    def boom(_path=None):
        raise RuntimeError("simulated malformed events file")

    monkeypatch.setattr(wreck_import, "import_events_from_file", boom)
    assert api.get_live_wreck_snapshot() is None
