"""Tests for recipe tree resolution (backend.resolver.resolve_recipe_tree).

This is the most complex pure-logic piece of the app - recursive crafting
breakdown with ceil-based craft counts, cycle detection, and alternate-recipe
handling - and the part most likely to silently regress, since a wrong tree
doesn't crash, it just quietly shows the wrong numbers.

Ported from craftmap/tests/test_recipes.py - test bodies are unchanged; only
the fixture changed, since resolve_recipe_tree and the DB functions it uses
now live in two separate modules (backend.db, backend.resolver) instead of
one combined `overlay` module. The fixture merges both modules' public
names into one namespace so every `db.foo(...)` call below still resolves,
whichever module `foo` actually lives in.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db as db_module, resolver  # noqa: E402

DEFAULT_STATIONS = [("Station", None, None)]


@pytest.fixture
def db(tmp_path, monkeypatch):
    test_db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)
    monkeypatch.setattr(resolver, "DB_PATH", test_db_path)
    db_module.init_db()
    return types.SimpleNamespace(**{**vars(db_module), **vars(resolver)})


def test_raw_ingredient_has_no_children(db):
    tree = resolver.resolve_recipe_tree("Iron Ore", qty_needed=5)
    assert tree["name"] == "Iron Ore"
    assert tree["qty"] == 5
    assert tree["is_recipe"] is False
    assert tree["children"] == []
    assert tree["alts"] == []


def test_single_level_recipe_breaks_down_ingredients(db):
    db.save_recipe(
        None,
        "Iron Bar",
        outputs=[("Iron Bar", 2)],
        ingredients=[("Iron Ore", 3)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Iron Bar", qty_needed=4)

    assert tree["is_recipe"] is True
    assert tree["output_qty"] == 2
    assert len(tree["children"]) == 1
    ore = tree["children"][0]
    assert ore["name"] == "Iron Ore"
    # 4 needed / 2 per craft = 2 crafts -> 2 * 3 ore per craft = 6 ore
    assert ore["qty"] == 6
    assert ore["is_recipe"] is False


def test_craft_count_rounds_up_with_ceil(db):
    # output qty=3 but only 4 needed -> ceil(4/3) = 2 crafts, not 1 or 1.33
    db.save_recipe(
        None,
        "Plate",
        outputs=[("Plate", 3)],
        ingredients=[("Iron Bar", 1)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Plate", qty_needed=4)

    iron_bar = tree["children"][0]
    assert iron_bar["qty"] == 2  # 2 crafts * 1 iron bar each


def test_max_depth_truncates_and_flags_it(db):
    db.save_recipe(
        None,
        "Iron Bar",
        outputs=[("Iron Bar", 1)],
        ingredients=[("Iron Ore", 2)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Gear",
        outputs=[("Gear", 1)],
        ingredients=[("Iron Bar", 3)],
        stations=DEFAULT_STATIONS,
    )

    # depth 0 = Gear itself, depth 1 = Iron Bar - Iron Bar's own children
    # (Iron Ore) get cut off at max_depth=1.
    tree = db.resolve_recipe_tree("Gear", qty_needed=1, max_depth=1)

    assert tree["truncated"] is False
    iron_bar = tree["children"][0]
    assert iron_bar["name"] == "Iron Bar"
    assert iron_bar["is_recipe"] is True
    assert iron_bar["truncated"] is True
    assert iron_bar["children"] == []
    # Truncation shouldn't affect this node's own metadata/qty scaling.
    assert iron_bar["qty"] == 3

    # Resuming from the truncated node with a fresh top-level call (as
    # get_recipe_subtree does) reproduces its real children.
    resumed = db.resolve_recipe_tree(
        "Iron Bar", qty_needed=iron_bar["qty"], _visited=frozenset({"Gear"})
    )
    assert resumed["truncated"] is False
    assert resumed["children"][0]["name"] == "Iron Ore"
    assert resumed["children"][0]["qty"] == 6


def test_max_depth_none_matches_unbounded_resolve(db):
    db.save_recipe(
        None,
        "Iron Bar",
        outputs=[("Iron Bar", 1)],
        ingredients=[("Iron Ore", 2)],
        stations=DEFAULT_STATIONS,
    )
    unbounded = db.resolve_recipe_tree("Iron Bar", qty_needed=1)
    explicit_none = db.resolve_recipe_tree("Iron Bar", qty_needed=1, max_depth=None)
    assert unbounded == explicit_none


def test_multi_level_nesting(db):
    db.save_recipe(
        None,
        "Iron Bar",
        outputs=[("Iron Bar", 1)],
        ingredients=[("Iron Ore", 2)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Gear",
        outputs=[("Gear", 1)],
        ingredients=[("Iron Bar", 3)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Gear", qty_needed=1)

    iron_bar = tree["children"][0]
    assert iron_bar["is_recipe"] is True
    assert iron_bar["qty"] == 3
    ore = iron_bar["children"][0]
    assert ore["name"] == "Iron Ore"
    assert ore["qty"] == 6  # 3 iron bars * 2 ore each


def test_cycle_is_broken_not_infinite(db):
    # A needs B, B needs A - resolving A must terminate and treat the
    # second occurrence of A as a raw (non-recipe) leaf.
    db.save_recipe(
        None, "A", outputs=[("A", 1)], ingredients=[("B", 1)], stations=DEFAULT_STATIONS
    )
    db.save_recipe(
        None, "B", outputs=[("B", 1)], ingredients=[("A", 1)], stations=DEFAULT_STATIONS
    )

    tree = db.resolve_recipe_tree("A", qty_needed=1)

    assert tree["is_recipe"] is True
    b_node = tree["children"][0]
    assert b_node["is_recipe"] is True
    a_again = b_node["children"][0]
    assert a_again["name"] == "A"
    assert a_again["is_recipe"] is False  # cycle broken: treated as raw here


def test_alternate_recipes_are_listed(db):
    db.save_recipe(
        None,
        "Fuel",
        outputs=[("Energy", 1)],
        ingredients=[("Coal", 2)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Battery",
        outputs=[("Energy", 1)],
        ingredients=[("Lithium", 1)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Energy", qty_needed=1)

    # First-created recipe (by id) is the default. No "Raw Material" option
    # here - Energy isn't in the curated raw-material list (see
    # test_raw_material_option_offered_only_for_curated_items), so the
    # picker only ever offers other real recipes for it.
    assert tree["recipe_name"] == "Fuel"
    assert len(tree["alts"]) == 1
    assert tree["alts"][0]["recipe_name"] == "Battery"


def test_alt_pref_overrides_default_recipe(db):
    db.save_recipe(
        None,
        "Fuel",
        outputs=[("Energy", 1)],
        ingredients=[("Coal", 2)],
        stations=DEFAULT_STATIONS,
    )
    battery_id = db.save_recipe(
        None,
        "Battery",
        outputs=[("Energy", 1)],
        ingredients=[("Lithium", 1)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Energy", qty_needed=1, _alt_prefs={"Energy": battery_id})

    assert tree["recipe_name"] == "Battery"
    assert tree["children"][0]["name"] == "Lithium"


def test_recipe_station_and_time_returned_in_tree(db):
    db.save_recipe(
        None,
        "Steel Ingot",
        outputs=[("Steel Ingot", 3)],
        ingredients=[("Iron Ingot", 4)],
        stations=[("Smelter", 180.0, 5.0)],
    )

    tree = db.resolve_recipe_tree("Steel Ingot", qty_needed=3)

    assert tree["station"] == "Smelter"
    assert tree["auto_craft_seconds"] == 180.0
    assert tree["manual_craft_seconds"] == 5.0


def test_recipe_can_have_multiple_stations(db):
    rid = db.save_recipe(
        None,
        "Steel Ingot",
        outputs=[("Steel Ingot", 3)],
        ingredients=[("Iron Ingot", 4)],
        stations=[
            ("Smelter", 180.0, 5.0),
            ("Micro-Furnace", 10.0, 5.0),
            ("Ship (on-board)", None, 15.0),
        ],
    )

    stations = db.get_recipe_stations(rid)

    assert stations == [
        ("Smelter", 180.0, 5.0),
        ("Micro-Furnace", 10.0, 5.0),
        ("Ship (on-board)", None, 15.0),
    ]
    # The primary (first) station is mirrored onto the recipe's own row.
    assert db.get_recipe_meta(rid) == ("Smelter", 180.0, 5.0)


def test_get_recipe_station_times_looks_up_by_name(db):
    rid = db.save_recipe(
        None,
        "Steel Ingot",
        outputs=[("Steel Ingot", 3)],
        ingredients=[("Iron Ingot", 4)],
        stations=[("Smelter", 180.0, 5.0), ("Micro-Furnace", 10.0, 5.0)],
    )

    assert db.get_recipe_station_times(rid, "Micro-Furnace") == (10.0, 5.0)
    assert db.get_recipe_station_times(rid, "Nonexistent Station") is None


def test_multi_output_recipe_returns_scaled_byproducts(db):
    # Smelting Aquamarine yields both Silicium Ingot and Aluminium Ingot.
    db.save_recipe(
        None,
        "Aluminium Ingot Aquamarine",
        outputs=[("Silicium Ingot", 2), ("Aluminium Ingot", 1)],
        ingredients=[("Aquamarine", 3)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Aluminium Ingot", qty_needed=2)

    # ceil(2 / 1) = 2 crafts -> 2 * 2 = 4 Silicium Ingot as a byproduct.
    assert tree["output_qty"] == 1
    assert tree["byproducts"] == [{"name": "Silicium Ingot", "qty": 4.0}]


def test_alts_grouped_by_output_item_not_recipe_id(db):
    # A single multi-output recipe must show up as an alt under BOTH of its
    # outputs' buckets, each scaled to that output's own qty - not just its
    # "primary" output. The two single-output recipes are saved first so they
    # win as the default (first-by-id) recipe for each item.
    db.save_recipe(
        None,
        "Steel",
        outputs=[("Steel Ingot", 3)],
        ingredients=[("Iron Ingot", 4)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Copper",
        outputs=[("Copper Ingot", 1)],
        ingredients=[("Copper Ore", 2)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Recycle Steel Hull",
        outputs=[("Steel Ingot", 2), ("Copper Ingot", 1)],
        ingredients=[("Wrecked Hull", 4)],
        stations=DEFAULT_STATIONS,
    )

    steel_tree = db.resolve_recipe_tree("Steel Ingot", qty_needed=3)
    copper_tree = db.resolve_recipe_tree("Copper Ingot", qty_needed=1)

    steel_alt_names = {alt["recipe_name"] for alt in steel_tree["alts"]}
    copper_alt_names = {alt["recipe_name"] for alt in copper_tree["alts"]}
    assert "Recycle Steel Hull" in steel_alt_names
    assert "Recycle Steel Hull" in copper_alt_names

    steel_alt = next(
        alt for alt in steel_tree["alts"] if alt["recipe_name"] == "Recycle Steel Hull"
    )
    assert steel_alt["output_qty"] == 2
    assert steel_alt["byproducts"] == [{"name": "Copper Ingot", "qty": 2.0}]


def test_get_all_output_names_includes_secondary_outputs(db):
    db.save_recipe(
        None,
        "Aluminium Ingot Aquamarine",
        outputs=[("Silicium Ingot", 2), ("Aluminium Ingot", 1)],
        ingredients=[("Aquamarine", 3)],
        stations=DEFAULT_STATIONS,
    )

    names = db.get_all_output_names()

    assert "Silicium Ingot" in names
    assert "Aluminium Ingot" in names


def test_station_pref_overrides_station_and_mode(db):
    db.save_recipe(
        None,
        "Steel Ingot",
        outputs=[("Steel Ingot", 3)],
        ingredients=[("Iron Ingot", 4)],
        stations=[("Smelter", 180.0, 5.0), ("Micro-Furnace", 10.0, 5.0)],
    )

    db.set_station_pref("Steel Ingot", "Micro-Furnace", "manual")
    tree = db.resolve_recipe_tree(
        "Steel Ingot", qty_needed=3, _station_prefs=db.get_station_prefs()
    )

    assert tree["station"] == "Micro-Furnace"
    assert tree["craft_mode"] == "manual"
    assert tree["manual_craft_seconds"] == 5.0


def test_station_prefs_round_trip(db):
    db.set_station_pref("Iron Ingot", "Smelter", "auto")

    assert db.get_station_prefs() == {"Iron Ingot": ("Smelter", "auto")}

    db.clear_station_pref("Iron Ingot")

    assert db.get_station_prefs() == {}


def test_raw_material_names_round_trip(db):
    assert db.get_raw_material_names() == set()

    db.add_raw_material("Quartz")
    db.add_raw_material("Hematite")
    assert db.get_raw_material_names() == {"Quartz", "Hematite"}

    db.add_raw_material("Quartz")  # idempotent, no duplicate/error
    assert db.get_raw_material_names() == {"Quartz", "Hematite"}

    db.remove_raw_material("Quartz")
    assert db.get_raw_material_names() == {"Hematite"}


def test_craft_mode_defaults_to_manual_when_no_auto_time(db):
    # A manual-only station (e.g. "Ship (on-board)") has no auto value at
    # all - the default mode must fall back to manual rather than pointing
    # at a nonexistent auto time.
    db.save_recipe(
        None,
        "Field Repair Kit",
        outputs=[("Field Repair Kit", 1)],
        ingredients=[("Scrap Metal", 2)],
        stations=[("Ship (on-board)", None, 15.0)],
    )

    tree = db.resolve_recipe_tree("Field Repair Kit", qty_needed=1)

    assert tree["craft_mode"] == "manual"
    assert tree["manual_craft_seconds"] == 15.0


def test_node_own_time_scales_by_crafts_needed(db):
    # Regression test for the bug where the breakdown tree showed a single
    # craft's time (e.g. "24m") regardless of how many crafts were actually
    # needed (e.g. 4x → should reflect 4 separate craft cycles).
    db.save_recipe(
        None,
        "Titanium Part Casing",
        outputs=[("Titanium Part Casing", 1)],
        ingredients=[("Titanium Ingot", 1)],
        stations=[("Fabricator", 1440.0, None)],
    )

    tree = db.resolve_recipe_tree("Titanium Part Casing", qty_needed=4)

    assert db._node_crafts(tree) == 4
    assert db._node_own_time(tree) == 1440.0 * 4


def test_subtree_remaining_seconds_excludes_checked_subtree(db):
    db.save_recipe(
        None,
        "Iron Bar",
        outputs=[("Iron Bar", 1)],
        ingredients=[("Iron Ore", 2)],
        stations=[("Smelter", 100.0, None)],
    )
    db.save_recipe(
        None,
        "Gear",
        outputs=[("Gear", 1)],
        ingredients=[("Iron Bar", 3)],
        stations=[("Assembler", 50.0, None)],
    )

    tree = db.resolve_recipe_tree("Gear", qty_needed=1)
    iron_bar_path_key = "Gear|Iron Bar"

    remaining_before = db._subtree_remaining_seconds(tree, [], set())
    remaining_after = db._subtree_remaining_seconds(tree, [], {iron_bar_path_key})

    # Gear itself: 1 craft * 50s. Iron Bar: 3 crafts * 100s = 300s.
    assert remaining_before == 50.0 + 300.0
    # Checking Iron Bar's path_key drops its whole subtree's contribution,
    # leaving only Gear's own craft time.
    assert remaining_after == 50.0


def test_collect_path_keys_includes_self_and_descendants(db):
    db.save_recipe(
        None,
        "Iron Bar",
        outputs=[("Iron Bar", 1)],
        ingredients=[("Iron Ore", 2)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Gear",
        outputs=[("Gear", 1)],
        ingredients=[("Iron Bar", 3)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree("Gear", qty_needed=1)

    keys = db._collect_path_keys(tree, [])

    assert keys == ["Gear", "Gear|Iron Bar", "Gear|Iron Bar|Iron Ore"]


def test_node_has_step_options_true_for_alts_and_multi_mode_stations(db):
    db.save_recipe(
        None,
        "Fuel",
        outputs=[("Energy", 1)],
        ingredients=[("Coal", 2)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Battery",
        outputs=[("Energy", 1)],
        ingredients=[("Lithium", 1)],
        stations=DEFAULT_STATIONS,
    )
    db.save_recipe(
        None,
        "Steel Ingot",
        outputs=[("Steel Ingot", 3)],
        ingredients=[("Iron Ingot", 4)],
        stations=[("Smelter", 180.0, 5.0), ("Micro-Furnace", 10.0, 5.0)],
    )

    energy_tree = db.resolve_recipe_tree("Energy", qty_needed=1)
    steel_tree = db.resolve_recipe_tree("Steel Ingot", qty_needed=3)
    iron_ore_tree = db.resolve_recipe_tree("Iron Ore", qty_needed=1)

    assert db._node_has_step_options(energy_tree) is True  # has alts
    assert db._node_has_step_options(steel_tree) is True  # multi-mode stations
    assert db._node_has_step_options(iron_ore_tree) is False  # raw, no options


def test_alt_pref_raw_material_sentinel_forces_raw(db):
    # A recipe exists for "Quartz", but a RAW_MATERIAL_PREF alt pref should
    # override it - is_recipe False, no children, and the real recipe still
    # listed in alts (as "Raw Material"'s own exclude target) so the picker
    # can offer switching back.
    quartz_id = db.save_recipe(
        None,
        "Quartz",
        outputs=[("Quartz", 25)],
        ingredients=[("Silicon Ingot", 32)],
        stations=DEFAULT_STATIONS,
    )

    tree = db.resolve_recipe_tree(
        "Quartz", qty_needed=6, _alt_prefs={"Quartz": resolver.RAW_MATERIAL_PREF}
    )

    assert tree["is_recipe"] is False
    assert tree["children"] == []
    assert tree["cycle_cut"] is False  # forced raw, not a cycle artifact
    assert len(tree["alts"]) == 1
    assert tree["alts"][0]["recipe_id"] == quartz_id
    assert tree["alts"][0]["recipe_name"] == "Quartz"


def test_raw_material_option_offered_only_for_curated_items(db):
    # "Raw Material" must be LIMITED to the curated list (db.get_raw_
    # material_names) - an item with a recipe but no gather source of its
    # own (Energy here) never gets the option at all, even though it's
    # is_recipe True same as a curated item would be.
    fuel_id = db.save_recipe(
        None,
        "Fuel",
        outputs=[("Energy", 1)],
        ingredients=[("Coal", 2)],
        stations=DEFAULT_STATIONS,
    )

    plain_tree = db.resolve_recipe_tree("Energy", qty_needed=1)
    assert plain_tree["is_recipe"] is True
    assert plain_tree["alts"] == []

    # Curated + no explicit _alt_prefs override at all - defaults straight
    # to raw (the actual point of db.get_raw_material_names), with the real
    # recipe offered in the picker to switch to crafted.
    default_raw_tree = db.resolve_recipe_tree(
        "Energy", qty_needed=1, _raw_material_names={"Energy"}
    )
    assert default_raw_tree["is_recipe"] is False
    assert default_raw_tree["children"] == []
    assert [alt["recipe_id"] for alt in default_raw_tree["alts"]] == [fuel_id]

    # Explicitly overridden to the real recipe - Raw Material reappears as
    # the one thing not currently active, to switch back to.
    crafted_tree = db.resolve_recipe_tree(
        "Energy",
        qty_needed=1,
        _raw_material_names={"Energy"},
        _alt_prefs={"Energy": fuel_id},
    )
    assert crafted_tree["is_recipe"] is True
    crafted_alt_names = [alt["recipe_name"] for alt in crafted_tree["alts"]]
    assert crafted_alt_names == [resolver.RAW_MATERIAL_RECIPE_NAME]


def test_cycle_cut_occurrence_not_counted_as_shared(db):
    # Root -> P -> A -> B -> A (cycle). A's second occurrence (under B) is
    # a cycle-detection placeholder, not a genuine second consumer - it
    # must not make A look "shared" between P and B (mirrors the real
    # h-Crystal Matrix / Hematite cycle in resources.db that motivated this
    # fix: both occurrences trace back to the same job, not two jobs).
    db.save_recipe(
        None, "Root", outputs=[("Root", 1)], ingredients=[("P", 1)], stations=DEFAULT_STATIONS
    )
    db.save_recipe(
        None, "P", outputs=[("P", 1)], ingredients=[("A", 1)], stations=DEFAULT_STATIONS
    )
    db.save_recipe(
        None, "A", outputs=[("A", 1)], ingredients=[("B", 1)], stations=DEFAULT_STATIONS
    )
    db.save_recipe(
        None, "B", outputs=[("B", 1)], ingredients=[("A", 1)], stations=DEFAULT_STATIONS
    )

    tree = db.resolve_recipe_tree("Root", qty_needed=1)
    specs = resolver.build_occurrence_specs(tree)
    occurrences = resolver.filter_unchecked_occurrences(specs, set())
    for occ in occurrences:
        occ["queue_id"] = 1
    aggregated = resolver.aggregate_item_occurrences(occurrences)

    a_entry = aggregated["A"]
    assert len(a_entry["occurrences"]) == 2  # under P (real), and under B (cycle-cut)
    assert a_entry["is_shared"] is False
    assert a_entry["is_root_demand"] is False
