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
    assert set(layouts.keys()) == {
        "A",
        "B",
        "C",
        "C-alt",
        "D",
        "D-sparse",
        "D-sparse-rate",
        "D-mix",
        "E",
        "E-alt",
        "F",
        "G",
    }


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


def _mid(rng):
    return (rng[0] + rng[1]) / 2


def _collect_effects(variant, toggle_ids):
    acc = {"all_speed": 0.0, "growth_speed_mult": 1.0, "fruit_qty": 0.0, "byproduct_qty": 0.0}
    for e in list(variant["enrichments"]) + variant.get("neighbor_effects", []):
        if e.get("id") in toggle_ids:
            for eff in e["effects"]:
                if eff["attr"] == "growth_speed_mult":
                    acc["growth_speed_mult"] *= eff["value"]
                else:
                    acc[eff["attr"]] += eff["value"]
    return acc


def _yields(variant, acc):
    import math

    g = _mid(variant["growth_hours"])
    fruit = math.ceil(g * (1 + acc["fruit_qty"]) / (_mid(variant["fruit_cycle_hours"]) * acc["growth_speed_mult"]))
    byprod = math.ceil(
        g * (1 + acc["byproduct_qty"]) / (_mid(variant["byproduct_cycle_hours"]) * acc["growth_speed_mult"])
    )
    return fruit, byprod


def _rates(variant, acc, germ_hours):
    fruit, byprod = _yields(variant, acc)
    growth_time = _mid(variant["growth_hours"]) / ((1 + acc["all_speed"]) * acc["growth_speed_mult"])
    cycle = germ_hours + growth_time
    return fruit / cycle, byprod / cycle


def _grid_count(layout, variant_id):
    return sum(row.count(variant_id) for row in layout["grid"])


def test_plain_layout_d_beats_d_mix_on_every_farm_total_axis():
    """Regression guard for the 2026-07-27 per-slot-vs-per-farm correction
    (see farming.json's own _meta.per_slot_vs_per_farm): Layout D-mix's
    per-plant numbers are individually higher than Layout D's, but D-mix
    only fits 9 Plain plots to D's 15 - and once multiplied through, D
    wins every comparison, not just some. If this ever flips back, Plain's
    goal_presets need to fork again (or worse, someone reverted the fix
    without reverting the recommendation)."""
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    layouts = api.get_farming_layouts()
    plain = next(v for v in crops["spacekorn"]["variants"] if v["id"] == "Plainkorn")
    germ = _mid(crops["spacekorn"]["germination_hours"])

    d_count = _grid_count(layouts["D"], "Plainkorn")
    dmix_count = _grid_count(layouts["D-mix"], "Plainkorn")
    assert d_count > dmix_count, "test assumption broken: D no longer has more Plain plots than D-mix"

    d_acc = _collect_effects(plain, {"temperate_speed", "uv_speed", "plain_neighbor", "neutral"})
    dmix_acc = _collect_effects(plain, {"uv_speed", "plain_neighbor", "putrescent_neighbor", "neutral"})

    d_fruit, d_byprod = _yields(plain, d_acc)
    dmix_fruit, dmix_byprod = _yields(plain, dmix_acc)
    assert d_fruit * d_count > dmix_fruit * dmix_count, "D should win farm-total fruit harvest"
    assert d_byprod * d_count > dmix_byprod * dmix_count, "D should win farm-total byproduct harvest"

    d_frate, d_brate = _rates(plain, d_acc, germ)
    dmix_frate, dmix_brate = _rates(plain, dmix_acc, germ)
    assert d_frate * d_count > dmix_frate * dmix_count, "D should win farm-total fruit rate"
    assert d_brate * d_count > dmix_brate * dmix_count, "D should win farm-total byproduct rate"


def test_plain_goal_presets_never_reference_d_mix():
    """Layout D-mix remains real, mechanically-valid data (see its own
    note - it's a legitimate 'grow both crops from one farm' option) but
    is no longer farm-total-optimal for Plain on any axis - Plain's own
    goal_presets should never point at it (see the preceding test for the
    numbers). byproduct_only stays on Layout D specifically (an exact
    grid search found no battery placement ever beats a full Plain vault
    for byproduct); fruit_only moved off Layout D too, onto the sparse
    battery layouts - see test_plain_sparse_battery_layouts_beat_d_on_fruit."""
    api = Api()
    crops = api.get_farming_crops()
    plain = next(
        v for crop in crops for v in crop["variants"] if v["id"] == "Plainkorn"
    )
    for metric in ("rate", "harvest"):
        for goal in ("overall", "fruit_only", "byproduct_only"):
            assert plain["goal_presets"][metric][goal]["layout"] != "D-mix", (metric, goal)
        assert plain["goal_presets"][metric]["byproduct_only"]["layout"] == "D"


def test_no_dominant_shape_is_currently_unused():
    """The {no_dominant: true, options: [...]} shape is for a genuine
    Pareto trade-off with no single winner - meant as a last resort, not
    the answer to "overall" whenever fruit-optimal and byproduct-optimal
    genuinely diverge. It WAS briefly used that way (2026-07-27) for
    Plain's rate/harvest 'overall' and White's rate 'overall', each as a
    2-option menu re-presenting the fruit_only/byproduct_only extremes -
    but that's not actually answering "what's best if I want both", it's
    dodging the question. Replaced same-day by a genuine combined-
    objective grid search (each product normalized against its own
    achievable best, summed, then re-optimized end to end) that resolves
    'overall' to one real single answer per variant every time - see
    _meta.exact_grid_search. Nothing should use no_dominant again unless
    a future case can't be resolved even that way."""
    api = Api()
    crops = api.get_farming_crops()
    for crop in crops:
        for variant in crop["variants"]:
            presets = variant.get("goal_presets")
            if not presets:
                continue
            for metric in ("rate", "harvest"):
                for goal in ("overall", "fruit_only", "byproduct_only"):
                    assert not presets[metric][goal].get("no_dominant"), (variant["id"], metric, goal)


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


def test_neighbor_effects_variant_triggers_reference_real_variant_ids():
    """A neighbor_effects entry's optional trigger ({kind: 'neighbor_variant',
    values: [...]}) names which actual variant id(s) grant it - added
    2026-07-27 so frontend/js/farming.js's per-cell farm-total math
    (collectEffectsForCell) can identify a real grid neighbor's
    contribution without parsing the free-text 'label' (the previous
    approach, which had a real bug: matching on a variant's own first
    name-word false-positived on a shared crop-family word, e.g. Sulfwood
    matching its own glow_neighbor entry on 'Rockwood' alone)."""
    api = Api()
    crops = api.get_farming_crops()
    valid_variant_ids = {v["id"] for crop in crops for v in crop["variants"]}
    seen_any = False
    for crop in crops:
        for variant in crop["variants"]:
            for e in variant.get("neighbor_effects", []):
                trigger = e.get("trigger")
                assert trigger is not None, (variant["id"], e["id"])
                seen_any = True
                assert trigger["kind"] == "neighbor_variant", (variant["id"], e["id"])
                assert trigger["values"], (variant["id"], e["id"])
                assert set(trigger["values"]) <= valid_variant_ids, (variant["id"], e["id"])
    assert seen_any


def _grid_neighbor_coords(r, c, rows, cols):
    out = []
    if r > 0:
        out.append((r - 1, c))
    if r < rows - 1:
        out.append((r + 1, c))
    if c > 0:
        out.append((r, c - 1))
    if c < cols - 1:
        out.append((r, c + 1))
    return out


def test_no_layout_places_two_reclusive_tagged_cells_adjacent():
    """Structural guard for the 2026-07-27 correction: a Reclusive-tagged
    variant's own gate requires no Reclusive-tagged neighbor, checked
    continuously (growth_death_mechanism) AND at the moment a fresh seed
    resolves into that variant (mechanism) - unlike Woolly's Putrescent
    restriction, this one is NOT battery-exempt, because the exemption
    only protects an ALREADY-mature cell's own restriction from being
    re-triggered; it does nothing for a freshly-resolving neighbor still
    checking what's already there. So no achievable steady state ever has
    two Reclusive cells (Green/White/Glow) mutually adjacent, in any
    layout, regardless of planting order - an earlier version of this
    optimizer work briefly produced illegal 'solid Reclusive pack' layouts
    before this was caught; this guards against that mistake returning."""
    api = Api()
    crops = api.get_farming_crops()
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops for v in crop["variants"]}
    for layout_id, layout in layouts.items():
        grid = layout["grid"]
        rows, cols = len(grid), len(grid[0])
        for r, row in enumerate(grid):
            for c, cell_id in enumerate(row):
                if cell_id is None or variants_by_id[cell_id].get("bio_tag") != "Reclusive":
                    continue
                for nr, nc in _grid_neighbor_coords(r, c, rows, cols):
                    neighbor_id = grid[nr][nc]
                    if neighbor_id is None:
                        continue
                    assert variants_by_id[neighbor_id].get("bio_tag") != "Reclusive", (
                        layout_id, r, c, cell_id, neighbor_id
                    )


def _collect_effects_for_cell(variant, toggle_ids, neighbor_ids, variants_by_id):
    """Python port of frontend/js/farming.js's collectEffectsForCell - true
    per-cell coverage (a neighbor-conditioned toggle only applies if an
    ACTUAL grid neighbor satisfies it), unlike this file's own older
    _collect_effects helper above (blanket - assumes every counted cell
    gets every toggle_id, correct only for uniform-coverage layouts)."""
    acc = {"all_speed": 0.0, "growth_speed_mult": 1.0, "fruit_qty": 0.0, "byproduct_qty": 0.0}
    neighbor_bio_tags = [
        variants_by_id[nid]["bio_tag"] for nid in neighbor_ids if nid in variants_by_id
    ]
    for e in list(variant["enrichments"]) + variant.get("neighbor_effects", []):
        if e.get("id") not in toggle_ids:
            continue
        trig = e.get("trigger")
        if trig and trig["kind"] == "neighbor_tag":
            if trig["values"][0] not in neighbor_bio_tags:
                continue
        elif trig and trig["kind"] == "neighbor_variant":
            if not (set(trig["values"]) & set(neighbor_ids)):
                continue
        for eff in e["effects"]:
            if eff["attr"] == "growth_speed_mult":
                acc["growth_speed_mult"] *= eff["value"]
            else:
                acc[eff["attr"]] += eff["value"]
    return acc


def _farm_totals_per_cell(variant, toggle_ids, layout, variants_by_id, germ_hours):
    grid = layout["grid"]
    rows, cols = len(grid), len(grid[0])
    g = _mid(variant["growth_hours"])
    fruit_h = byprod_h = fruit_r = byprod_r = 0.0
    count = 0
    for r, row in enumerate(grid):
        for c, cell_id in enumerate(row):
            if cell_id != variant["id"]:
                continue
            count += 1
            neighbor_ids = [
                grid[nr][nc] for nr, nc in _grid_neighbor_coords(r, c, rows, cols) if grid[nr][nc] is not None
            ]
            acc = _collect_effects_for_cell(variant, toggle_ids, neighbor_ids, variants_by_id)
            fruit, byprod = _yields(variant, acc)
            growth_time = g / ((1 + acc["all_speed"]) * acc["growth_speed_mult"])
            cycle = germ_hours + growth_time
            fruit_h += fruit
            byprod_h += byprod
            fruit_r += fruit / cycle
            byprod_r += byprod / cycle
    return fruit_h, byprod_h, fruit_r, byprod_r, count


def test_plain_sparse_battery_layouts_beat_d_on_fruit_but_lose_on_byproduct():
    """Regression guard for the 2026-07-27 exact-grid-search finding: a
    sparse, parked Sour 'battery' (2 cells for harvest, 3 for rate) covers
    most but not all of Plain's 15 plots with the Putrescent quantity
    bonus, for free (Finding 19/20's parking technique - no dial cost).
    Confirmed here with TRUE per-cell coverage (not the blanket model
    test_plain_layout_d_beats_d_mix_on_every_farm_total_axis already uses
    for D-mix, which happens to be correct there only because D-mix's
    dense stripe genuinely does give every counted cell the same
    neighbor - Layout D-sparse's 2 cells do NOT reach every Plain cell, so
    the blanket model would silently over-count it)."""
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops.values() for v in crop["variants"]}
    plain = next(v for v in crops["spacekorn"]["variants"] if v["id"] == "Plainkorn")
    germ = _mid(crops["spacekorn"]["germination_hours"])

    d_ids = {"temperate_speed", "uv_speed", "plain_neighbor", "neutral"}
    fh, bh, fr, br, count = _farm_totals_per_cell(plain, d_ids, layouts["D"], variants_by_id, germ)
    assert (fh, bh, count) == (60, 240, 15)

    sparse_ids = {"temperate_speed", "uv_speed", "plain_neighbor", "putrescent_neighbor"}
    sfh, sbh, sfr, sbr, scount = _farm_totals_per_cell(
        plain, sparse_ids, layouts["D-sparse"], variants_by_id, germ
    )
    assert scount == 13  # 15-cell grid, 2 of them Sour battery (not counted here)
    assert sfh == 66, "sparse battery should raise fruit harvest to the verified 66"
    assert sbh < bh, "2 lost Plain plots should still cost byproduct harvest overall"

    srfh, srbh, srfr, srbr, srcount = _farm_totals_per_cell(
        plain, sparse_ids, layouts["D-sparse-rate"], variants_by_id, germ
    )
    assert srcount == 12  # 15-cell grid, 3 of them Sour battery (not counted here)
    assert srfr > fr, "3-cell sparse battery should raise fruit rate above solid D"
    assert srbr < br, "3 lost Plain plots should still cost byproduct rate overall"


def test_whitewood_mixed_layout_c_dominates_old_pure_bitter_checkerboard():
    """Regression guard for the 2026-07-27 exact-grid-search finding:
    Layout C's mixed Bitter+Woolly filler (White in the 8-cell MAJORITY
    color - the earlier version of this layout had White backwards, in
    the 7-cell minority) is simultaneously optimal for fruit harvest,
    byproduct harvest, AND byproduct rate - confirmed here with true
    per-cell coverage, not the blanket model (which happens to still be
    accurate for this specific layout, since every White cell touches
    both a Bitter AND a Woolly neighbor uniformly - but that uniformity
    was verified, not assumed)."""
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops.values() for v in crop["variants"]}
    white = next(v for v in crops["rockwood"]["variants"] if v["id"] == "Whitewood")
    germ = _mid(crops["rockwood"]["germination_hours"])

    full_ids = {"carbonic", "neutral", "putrescent_neighbor", "woolly_neighbor"}
    fh, bh, fr, br, count = _farm_totals_per_cell(white, full_ids, layouts["C"], variants_by_id, germ)
    assert count == 8
    assert fh == 24
    assert bh == 1328
    assert round(br, 3) == 12.518

    calt_ids = {"carbonic", "woolly_neighbor"}
    _, _, calt_fr, calt_br, calt_count = _farm_totals_per_cell(
        white, calt_ids, layouts["C-alt"], variants_by_id, germ
    )
    assert calt_count == 8
    assert calt_fr > fr, "C-alt should still win fruit rate specifically (why it stays fruit_only's pick)"
    assert br > calt_br, "Layout C should win byproduct rate (why it's byproduct_only's pick instead)"


def test_overall_goal_is_a_genuine_combined_optimum_not_a_menu():
    """Regression guard for the 2026-07-27 correction: 'overall' briefly
    used the {no_dominant, options: [...]} menu shape for Plain and White,
    literally re-presenting the same fruit_only/byproduct_only answers
    side by side - which doesn't actually answer 'what's best if I want
    both'. Replaced by a genuine combined-objective search (each product
    normalized against its own achievable max, summed, then the WHOLE
    dial x fertilizer x grid space re-optimized against that combined
    score) - so 'overall' must always resolve to exactly one {layout,
    toggle_ids} entry, never a menu, for every variant."""
    api = Api()
    crops = api.get_farming_crops()
    for crop in crops:
        for variant in crop["variants"]:
            presets = variant.get("goal_presets")
            if not presets:
                continue
            for metric in ("rate", "harvest"):
                entry = presets[metric]["overall"]
                assert "no_dominant" not in entry, (variant["id"], metric)
                assert "layout" in entry and "toggle_ids" in entry, (variant["id"], metric)


def test_plain_overall_lands_on_the_same_setup_for_both_framings():
    """Regression guard: the combined-objective search happened to find
    IDENTICAL setups for Plain's rate.overall and harvest.overall (Layout
    D-sparse + Neutral Fertilizer - two different-looking 2-cell Sour
    placements, D-sparse and the since-removed D-sparse-overall, turned
    out to tie exactly because both cover the same COUNT of Plain cells,
    7 of 13, and coverage count alone determines the total here). Plain
    now merges into a single 'same setup for items/hour and items/harvest'
    panel like every other variant, rather than forking by framing the
    way fruit_only/byproduct_only still legitimately do."""
    api = Api()
    crops = api.get_farming_crops()
    plain = next(v for crop in crops for v in crop["variants"] if v["id"] == "Plainkorn")
    rate_overall = plain["goal_presets"]["rate"]["overall"]
    harvest_overall = plain["goal_presets"]["harvest"]["overall"]
    assert rate_overall["layout"] == harvest_overall["layout"] == "D-sparse"
    assert sorted(rate_overall["toggle_ids"]) == sorted(harvest_overall["toggle_ids"])


def test_whitewood_rate_overall_adds_free_neutral_fertilizer_to_c_alt():
    """Regression guard: White's rate.overall combined-objective optimum
    reuses fruit_only's own Layout C-alt grid (pure Woolly checkerboard)
    rather than byproduct_only's Layout C - Bitter's metabolic slowdown
    is a net loss for rate, so the combined search never wants ANY
    Bitter cell for 'overall' either. It does add Neutral Fertilizer on
    top of fruit_only's own toggle set though: free byproduct (it only
    touches byproduct_qty, never fruit_qty, so fruit rate is untouched)
    that fruit_only itself skips only because fruit_only doesn't care
    about byproduct at all."""
    api = Api()
    crops = {c["id"]: c for c in api.get_farming_crops()}
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops.values() for v in crop["variants"]}
    white = next(v for v in crops["rockwood"]["variants"] if v["id"] == "Whitewood")
    germ = _mid(crops["rockwood"]["germination_hours"])

    overall = white["goal_presets"]["rate"]["overall"]
    assert overall["layout"] == "C-alt"
    assert "neutral" in overall["toggle_ids"]

    fr_ids = set(overall["toggle_ids"])
    fh, bh, fr, br, count = _farm_totals_per_cell(white, fr_ids, layouts["C-alt"], variants_by_id, germ)
    assert count == 8
    fruit_only_ids = set(white["goal_presets"]["rate"]["fruit_only"]["toggle_ids"])
    _, _, fo_fr, fo_br, _ = _farm_totals_per_cell(white, fruit_only_ids, layouts["C-alt"], variants_by_id, germ)
    assert round(fr, 6) == round(fo_fr, 6), "adding neutral must not change fruit rate at all"
    assert br > fo_br, "adding neutral must raise byproduct rate for free"


def _is_live_compatible_with_dial(variant, dial):
    """Python port of frontend/js/farming.js's isLiveCompatibleWithDial -
    can this variant actually grow LIVE under a layout's own dial, or can
    it only be there as a parked/battery plant (Finding 19/20)? Derived
    purely from each variant's own temperature/light gate vs the layout's
    dial - no separate 'is this a battery' field to keep in sync."""
    temp_ok = not variant["temperature"] or any(t in variant["temperature"] for t in dial["temperature"])
    light_ok = not variant["light"] or any(l in variant["light"] for l in dial["light"])
    return temp_ok and light_ok


def _battery_variant_ids_in_layout(layout, variants_by_id):
    ids = set()
    for row in layout["grid"]:
        for cell_id in row:
            if cell_id and not _is_live_compatible_with_dial(variants_by_id[cell_id], layout["dial"]):
                ids.add(cell_id)
    return ids


def test_battery_cells_are_exactly_the_dial_incompatible_companions():
    """Regression guard for the 2026-07-27 UI addition: the Layouts view
    now visually flags a cell as a parked/'battery' plant (dashed outline
    on the board, a badge in the legend, a callout on the card) whenever
    its OWN temperature/light gate can't be satisfied by the layout's own
    dial - it could never have grown to maturity live, in place, under
    that dial. This pins down the exact set this dataset currently
    produces, so a future layout/dial edit that silently breaks the
    detection (or silently creates/removes a battery requirement) shows
    up here instead of only in the UI. A layout's own TARGET variant
    should never appear in its own battery set - the dial was chosen to
    suit it in the first place."""
    api = Api()
    crops = api.get_farming_crops()
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops for v in crop["variants"]}

    found = {
        layout_id: _battery_variant_ids_in_layout(layout, variants_by_id)
        for layout_id, layout in layouts.items()
    }
    assert found == {
        "A": set(),
        "B": set(),
        "C": {"ChillyEinkorn"},
        "C-alt": set(),
        "D": set(),
        "D-sparse": {"SourEinkorn"},
        "D-sparse-rate": {"SourEinkorn"},
        "D-mix": set(),
        "E": set(),
        "E-alt": set(),
        "F": set(),
        "G": set(),
    }


def _gate_passes(variant, dt, dl, ferts_present):
    """Python port of the germination-ambiguity audit script (2026-07-27,
    not checked into this repo - see farming.json's own
    _meta.germination_ambiguity): does variant's OWN grow-gate pass under
    this dial position and fertilizer set? Mirrors hasMinRequirement's
    five independent checks (mechanism/growth_death_mechanism) minus the
    neighbor-tag one, which doesn't matter for the same-crop-sibling
    question these tests ask (a sibling's neighbor_restriction_tag is
    checked against ITS OWN neighbors, not shared with the target)."""
    if variant.get("unreachable"):
        return False
    if variant["temperature"] and dt not in variant["temperature"]:
        return False
    if variant["light"] and dl not in variant["light"]:
        return False
    for req in variant["fertilizer_required"]:
        if req not in ferts_present:
            return False
    for forb in variant["fertilizer_forbidden"]:
        if forb in ferts_present:
            return False
    return True


def _real_fert_set(target, toggle_ids, grid, variants_by_id):
    fert_key = {e["id"]: e.get("fertilizer_item") for e in target.get("enrichments", [])}
    ferts = set(target["fertilizer_required"])
    for tid in toggle_ids:
        item = fert_key.get(tid)
        if item:
            ferts.add(item)
    other_ids = {c for row in grid for c in row if c and c != target["id"]}
    for oid in other_ids:
        ferts |= set(variants_by_id[oid]["fertilizer_required"])
    return ferts


def _same_crop_contaminants(target, layout, toggle_ids, variants_by_id, crop_variant_ids):
    dt = layout["dial"]["temperature"][0]
    dl = layout["dial"]["light"][0]
    ferts = _real_fert_set(target, toggle_ids, layout["grid"], variants_by_id)
    return [
        vid for vid in crop_variant_ids
        if vid != target["id"] and _gate_passes(variants_by_id[vid], dt, dl, ferts)
    ]


def test_every_active_goal_preset_is_free_of_same_crop_germination_contamination():
    """Regression guard for the 2026-07-27 germination_ambiguity finding:
    'After germination, ALL variants whose gates currently pass become
    candidates and the game picks uniformly at random among them'
    (mechanism) applies per PLOT, not per intended layout cell - a goal
    preset's own dial+fertilizer choice must not ALSO satisfy a different
    variant of the SAME crop, or the grid's claimed per-cell species is a
    lie some fraction of the time. Checked against each preset's own REAL
    fertilizer set (target's required + optional-toggled items, plus
    every other live companion's own required items). Rockwood Bitter's
    own Vault (Layout E/E-alt) is the one documented, permanent exception
    - see test_bitter_can_never_germinate_cleanly below - every other
    active preset must come back clean."""
    api = Api()
    crops = api.get_farming_crops()
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops for v in crop["variants"]}
    crop_variant_ids = {crop["id"]: [v["id"] for v in crop["variants"]] for crop in crops}
    crop_of = {v["id"]: crop["id"] for crop in crops for v in crop["variants"]}

    def check(target, layout_key, toggle_ids, label):
        layout = layouts[layout_key]
        contaminants = _same_crop_contaminants(
            target, layout, toggle_ids, variants_by_id, crop_variant_ids[crop_of[target["id"]]]
        )
        if target["id"] == "Sulfwood":
            assert contaminants == ["Whitewood"], (label, contaminants)
        else:
            assert contaminants == [], (label, contaminants)

    for crop in crops:
        for variant in crop["variants"]:
            presets = variant.get("goal_presets")
            if not presets:
                continue
            for metric in ("rate", "harvest"):
                for goal in ("overall", "fruit_only", "byproduct_only"):
                    entry = presets[metric][goal]
                    if entry.get("no_dominant"):
                        for option in entry["options"]:
                            check(variant, option["layout"], option["toggle_ids"], f"{variant['id']}/{metric}/{goal}/{option['label']}")
                    else:
                        check(variant, entry["layout"], entry["toggle_ids"], f"{variant['id']}/{metric}/{goal}")


def test_bitter_can_never_germinate_cleanly():
    """Regression guard: Rockwood White's own gate (unconstrained dial,
    needs only Metallic Fertilizer, forbids nothing) is satisfied by
    EVERY environment that also satisfies Bitter's own gate (Warm/Hot +
    Acidic AND Metallic) - there is no dial or fertilizer choice that
    excludes White while Bitter can still grow. Exhaustively checked over
    every temperature x light x achievable-fertilizer-subset combination.
    If this ever starts passing, farming.json's own _meta.
    germination_ambiguity and Layout E/E-alt's notes need updating, not
    just this test."""
    import itertools

    api = Api()
    crops = api.get_farming_crops()
    variants_by_id = {v["id"]: v for crop in crops for v in crop["variants"]}
    bitter = variants_by_id["Sulfwood"]
    white = variants_by_id["Whitewood"]

    all_temps = ["Cold", "Temperate", "Warm", "Hot"]
    all_lights = ["UV", "Natural", "Dark"]
    all_ferts = ["Neutral Fertilizer", "Metallic Fertilizer", "Carbonic Fertilizer", "Acidic Fertilizer", "Elmerium Dust"]
    mandatory = set(bitter["fertilizer_required"])
    optional_pool = [f for f in all_ferts if f not in mandatory and f not in bitter["fertilizer_forbidden"]]

    found_clean = False
    for dt, dl in itertools.product(all_temps, all_lights):
        for r in range(len(optional_pool) + 1):
            for combo in itertools.combinations(optional_pool, r):
                ferts = mandatory | set(combo)
                if _gate_passes(bitter, dt, dl, ferts) and not _gate_passes(white, dt, dl, ferts):
                    found_clean = True
    assert not found_clean, "Bitter now HAS a clean germination path - update farming.json's notes/meta"


def test_sour_vault_dial_excludes_plain_contamination():
    """Regression guard for the 2026-07-27 fix: Layout F used to list
    Warm as equally valid alongside Hot for Sour's own Vault - but Warm
    is also inside Plainkorn's own accepted temperature range, and Plain
    has no fertilizer requirement of its own to exclude via Sour's own
    Carbonic Fertilizer, so a Spacekorn seed planted under Warm there had
    a real chance of sprouting Plain instead. Hot excludes both Plain and
    Woolly at zero cost to Sour's own numbers (no temperature-triggered
    enrichment of its own)."""
    api = Api()
    layouts = api.get_farming_layouts()
    assert layouts["F"]["dial"]["temperature"] == ["Hot"]


def test_d_mix_dial_is_documented_as_mutually_ambiguous():
    """Regression guard: Layout D-mix's own Warm dial lets BOTH
    Plainkorn's and SourEinkorn's gates pass at every cell (Plain has no
    fertilizer requirement to exclude via Sour's own mandatory Carbonic),
    so the deterministic-looking stripe it draws is not actually
    achievable by live growing - see its own note and _meta.
    germination_ambiguity. This pins the underlying fact down: if a data
    change ever makes D-mix's own pairing clean, its note (which
    currently says the opposite) needs rewriting, not just this test."""
    api = Api()
    crops = api.get_farming_crops()
    layouts = api.get_farming_layouts()
    variants_by_id = {v["id"]: v for crop in crops for v in crop["variants"]}
    lay = layouts["D-mix"]
    dt, dl = lay["dial"]["temperature"][0], lay["dial"]["light"][0]
    ferts = set(variants_by_id["SourEinkorn"]["fertilizer_required"])
    assert _gate_passes(variants_by_id["Plainkorn"], dt, dl, ferts)
    assert _gate_passes(variants_by_id["SourEinkorn"], dt, dl, ferts)
