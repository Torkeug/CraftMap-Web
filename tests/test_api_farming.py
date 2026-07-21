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


def test_get_farming_mechanics_note_returns_nonempty_text():
    api = Api()
    note = api.get_farming_mechanics_note()
    json.dumps(note)
    assert isinstance(note, str) and len(note) > 100


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


def test_only_rockwood_glow_forbids_any_fertilizer():
    """"fertilizer_forbidden_any" marks a genuinely different case from a
    merely empty fertilizer_required (see farming.json's own
    _meta.fertilizer_forbidden_any) - Finding 13/14's own tables write
    Rockwood Glow's Fertilizer-required cell as the distinct word "none"
    while every other unconstrained variant (Spacekorn Plain, Woolly
    Spacekorn) uses "-", so only Glowwood should carry this flag."""
    api = Api()
    crops = api.get_farming_crops()
    flagged = [
        v["id"]
        for crop in crops
        for v in crop["variants"]
        if v.get("fertilizer_forbidden_any")
    ]
    assert flagged == ["Glowwood"]


def test_speed_effect_entries_have_valid_stat_type_and_value():
    """frontend/js/farming.js's timing calculator trusts every speed_effect
    entry's shape completely (see farming.json's own _meta.speed_effect) -
    a bad stat/type name would silently no-op instead of erroring, and a
    non-positive value would produce a nonsensical (zero/negative/infinite)
    adjusted duration, so this guards the hand-transcription."""
    api = Api()
    crops = api.get_farming_crops()
    valid_stats = {"growth", "fruit", "byproduct"}
    valid_types = {"additive", "multiplicative"}
    seen_any = False
    for crop in crops:
        for variant in crop["variants"]:
            sources = list(variant["enrichments"]) + variant.get("neighbor_effects", [])
            for entry in sources:
                for eff in entry.get("speed_effect", []):
                    seen_any = True
                    assert eff["stat"] in valid_stats
                    assert eff["type"] in valid_types
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


def test_quantity_only_enrichments_carry_no_speed_effect():
    """An enrichment whose effect text says "quantity" (not "speed") boosts
    output, not timing - this app tracks no yield/quantity field at all, so
    those entries must NOT carry a speed_effect (frontend/js/farming.js
    would otherwise render a checkbox that claims to change a cycle time
    it actually has no effect on)."""
    api = Api()
    crops = api.get_farming_crops()
    checked_any = False
    for crop in crops:
        for variant in crop["variants"]:
            for e in variant["enrichments"]:
                if "quantity" in e["effect"].lower() and "speed" not in e["effect"].lower():
                    checked_any = True
                    assert "speed_effect" not in e, e
    assert checked_any


def test_neighbor_effects_only_on_variants_with_a_real_source():
    """Only two real cross-variant cases exist per game_logic_notes.md
    Finding 13/16: Spacekorn Plain's self-buff from a neighboring Plain,
    and Rockwood Glow's UV-lit effect mirrored onto whichever variants
    have their own Light=UV enrichment (Rockwood Bitter and all three
    Spacekorn variants)."""
    api = Api()
    crops = api.get_farming_crops()
    with_neighbor_effects = {
        v["id"]
        for crop in crops
        for v in crop["variants"]
        if v.get("neighbor_effects")
    }
    assert with_neighbor_effects == {"Plainkorn", "SourEinkorn", "ChillyEinkorn", "Sulfwood"}
