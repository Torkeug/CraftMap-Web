"""Tests for backend.api.Api.get_farming_crops (the "Farming" tab -
frontend/js/farming.js) - static, JSON-file-backed reference data, not
DB-backed, same rationale as test_api_wrecks.py: no isolated-temp-DB
fixture, reads the real game_data_extract/farming.json shipped with the
repo.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.api import Api  # noqa: E402


def test_get_farming_crops_returns_both_crops():
    api = Api()
    crops = api.get_farming_crops()
    json.dumps(crops)
    ids = [c["id"] for c in crops]
    assert ids == ["rockwood", "spacekorn"]


def test_rockwood_has_five_variants():
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    variants = crops["rockwood"]["variants"]
    assert len(variants) == 5
    names = {v["name"] for v in variants}
    assert names == {
        "Rockwood Green",
        "Rockwood White",
        "Rockwood Dream",
        "Rockwood Glow",
        "Rockwood Bitter",
    }


def test_spacekorn_has_three_variants():
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    variants = crops["spacekorn"]["variants"]
    assert len(variants) == 3
    names = {v["name"] for v in variants}
    assert names == {"Spacekorn Plain", "Spacekorn Sour", "Woolly Spacekorn"}


def test_every_variant_has_gate_and_timing_fields():
    api = Api()
    crops = api.get_farming_crops()
    for crop in crops:
        for variant in crop["variants"]:
            assert isinstance(variant["temperature"], list)
            assert isinstance(variant["light"], list)
            assert len(variant["growth_hours"]) == 2
            assert len(variant["fruit_cycle_hours"]) == 2
            assert len(variant["byproduct_cycle_hours"]) == 2


def test_rockwood_dream_gated_to_dark_light_and_no_hot():
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    dream = next(v for v in crops["rockwood"]["variants"] if v["id"] == "Dreamwood")
    assert dream["light"] == ["Dark"]
    assert "Hot" not in dream["temperature"]


def test_woolly_spacekorn_has_no_bio_tag():
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    woolly = next(v for v in crops["spacekorn"]["variants"] if v["id"] == "ChillyEinkorn")
    assert woolly["bio_tag"] is None


def test_enrichment_dial_triggers_reference_values_the_variant_actually_gates_on():
    """frontend/js/farming.js renders a "temp"/"light" trigger as the same
    dial chip used in Requirements - a trigger value not present in the
    variant's own temperature/light gate (or, for an unconstrained gate,
    just not a real dial position) would render a chip claiming a gate
    that doesn't exist, so this guards farming.json's hand-transcription
    against that kind of typo. "neighbor_tag" triggers aren't gated by the
    variant's own dial at all (see farming.json's _meta.enrichment_trigger)
    so they're only checked against the valid bio-tag set, not a gate."""
    api = Api()
    crops = api.get_farming_crops()
    valid_temps = {"Cold", "Temperate", "Warm", "Hot"}
    valid_lights = {"UV", "Natural", "Dark"}
    valid_tags = {"Reclusive", "Invasive", "Putrescent"}
    seen_any_trigger = False
    for crop in crops:
        for variant in crop["variants"]:
            for e in variant["enrichments"]:
                trigger = e.get("trigger")
                if not trigger:
                    continue
                seen_any_trigger = True
                assert trigger["kind"] in ("temp", "light", "neighbor_tag")
                if trigger["kind"] == "neighbor_tag":
                    assert set(trigger["values"]) <= valid_tags
                    continue
                valid = valid_temps if trigger["kind"] == "temp" else valid_lights
                assert set(trigger["values"]) <= valid
                gate = variant["temperature"] if trigger["kind"] == "temp" else variant["light"]
                if gate:
                    assert set(trigger["values"]) <= set(gate)
    assert seen_any_trigger


def test_neighbor_restriction_tag_is_a_valid_bio_tag_or_none():
    api = Api()
    crops = api.get_farming_crops()
    valid_tags = {"Reclusive", "Invasive", "Putrescent"}
    for crop in crops:
        for variant in crop["variants"]:
            tag = variant["neighbor_restriction_tag"]
            assert tag is None or tag in valid_tags


def test_only_invasive_tagged_variants_get_the_spread_adjacency_line():
    """game_logic_notes.md Finding 16's Invasive-spread mechanic only
    applies to Invasive-tagged variants - Rockwood Dream and Spacekorn
    Plain per Finding 13/14 - so they're the only ones whose adjacency
    list should mention it."""
    api = Api()
    crops = api.get_farming_crops()
    spread_variants = {
        v["id"]
        for crop in crops
        for v in crop["variants"]
        if any("Invasive spread" in line for line in v["adjacency"])
    }
    invasive_variants = {
        v["id"] for crop in crops for v in crop["variants"] if v["bio_tag"] == "Invasive"
    }
    assert spread_variants == invasive_variants == {"Dreamwood", "Plainkorn"}


def test_no_variant_carries_the_removed_fertilizer_forbidden_any_flag():
    """An earlier revision marked Rockwood Glow "fertilizer_forbidden_any"
    from a live-play impression; the flagged-for-follow-up disassembly
    check then found the game has no such mechanism at all (a gate can
    only require/forbid SPECIFIC supplements - see farming.json's own
    _meta.fertilizer_forbidden_any_removed), so the flag must stay gone -
    frontend/js/farming.js no longer knows how to render it either."""
    api = Api()
    crops = api.get_farming_crops()
    flagged = [
        v["id"]
        for crop in crops
        for v in crop["variants"]
        if v.get("fertilizer_forbidden_any")
    ]
    assert flagged == []


def test_effect_entries_have_valid_attr_and_value():
    """frontend/js/farming.js's harvest calculator trusts every effects
    entry's shape completely (see farming.json's own _meta.effects) - a
    bad attr name would silently no-op instead of erroring, and a
    non-positive growth_speed_mult would produce a nonsensical
    (zero/negative/infinite) growth time and yield, so this guards the
    hand-transcription. The old speed_effect model (stat/type keys) must
    not reappear - the frontend no longer reads it."""
    api = Api()
    crops = api.get_farming_crops()
    valid_attrs = {"all_speed", "growth_speed_mult", "fruit_qty", "byproduct_qty"}
    seen_any = False
    for crop in crops:
        for variant in crop["variants"]:
            sources = list(variant["enrichments"]) + variant.get("neighbor_effects", [])
            for entry in sources:
                assert "speed_effect" not in entry, entry
                for eff in entry.get("effects", []):
                    seen_any = True
                    assert eff["attr"] in valid_attrs
                    assert eff["value"] > 0
    assert seen_any


def test_dial_group_entries_reference_a_valid_group():
    api = Api()
    crops = api.get_farming_crops()
    for crop in crops:
        for variant in crop["variants"]:
            sources = list(variant["enrichments"]) + variant.get("neighbor_effects", [])
            for entry in sources:
                if "dial_group" in entry:
                    assert entry["dial_group"] in ("temp", "light")


def test_every_enrichment_is_toggleable_and_effects_match_their_prose():
    """Since Finding 18 the app models yields, so quantity bonuses are
    toggleable too - every enrichment must carry a non-empty effects array
    (a missing one would silently render as dead, non-interactive text),
    and each effect attr must agree with the entry's own prose: a
    fruit_qty/byproduct_qty entry talks about "quantity", an all_speed
    entry about "speed", a growth_speed_mult entry about growing "slower"
    (the below-1 metabolic-speed tradeoff is the only kind in the data).
    Guards the hand-transcription against attr/prose mismatches - exactly
    the +speed-vs-+quantity mislabeling bug this tab shipped with once.
    neighbor_effects entries are held to the same bar (each carries its
    own "effect" prose - frontend/js/farming.js renders it after the
    label, so a missing one would leave a description-less toggle)."""
    api = Api()
    crops = api.get_farming_crops()
    for crop in crops:
        for variant in crop["variants"]:
            sources = list(variant["enrichments"]) + variant.get("neighbor_effects", [])
            for e in sources:
                effects = e.get("effects")
                assert effects, e
                assert e.get("effect"), e
                if "effect_note" in e:
                    assert isinstance(e["effect_note"], str) and e["effect_note"], e
                text = e["effect"].lower()
                for eff in effects:
                    if eff["attr"] in ("fruit_qty", "byproduct_qty"):
                        assert "quantity" in text or "per harvest" in text, e
                    elif eff["attr"] == "all_speed":
                        assert "speed" in text, e
                    elif eff["attr"] == "growth_speed_mult":
                        assert "slower" in text, e


def test_neighbor_effects_only_on_variants_with_a_real_source():
    """Three real cross-variant cases exist: Spacekorn Plain's self-buff
    from a neighboring Plain, Rockwood Glow's UV-lit effect mirrored onto
    whichever variants have their own Light=UV enrichment (Rockwood Bitter
    and all three Spacekorn variants), and Woolly Spacekorn's own +20%
    Byproduct quantity 'to any neighbor' (its adjacency line) mirrored onto
    the Rockwood variants that can actually share its Cold-only dial gate
    (Green/White/Dream - not Bitter, whose Warm/Hot gate can never overlap
    a Cold farm). That third case was originally missing entirely (Woolly's
    own card recorded what it gives, but no receiving variant's card could
    toggle receiving it) until building the Layouts view's goal_presets
    exposed that White's own rate-optimal pairing depends on it."""
    api = Api()
    crops = api.get_farming_crops()
    with_neighbor_effects = {
        v["id"]
        for crop in crops
        for v in crop["variants"]
        if v.get("neighbor_effects")
    }
    assert with_neighbor_effects == {
        "Plainkorn",
        "SourEinkorn",
        "ChillyEinkorn",
        "Sulfwood",
        "Rockwood",
        "Whitewood",
        "Dreamwood",
    }


def test_every_togglable_entry_has_a_stable_id():
    """frontend/js/farming.js's Layouts view resolves a goal_preset's
    toggle_ids against these same ids (see farming.json's own
    _meta.effects) - a togglable entry (anything carrying 'effects')
    missing one would make that preset's checkbox unreachable."""
    api = Api()
    crops = api.get_farming_crops()
    for crop in crops:
        for variant in crop["variants"]:
            sources = list(variant["enrichments"]) + variant.get("neighbor_effects", [])
            for e in sources:
                if "effects" in e:
                    assert e.get("id"), (variant["id"], e)


def test_get_farming_layouts_returns_expected_layout_ids():
    api = Api()
    layouts = api.get_farming_layouts()
    json.dumps(layouts)
    assert set(layouts.keys()) == {"A", "B", "C", "C-alt", "D", "D-mix"}


def test_every_layout_grid_is_a_valid_5x3_board_of_real_variant_ids():
    api = Api()
    layouts = api.get_farming_layouts()
    crops = api.get_farming_crops()
    valid_variant_ids = {v["id"] for crop in crops for v in crop["variants"]}
    for layout_id, layout in layouts.items():
        grid = layout["grid"]
        assert len(grid) == 3, layout_id
        for row in grid:
            assert len(row) == 5, layout_id
            for cell in row:
                assert cell is None or cell in valid_variant_ids, (layout_id, cell)


def test_every_layout_dial_is_a_structured_valid_temp_and_light_list():
    """frontend/js/farming.js's Layouts view renders a layout's dial as
    Temperature/Light chips (makeDialChips, the same component the
    Reference tab's own Requirements block uses) rather than a plain
    string - this guards that 'dial' stayed structured (not a leftover
    'dial_display' free-text field) and only ever names real dial
    positions."""
    api = Api()
    layouts = api.get_farming_layouts()
    valid_temps = {"Cold", "Temperate", "Warm", "Hot"}
    valid_lights = {"UV", "Natural", "Dark"}
    for layout_id, layout in layouts.items():
        assert "dial_display" not in layout, layout_id
        dial = layout["dial"]
        assert dial["temperature"], layout_id
        assert set(dial["temperature"]) <= valid_temps, layout_id
        assert dial["light"], layout_id
        assert set(dial["light"]) <= valid_lights, layout_id


def test_fertilizer_item_entries_match_their_own_condition_and_are_real_supplements():
    """frontend/js/farming.js's Layouts view builds a preset's Fertilizer
    line from fertilizer_item (see farming.json's own _meta.effects) -
    only ever set on an enrichment whose condition is a plain "<item>
    present" fertilizer gate (never a temp/light/neighbor_tag trigger,
    which farming.js's Layouts view handles as chips instead), and the
    named item must be a real fertilizer this data model knows about."""
    api = Api()
    crops = api.get_farming_crops()
    valid_fertilizers = {
        "Neutral Fertilizer",
        "Metallic Fertilizer",
        "Carbonic Fertilizer",
        "Acidic Fertilizer",
        "Elmerium Dust",
    }
    seen_any = False
    for crop in crops:
        for variant in crop["variants"]:
            for e in variant["enrichments"]:
                if "fertilizer_item" not in e:
                    continue
                seen_any = True
                assert "trigger" not in e, (variant["id"], e["id"])
                assert e["fertilizer_item"] in valid_fertilizers, (variant["id"], e["id"])
                assert e["condition"] == f"{e['fertilizer_item']} present", (variant["id"], e["id"])
    assert seen_any


def test_every_goal_preset_toggle_id_exists_on_that_same_variant():
    """A goal_presets entry only ever references its OWN variant's toggle
    ids (see farming.json's own _meta.goal_presets_and_layouts) - this
    guards against a typo'd id or a stale reference left over from
    reshuffling which toggles a preset implies."""
    api = Api()
    crops = api.get_farming_crops()

    def all_preset_id_lists(goal_entry):
        if goal_entry.get("no_dominant"):
            for option in goal_entry["options"]:
                yield option["toggle_ids"]
        else:
            yield goal_entry["toggle_ids"]

    for crop in crops:
        for variant in crop["variants"]:
            presets = variant.get("goal_presets")
            if not presets:
                continue
            own_ids = {
                e["id"]
                for e in list(variant["enrichments"]) + variant.get("neighbor_effects", [])
                if "id" in e
            }
            for metric in ("rate", "harvest"):
                for goal in ("overall", "fruit_only", "byproduct_only"):
                    for ids in all_preset_id_lists(presets[metric][goal]):
                        assert set(ids) <= own_ids, (variant["id"], metric, goal, ids)


def test_every_goal_preset_layout_reference_exists():
    api = Api()
    crops = api.get_farming_crops()
    layouts = api.get_farming_layouts()

    def all_preset_layout_refs(goal_entry):
        if goal_entry.get("no_dominant"):
            for option in goal_entry["options"]:
                yield option["layout"]
        else:
            yield goal_entry["layout"]

    for crop in crops:
        for variant in crop["variants"]:
            presets = variant.get("goal_presets")
            if not presets:
                continue
            for metric in ("rate", "harvest"):
                for goal in ("overall", "fruit_only", "byproduct_only"):
                    for layout_id in all_preset_layout_refs(presets[metric][goal]):
                        assert layout_id in layouts, (variant["id"], metric, goal, layout_id)


def test_variants_with_goal_presets_cover_every_non_unreachable_variant():
    """Rockwood Glow is the one variant with no goal_presets at all - it's
    unreachable in normal play (see farming.json's own _meta.unreachable),
    so there's no real setup to recommend for it."""
    api = Api()
    crops = api.get_farming_crops()
    with_presets = {
        v["id"] for crop in crops for v in crop["variants"] if v.get("goal_presets")
    }
    without_presets = {
        v["id"] for crop in crops for v in crop["variants"] if not v.get("goal_presets")
    }
    assert without_presets == {"Glowwood"}
    assert "Glowwood" not in with_presets


def test_only_rockwood_glow_is_marked_unreachable():
    """game_logic_notes.md Finding 13's correction: Glowwood's temperature/
    light fields are a literal 0 in the source data (not absent), and
    hasMinRequirement never skips a present field - so its gate can NEVER
    pass, confirmed by both disassembly and a direct in-game test. No
    other variant in Findings 13/14 has this bug - every other
    "unconstrained" gate uses a genuinely absent key."""
    api = Api()
    crops = api.get_farming_crops()
    unreachable = [
        v["id"] for crop in crops for v in crop["variants"] if v.get("unreachable")
    ]
    assert unreachable == ["Glowwood"]
    glow = next(v for crop in crops for v in crop["variants"] if v["id"] == "Glowwood")
    assert isinstance(glow["unreachable_note"], str) and len(glow["unreachable_note"]) > 20
    # Empty temperature/light on an unreachable variant means "can never
    # pass," the opposite of what an empty list means everywhere else -
    # frontend/js/farming.js relies on the unreachable flag itself (not
    # the list contents) to tell the two cases apart, so both must stay
    # empty for that disambiguation to mean anything.
    assert glow["temperature"] == []
    assert glow["light"] == []
