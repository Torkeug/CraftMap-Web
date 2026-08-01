"""Tests for backend.db's galaxy_resources table - no Api layer yet (no
frontend consumes this table), so these exercise backend.db directly against
an isolated temp DB, the same way tests/test_api.py isolates it for Api.

get_galaxy_sources_for_resource's returned tuple order (see its own
docstring): (system_name, planet, sector, node_count, density, poi_tags,
pure_poi, is_asteroid, temperature, temperature_name, attributes,
attribute_names, poi_landmarks, poi_sun_states, poi_value, general_value,
effective_score, poi_value_is_exact, poi_value_poi_index)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db as db_module  # noqa: E402

# Index shorthand matching get_galaxy_sources_for_resource's return tuple.
PLANET = 1
NODE_COUNT = 3
DENSITY = 4
POI_TAGS = 5
PURE_POI = 6
IS_ASTEROID = 7
TEMPERATURE = 8
TEMPERATURE_NAME = 9
ATTRIBUTES = 10
ATTRIBUTE_NAMES = 11
POI_LANDMARKS = 12
POI_SUN_STATES = 13
POI_VALUE = 14
GENERAL_VALUE = 15
EFFECTIVE_SCORE = 16
POI_VALUE_IS_EXACT = 17
POI_VALUE_POI_INDEX = 18


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


def test_get_galaxy_sources_pure_single_poi_ranks_by_raw_node_count(db):
    # A single-POI pure row's poi_value is just its own node_count - no
    # on-planet confirmation needed, since resourceCounts is already an
    # exact, live count straight from the dump (see get_galaxy_sources_for_
    # resource's own docstring). No area, no confirmation - the bigger
    # count simply wins.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Iron", 90, 0.4, "poi0", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys2", "PlanetB", "Sec1", "Iron", 20, 4.7, "poi0", None, 1,
         "PlanetHot1", "Hot", None, None),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    assert [r[PLANET] for r in results] == ["PlanetA", "PlanetB"]
    assert results[0][POI_VALUE] == pytest.approx(90)
    assert results[1][POI_VALUE] == pytest.approx(20)
    assert all(r[GENERAL_VALUE] == 0 for r in results)
    # Nothing was confirmed via poi_resource_nodes - poi_value_is_exact only
    # flags an actual on-planet visit, not "the number is trustworthy" (it
    # already is, here, from the dump alone).
    assert all(r[POI_VALUE_IS_EXACT] is False for r in results)
    assert results[0][IS_ASTEROID] is False
    assert results[1][IS_ASTEROID] is True


def test_get_galaxy_sources_general_rows_still_rank_by_density(db):
    # Unrelated to node_count - a small, dense planet still beats a huge,
    # sparse one, same as always for plain scattered gathering.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Graphite", 10, 5.0, "general", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys2", "PlanetB", "Sec1", "Graphite", 1000, 0.1, "general", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    results = db.get_galaxy_sources_for_resource("Graphite")
    assert [r[PLANET] for r in results] == ["PlanetA", "PlanetB"]
    assert all(r[POI_VALUE] == 0 for r in results)


def test_get_galaxy_sources_confirmed_mixed_poi_credit_is_scale_independent(db):
    # The scenario that motivated this whole design: a mixed row's plain
    # `density` scales with the planet's own physical size (see
    # dump_planet_resources.py's compute_display_density), so a tiny-scale
    # planet with a genuinely huge confirmed POI stash can show a trivial
    # density - poi_value must still credit that stash directly via its raw
    # confirmed count, immune to the scale penalty, so this row isn't
    # buried behind an unrelated general-only planet.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Aquamarine", 1000, 0.01, "general,poi0", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys2", "PlanetB", "Sec1", "Aquamarine", 50, 0.5, "general", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Aquamarine", 900, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    by_planet = {r[PLANET]: r for r in results}
    assert by_planet["PlanetA"][POI_VALUE] == pytest.approx(900)
    # general_value backs out the confirmed 900 from the 1000 total:
    # density_per_node = 0.01/1000 = 0.00001; (1000-900)*0.00001 = 0.001
    assert by_planet["PlanetA"][GENERAL_VALUE] == pytest.approx(0.001)
    assert by_planet["PlanetA"][POI_VALUE_IS_EXACT] is True
    assert by_planet["PlanetA"][POI_VALUE_POI_INDEX] == "poi0"
    # PlanetA's poi_ratio (900/900 * 1.0 weight, only one nonzero poi_value
    # sample) plus its tiny general_ratio (0.001/0.5 * ~0.998 discrimination
    # weight, see _discrimination_weight) still edges out PlanetB's
    # general_ratio-only ~0.998.
    assert [r[PLANET] for r in results] == ["PlanetA", "PlanetB"]


def test_get_galaxy_sources_downweights_general_ratio_when_general_population_barely_discriminates(db):
    # PlanetB (general-only, general_value=0.5) and PlanetC (pure POI,
    # poi_value=30) both sit at a similar RATIO-TO-MAX in their own
    # dimension (0.5/0.6=0.833 vs 30/40=0.75) - a naive ratio-to-max sum
    # would rank PlanetB above PlanetC. But PlanetB's general_value is one
    # of only two ever seen for this resource, 0.5 and 0.6 - barely
    # different from the best - while PlanetC's poi_value (30) is
    # meaningfully smaller than the best confirmed POI haul (40, on
    # PlanetA) - a population that actually spans a wide range. Once each
    # ratio is scaled by how much its OWN population discriminates
    # (_discrimination_weight), PlanetC's poi contribution should hold up
    # far better than PlanetB's general contribution, flipping the order.
    db.import_galaxy_resources([
        # mixed: confirmed poi0=40 out of node_count=100 -> general leftover
        # 60 * density_per_node(1.0/100=0.01) = general_value 0.6
        ("Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "general,poi0", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys2", "PlanetB", "Sec1", "Iron", 100, 0.5, "general", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys3", "PlanetC", "Sec1", "Iron", 30, 1.0, "poi0", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Iron", 40, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    by_planet = {r[PLANET]: r for r in results}
    assert by_planet["PlanetA"][GENERAL_VALUE] == pytest.approx(0.6)
    assert by_planet["PlanetA"][POI_VALUE] == pytest.approx(40)
    # general_weight = (0.6-0.5)/0.6 ~= 0.1667; poi_weight = (40-30)/40 = 0.25
    assert by_planet["PlanetB"][EFFECTIVE_SCORE] == pytest.approx((0.5 / 0.6) * (0.1 / 0.6))
    assert by_planet["PlanetC"][EFFECTIVE_SCORE] == pytest.approx((30 / 40) * 0.25)
    assert [r[PLANET] for r in results] == ["PlanetA", "PlanetC", "PlanetB"]


def test_get_galaxy_sources_discrimination_weight_defaults_to_full_with_one_sample(db):
    # Only one row has any general/poi presence at all for this resource -
    # nothing to compare it against, so _discrimination_weight must NOT
    # suppress it (defaults to full weight 1.0), unlike the 2+-sample case
    # above.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "general,poi0", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Iron", 40, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    # poi_ratio = 40/40 * 1.0 = 1.0; general_ratio = 0.6/0.6 * 1.0 = 1.0
    assert results[0][EFFECTIVE_SCORE] == pytest.approx(2.0)


def test_get_galaxy_sources_unconfirmed_mixed_row_falls_back_to_plain_density(db):
    # No poi_resource_nodes data at all - the dump never splits a mixed
    # row's total between general and POI, so this is the known,
    # conservative limitation: an unconfirmed mixed row ties with a
    # general-only row of equal density, exactly as if it weren't
    # POI-anchored at all, until someone actually visits and confirms it.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Aquamarine", 100, 1.0, "general,poi0", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys2", "PlanetB", "Sec1", "Aquamarine", 100, 1.0, "general", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    results = db.get_galaxy_sources_for_resource("Aquamarine")
    by_planet = {r[PLANET]: r for r in results}
    assert by_planet["PlanetA"][POI_VALUE] == 0
    assert by_planet["PlanetA"][GENERAL_VALUE] == pytest.approx(1.0)
    assert by_planet["PlanetA"][EFFECTIVE_SCORE] == pytest.approx(by_planet["PlanetB"][EFFECTIVE_SCORE])


def test_get_galaxy_sources_pure_multi_poi_unconfirmed_ranks_on_full_total(db):
    # No poi_resource_nodes data for either declared POI - the row's own
    # total node_count (exact from the dump) becomes one synthetic
    # "remainder" slot at rank 0 (full decay weight), so an entirely
    # unconfirmed multi-POI row still ranks on its full honest total rather
    # than being zeroed out for lack of a per-POI split.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0,poi1", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    assert results[0][POI_VALUE] == pytest.approx(100)
    assert results[0][POI_VALUE_IS_EXACT] is False
    assert results[0][POI_VALUE_POI_INDEX] is None


def test_get_galaxy_sources_pure_multi_poi_unconfirmed_remainder_can_still_dominate(db):
    # poi0 is confirmed at only 10; the other 90 is still unconfirmed. That
    # 90 is folded in as a synthetic slot and, being the bigger chunk, ranks
    # FIRST (full weight) - poi_value_poi_index stays None since the top
    # slot isn't an actual confirmed tag, even though poi_value_is_exact is
    # True (SOME data was confirmed) - there's nothing real to point the
    # player at yet.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0,poi1", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Iron", 10, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    # ranked = [90 (remainder), 10 (poi0)] -> 90 + 0.5*10 = 95
    assert results[0][POI_VALUE] == pytest.approx(95)
    assert results[0][POI_VALUE_IS_EXACT] is True
    assert results[0][POI_VALUE_POI_INDEX] is None


def test_get_galaxy_sources_pure_multi_poi_confirmed_remainder_can_be_pointed_at(db):
    # Same shape, but this time the CONFIRMED poi0 is the dominant chunk
    # (90 of 100) - it ranks first, so poi_value_poi_index correctly names
    # it as the real spot worth visiting.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0,poi1", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Iron", 90, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    # ranked = [90 (poi0), 10 (remainder)] -> 90 + 0.5*10 = 95
    assert results[0][POI_VALUE] == pytest.approx(95)
    assert results[0][POI_VALUE_IS_EXACT] is True
    assert results[0][POI_VALUE_POI_INDEX] == "poi0"


def test_get_galaxy_sources_rewards_concentration_over_an_even_spread(db):
    # Same total (100) across 4 fully-confirmed POIs on each planet, but
    # PlanetA's value concentrates in one dominant POI while PlanetB's is
    # split evenly across all 4 - PlanetA should rank higher, since
    # reaching PlanetB's total costs real extra inter-POI travel on the
    # same planet, not nothing.
    db.import_galaxy_resources([
        ("Sys1", "PlanetA", "Sec1", "Iron", 100, 1.0, "poi0,poi1,poi2,poi3", None, 0,
         "PlanetTemperate", "Temperate", None, None),
        ("Sys2", "PlanetB", "Sec1", "Iron", 100, 1.0, "poi0,poi1,poi2,poi3", None, 0,
         "PlanetTemperate", "Temperate", None, None),
    ])
    db.import_poi_resource_nodes([
        ("Sys1", "PlanetA", "poi0", "Iron", 70, "2026-07-23T00:00:00+00:00"),
        ("Sys1", "PlanetA", "poi1", "Iron", 10, "2026-07-23T00:00:00+00:00"),
        ("Sys1", "PlanetA", "poi2", "Iron", 10, "2026-07-23T00:00:00+00:00"),
        ("Sys1", "PlanetA", "poi3", "Iron", 10, "2026-07-23T00:00:00+00:00"),
        ("Sys2", "PlanetB", "poi0", "Iron", 25, "2026-07-23T00:00:00+00:00"),
        ("Sys2", "PlanetB", "poi1", "Iron", 25, "2026-07-23T00:00:00+00:00"),
        ("Sys2", "PlanetB", "poi2", "Iron", 25, "2026-07-23T00:00:00+00:00"),
        ("Sys2", "PlanetB", "poi3", "Iron", 25, "2026-07-23T00:00:00+00:00"),
    ])
    results = db.get_galaxy_sources_for_resource("Iron")
    assert [r[PLANET] for r in results] == ["PlanetA", "PlanetB"]
    by_planet = {r[PLANET]: r for r in results}
    assert by_planet["PlanetA"][POI_VALUE] == pytest.approx(70 + 0.5 * 10 + 0.25 * 10 + 0.125 * 10)
    assert by_planet["PlanetB"][POI_VALUE] == pytest.approx(25 * (1 + 0.5 + 0.25 + 0.125))


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
    assert [r[PLANET] for r in with_asteroids] == ["AST-1A2", "PlanetA"]

    without_asteroids = db.get_galaxy_sources_for_resource("Iron", include_asteroids=False)
    assert [r[PLANET] for r in without_asteroids] == ["PlanetA"]


def test_get_galaxy_sources_for_missing_resource_returns_empty(db):
    assert db.get_galaxy_sources_for_resource("Nonexistent") == []


def test_resource_family_resolves_symmetrically():
    assert db_module._resource_family("Coal Clump") == db_module._resource_family("Big Coal Clump")
    assert set(db_module._resource_family("Coal Clump")) == {"Coal Clump", "Big Coal Clump"}
    # a resource with no known size variant is its own singleton family
    assert db_module._resource_family("Iron") == ["Iron"]


def test_get_galaxy_sources_combines_size_variants_on_the_same_planet(db):
    db.import_galaxy_resources([
        # same planet, both variants purely tied to the SAME poi0 - node_count/
        # density sum, and since it's still a single-tag pure row, poi_value
        # is simply the combined total.
        (
            "Sys1", "PlanetA", "Sec1", "Coal Clump", 100, 1.0, "poi0", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        (
            "Sys1", "PlanetA", "Sec1", "Big Coal Clump", 50, 0.5, "poi0", None, 0,
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
        by_planet = {r[PLANET]: r for r in results}
        assert len(results) == 2
        combined = by_planet["PlanetA"]
        assert combined[NODE_COUNT] == 150  # node_count summed
        assert combined[DENSITY] == pytest.approx(1.5)  # density summed
        assert combined[POI_TAGS] == "poi0"  # poi_tags union (identical on both rows)
        assert combined[PURE_POI] is True
        assert combined[POI_VALUE] == pytest.approx(150)
        assert by_planet["PlanetB"][NODE_COUNT] == 200  # untouched single-variant planet


def test_get_galaxy_sources_combines_differing_poi_tags_into_a_mixed_row(db):
    db.import_galaxy_resources([
        (
            "Sys1", "PlanetA", "Sec1", "Coal Clump", 100, 1.0, "poi0", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
        # same planet, but this variant is scattered ("general") rather than
        # tied to poi0 - the combined row is now genuinely mixed
        (
            "Sys1", "PlanetA", "Sec1", "Big Coal Clump", 50, 0.5, "general", None, 0,
            "PlanetTemperate", "Temperate", None, None,
        ),
    ])
    results = db.get_galaxy_sources_for_resource("Coal Clump")
    assert len(results) == 1
    combined = results[0]
    assert combined[NODE_COUNT] == 150
    assert combined[POI_TAGS] == "general,poi0"  # union of both rows' tags
    assert combined[PURE_POI] is False  # "general" is present
    # unconfirmed mixed row - conservative fallback, no poi credit yet
    assert combined[POI_VALUE] == 0
    assert combined[GENERAL_VALUE] == pytest.approx(1.5)


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
    poi_landmarks, poi_sun_states = results[0][POI_LANDMARKS], results[0][POI_SUN_STATES]
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
    assert results[0][POI_SUN_STATES] == ["day", "night"]


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
