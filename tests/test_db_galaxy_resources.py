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
    assert results[3][9:13] == ("PlanetHot1", "Hot", "PlanetHot1", "Hot")  # PlanetB
    assert results[4][9:13] == ("PlanetTemperate", "Temperate", "PlanetWater", "Water presence")  # PlanetE
    # no galaxy_poi_landmarks rows imported in this test - both trailing
    # fields are always empty
    assert all(r[13] == [] and r[14] == [] for r in results)


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


def test_get_galaxy_sources_prefers_exact_poi_area_density_when_fully_covered(db):
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "poi0", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
    ])
    # The estimate said 100 nodes; on-planet tracking found 200 - a real,
    # much richer spot than the coarse dump guessed.
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 200, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert len(results) == 1
    # density_per_node = 1.0/100 = 0.01; exact = 200 * 0.01 / 0.05 = 40.0,
    # not the stale 2.0 estimate.
    assert results[0][7] == pytest.approx(40.0)
    assert results[0][15] is True  # poi_area_density_is_exact
    assert results[0][16] == "poi0"  # poi_area_density_poi_index - the winning POI


def test_get_galaxy_sources_credits_a_single_confirmed_poi_even_with_unconfirmed_siblings(db):
    # poi0 AND poi1 are both declared, but only poi0 has ever been
    # on-planet-confirmed - poi0's own density doesn't depend on poi1's
    # (unknown) stats at all, so this should still be credited rather than
    # falling back to the stale estimate just because poi1 is unconfirmed.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "poi0,poi1", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
        ("Sys1", "PlanetA", "poi1", "Natural Canyon", "BalisePOI2", "day", 0.4, 0.03),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 200, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    # density_per_node = 1.0/100 = 0.01; poi0 alone = 200*0.01/0.05 = 40.0
    assert results[0][7] == pytest.approx(40.0)
    assert results[0][15] is True  # poi_area_density_is_exact
    assert results[0][16] == "poi0"  # poi_area_density_poi_index


def test_get_galaxy_sources_does_not_dilute_a_rich_poi_by_summing_with_a_sparse_sibling(db):
    # poi0 is rich (50 nodes in a small 0.05 area), poi1 is sparse (2 nodes
    # in a much bigger 0.20 area) - an earlier, wrong version of this
    # override BLENDED both together (50+2)/(0.05+0.20) = 208*density_per_node,
    # far below poi0's own individual 1000*density_per_node. The current
    # weighted-decay-sum still evaluates each POI individually and ranks
    # poi0 first, but poi1's own (much smaller) individual density still
    # contributes a decayed sliver on top, rather than being ignored
    # entirely or blended in at full weight.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "poi0,poi1", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
        ("Sys1", "PlanetA", "poi1", "Natural Canyon", "BalisePOI2", "day", 0.4, 0.20),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 50, "2026-07-23T00:00:00+00:00"),
        ("Sys1", "PlanetA", "poi1", "Aquamarine", 2, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    # density_per_node = 1.0/100 = 0.01; poi0 alone = 50*0.01/0.05 = 10.0,
    # poi1 alone = 2*0.01/0.20 = 0.1 - sorted [10.0, 0.1], weighted sum =
    # 10.0 + 0.5*0.1 = 10.05, nowhere near the old (wrong) blended 208-scale
    # figure, and still clearly poi0-led.
    assert results[0][7] == pytest.approx(10.05)
    assert results[0][16] == "poi0"


def test_get_galaxy_sources_credits_multiple_good_pois_over_one_slightly_better_one(db):
    # Planet A has TWO confirmed, genuinely good POIs (40 and 41); Planet B
    # has only ONE, slightly better POI (42). A straight max() would rank
    # Planet B above Planet A - wrong, since having two good options is
    # itself worth something. The weighted decay sum should let Planet A's
    # combined credit (41 + 0.5*40 = 61) win over Planet B's lone 42.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "poi0,poi1", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys2", "PlanetB", "Sec1", "Aquamarine", 100, 1.0, "poi0", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
        ("Sys1", "PlanetA", "poi1", "Natural Canyon", "BalisePOI2", "day", 0.4, 0.05),
        ("Sys2", "PlanetB", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
    ])
    # density_per_node = 1.0/100 = 0.01 for both planets, area = 0.05 for
    # every POI here, so a target individual density D needs count = D*5.
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 200, "2026-07-23T00:00:00+00:00"),  # 40.0
        ("Sys1", "PlanetA", "poi1", "Aquamarine", 205, "2026-07-23T00:00:00+00:00"),  # 41.0
        ("Sys2", "PlanetB", "poi0", "Aquamarine", 210, "2026-07-23T00:00:00+00:00"),  # 42.0
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert [r[1] for r in results] == ["PlanetA", "PlanetB"]
    by_planet = {r[1]: r for r in results}
    assert by_planet["PlanetA"][7] == pytest.approx(41.0 + 0.5 * 40.0)
    assert by_planet["PlanetB"][7] == pytest.approx(42.0)


def test_get_galaxy_sources_computes_exact_poi_area_density_for_mixed_rows(db):
    # poi_tags includes "general" - pure_poi is False, and the ESTIMATE
    # never gets a poi_area_density for a mixed row at all (see
    # tools/backfill_galaxy_resources.py's load_rows) - but once poi0's own
    # sub-portion is exact-confirmed, this row should now get a real
    # poi_area_density computed from JUST that sub-portion (ignoring the
    # unconfirmed "general" share entirely - no confirmation of it is
    # needed), resolving the "RANKING LIMITATION" noted above the final sort.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "general,poi0", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 200, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert results[0][6] is False  # pure_poi - "general" is still present
    # density_per_node = 1.0/100 = 0.01; exact poi0-only = 200*0.01/0.05 = 40.0
    assert results[0][7] == pytest.approx(40.0)


def test_get_galaxy_sources_credits_a_single_confirmed_poi_in_a_mixed_row_with_unconfirmed_siblings(db):
    # Two actual POIs plus "general" - only poi0 is exact-confirmed, poi1
    # isn't - poi0's own density stands alone regardless, same reasoning as
    # the pure-POI equivalent above.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "general,poi0,poi1", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
        ("Sys1", "PlanetA", "poi1", "Natural Canyon", "BalisePOI2", "day", 0.4, 0.03),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 200, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert results[0][7] == pytest.approx(40.0)
    assert results[0][16] == "poi0"


def test_get_galaxy_sources_mixed_row_floors_at_plain_density_when_general_dominates(db):
    # 1000 general nodes + a small confirmed poi0 pocket of only 30 - the
    # POI sub-portion's OWN density (30*density_per_node/0.05) comes out
    # LOWER than the row's plain total density here, since the confirmed
    # POI share is small relative to the still-unconfirmed general share.
    # Taking poi_sub_density unconditionally would WRONGLY rank this row
    # below a planet with less total supply - must floor at plain density
    # instead, crediting the real bonus abundance beyond the POI.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 1030, 1.0, "general,poi0", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 30, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    # density_per_node = 1.0/1030; poi_sub_density = 30*density_per_node/0.05
    # ≈ 0.5825, well below the plain density of 1.0 - the floor should win.
    assert results[0][7] == pytest.approx(1.0)
    # The floor (plain density) won, not the exact POI figure - so this
    # isn't a "newly confirmed" ranking number, and there's no single POI
    # to point the player at.
    assert results[0][15] is False  # poi_area_density_is_exact
    assert results[0][16] is None  # poi_area_density_poi_index


def test_get_galaxy_sources_exact_mixed_row_outranks_equal_density_general_only_row(db):
    # This is the exact "RANKING LIMITATION" scenario: equal plain density,
    # but PlanetA has a real, confirmed walkable-POI concentration and
    # PlanetB is genuinely scattered everywhere - PlanetA should now win.
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "general,poi0", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys2", "PlanetB", "Sec1", "Aquamarine", 100, 1.0, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 30, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert [r[1] for r in results] == ["PlanetA", "PlanetB"]


def test_get_galaxy_sources_leaves_estimate_when_poi_area_unknown(db):
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "poi0", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    # No galaxy_poi_landmarks row at all for poi0 - area unknown, so there's
    # no denominator to convert the exact count into a density with.
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 200, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert results[0][7] == pytest.approx(2.0)  # untouched estimate


def test_get_galaxy_sources_exact_data_can_change_ranking_order(db):
    db.import_galaxy_resources([
        # PlanetA's estimate looks better (3.0 > 2.0)...
        (
            "Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "poi0", 3.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys2", "PlanetB", "Sec1", "Aquamarine", 100, 1.0, "poi0", 2.0, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.10),
    ])
    # ...but on-planet tracking found PlanetA's real spot is much sparser
    # than the coarse estimate guessed (density_per_node=0.01, exact=
    # 10*0.01/0.10=1.0), which should now rank it BELOW PlanetB's untouched
    # 2.0 estimate.
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 10, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    assert [r[1] for r in results] == ["PlanetB", "PlanetA"]


def test_import_galaxy_poi_landmarks_is_replace_not_ignore(db):
    rows = [("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05)]
    db.import_galaxy_poi_landmarks(rows)
    # re-running with fresher lighting data for the same (system, planet,
    # poi_index) should overwrite, not be silently ignored like
    # import_galaxy_resources - see that function's own docstring
    db.import_galaxy_poi_landmarks(
        [("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "night", -0.5, 0.05)]
    )
    conn = db_module.sqlite3.connect(db_module.DB_PATH)
    row = conn.execute(
        "SELECT sun_side, light_value FROM galaxy_poi_landmarks"
        " WHERE system_name='Sys1' AND planet='PlanetA' AND poi_index='poi0'"
    ).fetchone()
    conn.close()
    assert row == ("night", -0.5)


def test_get_galaxy_sources_attaches_matching_poi_landmarks_only(db):
    db.import_galaxy_resources([
        # anchored at poi0 AND poi1 - only poi0 has a landmark
        (
            "Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0,poi1", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
        # poi2 has a landmark too, but nothing on PlanetA is anchored there -
        # must NOT leak into this row's poi_landmarks
        ("Sys1", "PlanetA", "poi2", "High Peak", "BalisePOI1", "night", -0.5, 0.08),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    assert len(results) == 1
    poi_landmarks, poi_sun_states = results[0][13], results[0][14]
    assert [lm["poi_index"] for lm in poi_landmarks] == ["poi0"]
    assert poi_landmarks[0]["name"] == "Meteor Crater"
    assert poi_landmarks[0]["area"] == pytest.approx(0.05)
    assert poi_sun_states == ["day"]


def test_get_galaxy_sources_reports_mixed_sun_states_across_pois(db):
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0,poi1", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    db.import_galaxy_poi_landmarks([
        ("Sys1", "PlanetA", "poi0", "Meteor Crater", "BalisePOI", "day", 0.6, 0.05),
        ("Sys1", "PlanetA", "poi1", "High Peak", "BalisePOI1", "night", -0.5, 0.08),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    assert results[0][14] == ["day", "night"]
