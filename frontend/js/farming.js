/* Farming screen: a "what do I need to set up to grow X" reference for the
 * Xenic Farm's crop variants (Rockwood Nut / Spacekorn). Data comes from
 * game_data_extract/farming.json (backend/farming.py's get_farming_crops),
 * hand-transcribed from the sibling shipbuilder repo's game_logic_notes.md
 * Findings 13/14/16/17/18 - see that file for the original
 * decompile-sourced tables.
 *
 * Harvest model (Finding 18, see farming.json's _meta.harvest_mechanism):
 * fruit/byproduct are NOT repeating post-maturity cycles - both accumulate
 * while the plant grows and pay out once, at harvest, after which the plot
 * is empty again. So the card's calculator shows growth TIME plus per-
 * harvest YIELD counts, not three parallel "cycle" durations, and toggles
 * feed four accumulators with the game's own attribute semantics
 * (_meta.effects): all_speed shortens growth without changing yield,
 * growth_speed_mult trades time against yield 1:1, fruit_qty/byproduct_qty
 * scale only the counts.
 *
 * Deliberately goal-first, not state-first: an earlier version of this tab
 * had the player pick a Temperature/Light dial pair and highlighted which
 * variants that state happens to produce - backwards from how a player
 * actually thinks ("I want Dreamwood Fruit, what do I set the farm to?"),
 * not "I've set the farm to X, what does that give me?". So each variant
 * card now leads with a plain Requirements checklist (dial positions,
 * fertilizer, neighbor restriction) rather than gate values to be checked
 * against some picked state, and the goal-search box at top jumps straight
 * to the card for a typed fruit/byproduct/variant name. The crop tabs below
 * it stay for open-ended browsing (only 2 crops - a full switch, not a
 * filter within one list).
 *
 * Read-only by design, same rationale as js/sources.js/js/wrecks.js: this
 * is derived game data, not something the player logs themselves.
 */
(function () {
  const goalSearchInput = document.getElementById("farming-goal-search");
  const cropTabRockwood = document.getElementById("farming-crop-rockwood");
  const cropTabSpacekorn = document.getElementById("farming-crop-spacekorn");
  const infoRowEl = document.getElementById("farming-info-row");
  const variantsEl = document.getElementById("farming-variants");

  const modeReferenceBtn = document.getElementById("farming-mode-reference");
  const modeLayoutsBtn = document.getElementById("farming-mode-layouts");
  const referenceViewEl = document.getElementById("farming-reference-view");
  const layoutsViewEl = document.getElementById("farming-layouts-view");
  const layoutsGoalGroupEl = document.getElementById("farming-layouts-goal-group");
  const layoutsVariantSelect = document.getElementById("farming-layouts-variant-select");
  const layoutsResultEl = document.getElementById("farming-layouts-result");

  let cropsData = null; // {rockwood: crop, spacekorn: crop}, fetched once
  let layoutsData = null; // {A: layout, B: layout, ...}, fetched once
  // variant "id" (e.g. "Dreamwood") -> {cropId, variant} - built once
  // alongside cropsData, same rationale as goalIndex below but keyed by the
  // variant's own farming.json id rather than every label a player might
  // type, since the Layouts picker addresses a variant directly.
  let variantById = null;
  let currentFarmingMode = "reference";
  let currentLayoutsGoal = "overall";
  let currentCrop = "spacekorn";
  // label (fruit/byproduct/variant name, lowercased) -> {cropId, variant} -
  // built once alongside cropsData so the goal search can jump to a variant
  // by anything the player might actually type, not just its own name (a
  // player wanting "Dreamwood Fruit" has no reason to already know that's
  // produced by "Rockwood Dream"). goalLabels keeps the original casing,
  // separately, purely for what the dropdown displays.
  let goalIndex = null;
  let goalLabels = null;

  // "44h 19m" instead of a raw decimal-hour fraction like "44.31h" - reads
  // as an actual duration rather than a number needing conversion in your
  // head. Rounding to whole minutes also sidesteps float noise from
  // summing/dividing base ranges (e.g. 57.6 + 28 + 1.1 landing on
  // 86.69999999999999 instead of 86.7).
  function fmtDuration(hours) {
    const totalMinutes = Math.round(hours * 60);
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    if (h === 0) return `${m}m`;
    if (m === 0) return `${h}h`;
    return `${h}h ${m}m`;
  }

  function fmtRange(range) {
    if (!range) return "";
    const [lo, hi] = range;
    return lo === hi ? fmtDuration(lo) : `${fmtDuration(lo)} - ${fmtDuration(hi)}`;
  }

  // Temperature dial chips read like js/galaxy.js's climate chips (filled
  // pill, color+text label carries meaning on its own) - see
  // components.css's own comment on .chip-cold/.chip-temperate/.chip-warm/
  // .chip-scorching for why these are separate classes from the planet-
  // climate ones despite sharing hues.
  const TEMP_CHIP_CLASS = {
    Cold: "chip-cold",
    Temperate: "chip-temperate",
    Warm: "chip-warm",
    Hot: "chip-scorching",
  };

  // Light dial chips read like js/galaxy.js's SUN_CHIPS (outlined pill +
  // a leading glyph baked into the label text, not color alone) - same
  // rationale, see components.css's .chip-lighting comment.
  const LIGHT_CHIP = {
    UV: { cls: "chip-lighting chip-light-uv", label: "✦ UV" },
    Natural: { cls: "chip-lighting chip-light-natural", label: "☀ Natural" },
    Dark: { cls: "chip-lighting chip-light-dark", label: "☾ Dark" },
  };

  // Background tint per grown variant/"species" (its own farming.json
  // "id", e.g. "Dreamwood" for Rockwood Dream) so same-crop cards read
  // apart from each other at a glance even when they share a bio-tag -
  // see theme.css's --species-* comment.
  const SPECIES_CLASS = {
    Rockwood: "species-rockwood",
    Whitewood: "species-whitewood",
    Dreamwood: "species-dreamwood",
    Glowwood: "species-glowwood",
    Sulfwood: "species-sulfwood",
    Plainkorn: "species-plainkorn",
    SourEinkorn: "species-soureinkorn",
    ChillyEinkorn: "species-chillyeinkorn",
  };

  // Left-border accent + bio-tag badge color, independent of species above
  // - the tag itself already matters gameplay-wise (it's what OTHER
  // variants' own neighbor restrictions check against - see the tooltip
  // below), so it's worth surfacing even though several variants share
  // one (species tint is what tells those apart).
  const BIO_TAG_CLASS = {
    Reclusive: "tag-reclusive",
    Invasive: "tag-invasive",
    Putrescent: "tag-putrescent",
  };

  // Shown as a tooltip on every bio-tag pill (the header badge, a
  // Requirements Neighbor line, an enrichment's "Neighbor tagged X" chip -
  // see makeBioTagChip below) - what the tag itself actually does, not
  // just "this matters to neighbors" (the old, vaguer header-only tooltip).
  const BIO_TAG_DESCRIPTION = {
    Reclusive:
      "Reclusive: can't grow if a Reclusive-tagged plant is in an adjacent plot.",
    Invasive:
      "Invasive: on maturing, may spread a copy of itself onto an adjacent plot - 50% chance if it's empty, 25% if it holds a germinating seed or dead plant, never onto an already-grown neighbor.",
    Putrescent:
      "Putrescent: several other variants gain a bonus (or, for Woolly Spacekorn, can't grow at all) when a Putrescent-tagged plant is in an adjacent plot.",
  };

  function makeChip(label, cls) {
    const chip = document.createElement("span");
    chip.className = `chip ${cls}`;
    chip.textContent = label;
    return chip;
  }

  // The same small pill used for a variant's own bio-tag badge (see
  // renderVariantCard) - reused here wherever a bio-tag name appears in
  // generated text (a neighbor restriction, an enrichment condition)
  // instead of the plain tag name as a text string, so "Putrescent"/
  // "Reclusive"/"Invasive" reads (and hovers) identically everywhere on a
  // card.
  function makeBioTagChip(tag) {
    const chip = document.createElement("span");
    chip.className = "farming-bio-tag" + (BIO_TAG_CLASS[tag] ? ` ${BIO_TAG_CLASS[tag]}` : "");
    chip.textContent = tag;
    chip.title = BIO_TAG_DESCRIPTION[tag] || "";
    return chip;
  }

  // A gate's own list IS the set of dial positions that satisfy it - empty
  // normally means unconstrained (Spacekorn's absent-key encoding, per
  // game_logic_notes.md Finding 14's own note), rendered as one neutral
  // "Any" chip rather than one per possible dial position, since every
  // position already satisfies it. Rockwood Glow's temperature/light are
  // the one exception: empty there means the OPPOSITE (a present literal
  // 0, which can never pass the check - see farming.json's own
  // _meta.unreachable) - callers pass impossible=true for that case, which
  // renders a "Never" chip instead of silently claiming "Any" for a gate
  // that actually can't ever be satisfied.
  function makeDialChips(values, kind, impossible) {
    const wrap = document.createElement("span");
    wrap.className = "farming-req-chips";
    if (impossible) {
      wrap.appendChild(makeChip("✗ Never", "chip-impossible"));
      return wrap;
    }
    if (!values || !values.length) {
      wrap.appendChild(makeChip("Any", "chip-any"));
      return wrap;
    }
    for (const v of values) {
      if (kind === "temp") {
        wrap.appendChild(makeChip(v, TEMP_CHIP_CLASS[v] || "chip-any"));
      } else {
        const spec = LIGHT_CHIP[v];
        wrap.appendChild(makeChip(spec ? spec.label : v, spec ? spec.cls : "chip-any"));
      }
    }
    return wrap;
  }

  function makeReqLine(label, contentEl) {
    const line = document.createElement("div");
    line.className = "farming-req-line";
    const labelEl = document.createElement("span");
    labelEl.className = "farming-req-label";
    labelEl.textContent = label;
    line.appendChild(labelEl);
    line.appendChild(contentEl);
    return line;
  }

  function makeReqText(text) {
    const span = document.createElement("span");
    span.className = "farming-req-text";
    span.textContent = text;
    return span;
  }

  // "No [Reclusive] neighbor plant", mixing the bio-tag pill into the
  // sentence rather than spelling the tag out as plain text - every
  // farming.json neighbor_restriction_tag follows this exact "No X-tagged
  // neighbor plant" shape (see Findings 13/14), so building it from the
  // tag name alone avoids parsing a pre-formatted string back apart.
  function makeNeighborRestriction(tag) {
    if (!tag) return makeReqText("none");
    const wrap = document.createElement("span");
    wrap.className = "farming-req-chips";
    wrap.appendChild(document.createTextNode("No "));
    wrap.appendChild(makeBioTagChip(tag));
    wrap.appendChild(document.createTextNode(" neighbor plant"));
    return wrap;
  }

  // A multi-item fertilizer_required list is AND (every listed item must be
  // present simultaneously - a plot/slot can hold up to 3 at once) per
  // game_logic_notes.md Finding 13's own disassembly-verified correction
  // (an earlier pass through that data had mistakenly called it OR).
  // fertilizer_forbidden stays OR-to-fail (any one present blocks) either
  // way, which is just what "forbidden" means for a deny-list.
  function fmtFertilizerRequirement(variant) {
    const req = variant.fertilizer_required || [];
    const forbid = variant.fertilizer_forbidden || [];
    const parts = [];
    if (req.length) {
      parts.push(req.join(" and "));
    } else {
      parts.push("none required");
    }
    if (forbid.length) {
      parts.push(`${forbid.join(", ")} forbidden`);
    }
    return parts.join(" · ");
  }

  // Reads every currently-checked toggle inside this card (both the
  // variant's own enrichments and any neighbor_effects - see farming.json's
  // _meta.effects) and recomputes/repaints the harvest box from them. The
  // DOM's own checked state IS the source of truth here (no parallel JS
  // state to keep in sync) - INPUT_EFFECTS maps each input straight to the
  // effects array it was built from.
  const INPUT_EFFECTS = new WeakMap();

  // The four accumulators mirror the game's own attribute semantics
  // (farming.json's _meta.effects, disassembly-verified in Finding 18):
  // additive attrs sum (two +50%s make +100%), growth_speed_mult
  // multiplies (two ×0.8s make ×0.64).
  function collectEffects(card) {
    const acc = { all_speed: 0, growth_speed_mult: 1, fruit_qty: 0, byproduct_qty: 0 };
    let anyChecked = false;
    for (const input of card.querySelectorAll(".farming-toggle-input:checked")) {
      anyChecked = true;
      for (const e of INPUT_EFFECTS.get(input) || []) {
        if (e.attr === "growth_speed_mult") acc.growth_speed_mult *= e.value;
        else acc[e.attr] += e.value;
      }
    }
    return { acc, anyChecked };
  }

  // Growth time = base / ((1 + all_speed) * growth_speed_mult) - the
  // game's growth-progress rate, inverted into a duration.
  function growthRange(variant, acc) {
    const rate = (1 + acc.all_speed) * acc.growth_speed_mult;
    return variant.growth_hours.map((v) => v / rate);
  }

  // Per-harvest yield = ceil(growth_duration * (1 + qty_bonus) /
  // (per_item_duration * growth_speed_mult)) - the game accrues product
  // progress all through growth and converts it to items in one lump at
  // harvest (ceil of a positive value, so never 0). all_speed cancels out
  // (it scales growth and product accrual equally); growth_speed_mult sits
  // in the denominator (slower metabolic growth = MORE items per harvest -
  // the game's own "Productive Metabolic Speed" tradeoff). Both durations
  // are independent uniform rolls, so the honest range pairs each
  // extreme: min = shortest growth with slowest per-item timer, max the
  // opposite.
  function yieldRange(variant, cycleField, qtyBonus, acc) {
    const [gLo, gHi] = variant.growth_hours;
    const [cLo, cHi] = variant[cycleField];
    const k = (1 + qtyBonus) / acc.growth_speed_mult;
    return [Math.ceil((gLo / cHi) * k), Math.ceil((gHi / cLo) * k)];
  }

  // Plain item counts ("3 - 5"), deliberately NOT "×3 - ×5" - a ×-prefixed
  // number next to modifier toggles reads as a multiplication factor, when
  // this is the actual number of items handed over at gather.
  function fmtCount(range) {
    const [lo, hi] = range;
    return lo === hi ? `${lo}` : `${lo} - ${hi}`;
  }

  const HARVEST_ROWS = [
    ["growth", "Growth"],
    ["fruit", "Fruit at gather"],
    ["byproduct", "Byproduct at gather"],
  ];

  // Pure {growth, fruit, byproduct} -> [base, adjusted] computation, shared
  // by the Reference card's live calculator (updateHarvest, DOM-driven) and
  // the Layouts view (below, driven by a goal_preset's toggle_ids instead
  // of checkbox state) - one formula, two ways of choosing which bonuses
  // are active, so the two views can never disagree with each other.
  function computeHarvestValues(variant, acc) {
    const base = { all_speed: 0, growth_speed_mult: 1, fruit_qty: 0, byproduct_qty: 0 };
    return {
      growth: [fmtRange(variant.growth_hours), fmtRange(growthRange(variant, acc))],
      fruit: [
        fmtCount(yieldRange(variant, "fruit_cycle_hours", 0, base)),
        fmtCount(yieldRange(variant, "fruit_cycle_hours", acc.fruit_qty, acc)),
      ],
      byproduct: [
        fmtCount(yieldRange(variant, "byproduct_cycle_hours", 0, base)),
        fmtCount(yieldRange(variant, "byproduct_cycle_hours", acc.byproduct_qty, acc)),
      ],
    };
  }

  // Each row always leads with the unmodified base; once toggles change a
  // number it becomes "base → current" in the value itself (not a small
  // side note) - the base amount is the anchor the modifier only makes
  // sense against. A row whose value the checked toggles DON'T change
  // (e.g. yields under a pure Growth & Production speed bonus, which
  // cancels out of the yield formula) just keeps showing the single base
  // figure - itself informative: that toggle doesn't change this number.
  function updateHarvest(card, variant, harvestEls) {
    const { acc } = collectEffects(card);
    const values = computeHarvestValues(variant, acc);
    for (const [key] of HARVEST_ROWS) {
      const [baseText, adjusted] = values[key];
      harvestEls[key].valueEl.textContent =
        adjusted === baseText ? baseText : `${baseText} → ${adjusted}`;
    }
  }

  function makeHarvestBox(variant) {
    const box = document.createElement("div");
    box.className = "farming-timing-box";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-timing-label";
    labelEl.textContent = "Harvest";
    labelEl.title =
      "Fruit and byproduct build up while the plant grows and are all handed over at once when it's gathered - the plot is empty again afterwards. Counts only include time the plant's requirements were actually met.";
    box.appendChild(labelEl);

    const harvestEls = {};
    for (const [key, label] of HARVEST_ROWS) {
      const row = document.createElement("div");
      row.className = "farming-timing-row";
      const statEl = document.createElement("span");
      statEl.className = "farming-timing-stat";
      statEl.textContent = label;
      row.appendChild(statEl);
      const valueEl = document.createElement("span");
      valueEl.className = "farming-timing-value";
      row.appendChild(valueEl);
      box.appendChild(row);
      harvestEls[key] = { valueEl };
    }

    return { box, harvestEls };
  }

  // Toggle inputs that share a dial_group are mutually exclusive (checking
  // one unchecks any other sibling in the same group before recomputing) -
  // the farm only has one Temperature and one Light position at a time,
  // so e.g. a variant's own "Light dial = UV" enrichment and a "Neighboring
  // Rockwood Glow" neighbor_effect (which mirrors being UV-lit) can't both
  // apply at once even though they're rendered in different sections. See
  // farming.json's _meta.effects for the full rationale.
  function makeToggleInput(variantKey, entry) {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "farming-toggle-input";
    INPUT_EFFECTS.set(input, entry.effects);
    if (entry.dial_group) {
      input.dataset.dialGroup = `${variantKey}|${entry.dial_group}`;
    }
    return input;
  }

  function wireToggleInput(input, card, variant, harvestEls) {
    input.addEventListener("change", () => {
      if (input.checked && input.dataset.dialGroup) {
        for (const sibling of card.querySelectorAll(
          `.farming-toggle-input[data-dial-group="${input.dataset.dialGroup}"]`
        )) {
          if (sibling !== input) sibling.checked = false;
        }
      }
      updateHarvest(card, variant, harvestEls);
    });
  }

  function makeSection(label, lines) {
    const section = document.createElement("div");
    section.className = "farming-variant-section";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-variant-section-label";
    labelEl.textContent = label;
    section.appendChild(labelEl);
    const list = document.createElement("ul");
    for (const line of lines) {
      const li = document.createElement("li");
      li.textContent = line;
      list.appendChild(li);
    }
    section.appendChild(list);
    return section;
  }

  // Enrichments gated by the variant's own Temperature/Light dial (see
  // farming.json's _meta.enrichment_trigger) render with the same dial
  // chip(s) used in Requirements instead of the plain condition text -
  // everything else (fertilizer/neighbor-tag conditions have no
  // "trigger") falls back to plain text, since there's no established
  // chip style for those.
  //
  // An entry with an "effects" array (see farming.json's _meta.effects)
  // gets a checkbox that feeds the Per-harvest box above - toggling it
  // live-recomputes growth time AND the fruit/byproduct yield counts
  // (quantity bonuses are toggleable too now that yields are modeled, not
  // just cycle times). An entry without one (currently only the dead-code
  // UV byproduct malus, described in prose) stays plain text.
  // Dial-triggered rows lead, Temperature before Light - the same order
  // as the Requirements lines above the box - then everything else
  // (fertilizer/neighbor-tag) in data order. A stable sort, so entries
  // within the same group keep farming.json's own ordering.
  const TRIGGER_ORDER = { temp: 0, light: 1 };

  function enrichmentSortRank(e) {
    return e.trigger && e.trigger.kind in TRIGGER_ORDER ? TRIGGER_ORDER[e.trigger.kind] : 2;
  }

  function makeEnrichmentSection(label, enrichments, variantKey, card, variant, harvestEls) {
    const section = document.createElement("div");
    section.className = "farming-variant-section";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-variant-section-label";
    labelEl.textContent = label;
    section.appendChild(labelEl);
    const list = document.createElement("ul");
    const ordered = [...enrichments].sort((a, b) => enrichmentSortRank(a) - enrichmentSortRank(b));
    for (const e of ordered) {
      const li = document.createElement("li");
      li.className = "farming-bonus-line";

      const conditionEl = document.createElement("span");
      conditionEl.className = "farming-bonus-condition";
      if (e.trigger && (e.trigger.kind === "temp" || e.trigger.kind === "light")) {
        conditionEl.appendChild(makeDialChips(e.trigger.values, e.trigger.kind));
      } else if (e.trigger && e.trigger.kind === "neighbor_tag") {
        conditionEl.appendChild(makeReqText("Neighbor tagged"));
        conditionEl.appendChild(makeBioTagChip(e.trigger.values[0]));
      } else {
        conditionEl.appendChild(makeReqText(e.condition));
      }

      if (e.effects) {
        const inputEntry = { effects: e.effects, dial_group: e.dial_group };
        const input = makeToggleInput(variantKey, inputEntry);
        const toggleLabel = document.createElement("label");
        toggleLabel.className = "farming-toggle-label";
        toggleLabel.appendChild(input);
        toggleLabel.appendChild(conditionEl);
        li.appendChild(toggleLabel);
        wireToggleInput(input, card, variant, harvestEls);
      } else {
        li.appendChild(conditionEl);
      }

      li.appendChild(makeEffectCell(e));
      list.appendChild(li);
    }
    section.appendChild(list);
    return section;
  }

  // Arrow + effect text for a bonus row. An entry's optional
  // "effect_note" (farming.json) holds the longer aside that used to
  // live inline in the effect string - shown as a hover tooltip (dotted
  // underline as the cue, same title-tooltip pattern as the bio-tag
  // pills) so the row itself stays one readable line.
  function makeEffectCell(entry) {
    const frag = document.createDocumentFragment();
    const arrowEl = document.createElement("span");
    arrowEl.className = "farming-bonus-arrow";
    arrowEl.textContent = "→";
    frag.appendChild(arrowEl);
    const effectEl = document.createElement("span");
    effectEl.className = "farming-bonus-effect";
    effectEl.textContent = entry.effect;
    if (entry.effect_note) {
      effectEl.classList.add("has-note");
      effectEl.title = entry.effect_note;
    }
    frag.appendChild(effectEl);
    return frag;
  }

  // Cross-variant bonuses (farming.json's own "neighbor_effects" -
  // currently just Spacekorn Plain's self-buff from a neighboring Plain,
  // and Rockwood Glow's "neighbor treated as UV-lit" mirrored onto
  // whichever variants have their own Light=UV enrichment) - same
  // "condition → effect" row shape as makeEnrichmentSection, including
  // the effect prose (an earlier version showed only the label, leaving
  // the toggle description-less - what does a Glow neighbor DO to me? -
  // so farming.json now carries an "effect" line for these too).
  function makeNeighborEffectsSection(neighborEffects, variantKey, card, variant, harvestEls) {
    const section = document.createElement("div");
    section.className = "farming-variant-section";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-variant-section-label";
    labelEl.textContent = "Neighbor conditions that also affect the harvest:";
    section.appendChild(labelEl);
    const list = document.createElement("ul");
    for (const ne of neighborEffects) {
      const li = document.createElement("li");
      li.className = "farming-bonus-line";
      const input = makeToggleInput(variantKey, ne);
      const toggleLabel = document.createElement("label");
      toggleLabel.className = "farming-toggle-label";
      toggleLabel.appendChild(input);
      toggleLabel.appendChild(makeReqText(ne.label));
      li.appendChild(toggleLabel);
      wireToggleInput(input, card, variant, harvestEls);
      li.appendChild(makeEffectCell(ne));
      list.appendChild(li);
    }
    section.appendChild(list);
    return section;
  }

  function renderVariantCard(cropId, variant) {
    const card = document.createElement("div");
    const speciesClass = SPECIES_CLASS[variant.id];
    const tagClass = variant.bio_tag ? BIO_TAG_CLASS[variant.bio_tag] : null;
    card.className =
      "farming-variant-card" +
      (speciesClass ? ` ${speciesClass}` : "") +
      (tagClass ? ` ${tagClass}` : "");
    const variantKey = `${cropId}:${variant.id}`;
    card.dataset.variantKey = variantKey;

    const header = document.createElement("div");
    header.className = "farming-variant-header";
    const nameEl = document.createElement("span");
    nameEl.className = "farming-variant-name";
    nameEl.textContent = variant.name;
    header.appendChild(nameEl);
    if (variant.bio_tag) {
      header.appendChild(makeBioTagChip(variant.bio_tag));
    }
    card.appendChild(header);

    if (variant.unreachable) {
      const warningEl = document.createElement("div");
      warningEl.className = "farming-unreachable-warning";
      warningEl.textContent = variant.unreachable_note;
      card.appendChild(warningEl);
    }

    const producesEl = document.createElement("div");
    producesEl.className = "farming-variant-produces";
    producesEl.textContent = `Produces: ${variant.fruit} (fruit) · ${variant.byproduct} (byproduct)`;
    card.appendChild(producesEl);

    if (variant.note) {
      const noteEl = document.createElement("div");
      noteEl.className = "farming-variant-note";
      noteEl.textContent = variant.note;
      card.appendChild(noteEl);
    }

    const reqSection = document.createElement("div");
    reqSection.className = "farming-variant-section";
    const reqLabelEl = document.createElement("div");
    reqLabelEl.className = "farming-variant-section-label";
    reqLabelEl.textContent = "Requirements to grow it:";
    reqSection.appendChild(reqLabelEl);
    reqSection.appendChild(
      makeReqLine("Temperature", makeDialChips(variant.temperature, "temp", variant.unreachable))
    );
    reqSection.appendChild(
      makeReqLine("Light", makeDialChips(variant.light, "light", variant.unreachable))
    );
    reqSection.appendChild(makeReqLine("Fertilizer", makeReqText(fmtFertilizerRequirement(variant))));
    reqSection.appendChild(makeReqLine("Neighbor", makeNeighborRestriction(variant.neighbor_restriction_tag)));
    card.appendChild(reqSection);

    // Built before the toggle sections below (which need harvestEls to wire
    // their change handlers into) but appended here, right under
    // Requirements, so the numbers it live-updates stay prominent and
    // above-the-fold rather than buried under every modifier.
    const { box: harvestBox, harvestEls } = makeHarvestBox(variant);
    card.appendChild(harvestBox);
    updateHarvest(card, variant, harvestEls);

    if (variant.enrichments && variant.enrichments.length) {
      card.appendChild(
        makeEnrichmentSection(
          "Speed & yield modifiers:",
          variant.enrichments,
          variantKey,
          card,
          variant,
          harvestEls
        )
      );
    }
    if (variant.neighbor_effects && variant.neighbor_effects.length) {
      card.appendChild(
        makeNeighborEffectsSection(variant.neighbor_effects, variantKey, card, variant, harvestEls)
      );
    }
    if (variant.adjacency && variant.adjacency.length) {
      card.appendChild(makeSection("Effect on neighboring plants:", variant.adjacency));
    }

    return card;
  }

  function render() {
    const crop = cropsData[currentCrop];
    if (!crop) return;

    infoRowEl.innerHTML = "";
    const infoLine = document.createElement("div");
    infoLine.textContent = `Seed: ${crop.seed_name}  ·  Germinates in ${fmtRange(
      crop.germination_hours
    )} (needs ${crop.germination_needs})`;
    infoRowEl.appendChild(infoLine);

    variantsEl.innerHTML = "";
    for (const variant of crop.variants) {
      variantsEl.appendChild(renderVariantCard(currentCrop, variant));
    }
  }

  function setCrop(cropId) {
    currentCrop = cropId;
    cropTabRockwood.classList.toggle("active", cropId === "rockwood");
    cropTabSpacekorn.classList.toggle("active", cropId === "spacekorn");
    render();
  }

  function buildGoalIndex() {
    goalIndex = new Map();
    // First-seen wins on a collision (e.g. "Spacekorn Seed" is the fruit
    // of both Spacekorn Plain and Spacekorn Sour) - searching that exact
    // name lands on whichever variant is listed first for its crop; the
    // other is still reachable by browsing the crop tab directly.
    for (const cropId of Object.keys(cropsData)) {
      for (const variant of cropsData[cropId].variants) {
        for (const label of [variant.name, variant.fruit, variant.byproduct]) {
          const key = label.toLowerCase();
          if (!goalIndex.has(key)) goalIndex.set(key, { cropId, variant, label });
        }
      }
    }
    goalLabels = [...goalIndex.values()].map((e) => e.label).sort((a, b) => a.localeCompare(b));
  }

  function jumpToVariant(entry) {
    if (currentCrop !== entry.cropId) setCrop(entry.cropId);
    const card = variantsEl.querySelector(
      `[data-variant-key="${entry.cropId}:${entry.variant.id}"]`
    );
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("flash");
    // Force reflow so re-adding the class restarts the animation if the
    // same card is jumped to twice in a row.
    void card.offsetWidth;
    card.classList.add("flash");
  }

  function resolveGoalQuery(query) {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    if (goalIndex.has(q)) return goalIndex.get(q);
    for (const [label, entry] of goalIndex) {
      if (label.includes(q)) return entry;
    }
    return null;
  }

  function onGoalCommit() {
    const entry = resolveGoalQuery(goalSearchInput.value);
    if (entry) jumpToVariant(entry);
  }

  // ---- Layouts view (frontend/js/farming.js's second mode) ----
  //
  // A goal+variant picker over the same 5x3 plot layouts worked out
  // alongside the Reference tab's per-variant calculator (see
  // farming.json's own _meta.goal_presets_and_layouts): each variant names,
  // per (rate|harvest) framing and (overall|fruit_only|byproduct_only)
  // goal, which of its OWN toggle ids to check and which layout grid that
  // implies. Numbers shown here are computed straight from those same ids
  // through computeHarvestValues (the exact pure formula the Reference
  // card's own checkboxes drive) - not a jump-and-click-through to the
  // other tab, and not a second, hand-maintained set of figures either.

  // Short 3-letter tags for a layout board's cells - purely a legend/board
  // label, matches the variant's own display name closely enough to read
  // at the small board size a 5x3 grid gets in this window.
  const LAYOUT_CELL_ABBR = {
    Rockwood: "GRN",
    Whitewood: "WHT",
    Dreamwood: "DRM",
    Sulfwood: "BTR",
    Plainkorn: "PLN",
    SourEinkorn: "SOR",
    ChillyEinkorn: "WLY",
  };

  function renderLayoutBoard(layout) {
    const board = document.createElement("div");
    board.className = "farming-layout-board";
    for (const row of layout.grid) {
      for (const cellId of row) {
        const cell = document.createElement("div");
        cell.className = "farming-layout-cell";
        if (cellId) {
          const speciesClass = SPECIES_CLASS[cellId];
          if (speciesClass) cell.classList.add(speciesClass);
          const entry = variantById.get(cellId);
          cell.textContent = LAYOUT_CELL_ABBR[cellId] || cellId.slice(0, 3).toUpperCase();
          cell.title = entry ? entry.variant.name : cellId;
        } else {
          cell.classList.add("farming-layout-cell-empty");
        }
        board.appendChild(cell);
      }
    }
    return board;
  }

  // One row per distinct variant actually present on the board - reads the
  // grid itself rather than duplicating a variant list in farming.json, so
  // it can never drift from what renderLayoutBoard just drew.
  function renderLayoutLegend(layout) {
    const wrap = document.createElement("div");
    wrap.className = "farming-layout-legend";
    const seen = new Set();
    for (const row of layout.grid) {
      for (const cellId of row) {
        if (!cellId || seen.has(cellId)) continue;
        seen.add(cellId);
        const entry = variantById.get(cellId);
        if (!entry) continue;
        const item = document.createElement("div");
        item.className = "farming-layout-legend-item";
        const swatch = document.createElement("span");
        swatch.className = "farming-layout-swatch " + (SPECIES_CLASS[cellId] || "");
        item.appendChild(swatch);
        const text = document.createElement("span");
        text.textContent = `${entry.variant.name} → ${entry.variant.fruit} + ${entry.variant.byproduct}`;
        item.appendChild(text);
        wrap.appendChild(item);
      }
    }
    return wrap;
  }

  // Same accumulator shape collectEffects(card) builds from checked DOM
  // inputs, but built straight from a goal_preset's toggle_ids against the
  // variant's own enrichments/neighbor_effects - no card, no checkboxes,
  // same four-attribute math (farming.json's own _meta.effects).
  function collectEffectsForIds(variant, toggleIds) {
    const acc = { all_speed: 0, growth_speed_mult: 1, fruit_qty: 0, byproduct_qty: 0 };
    const sources = [...(variant.enrichments || []), ...(variant.neighbor_effects || [])];
    for (const entry of sources) {
      if (!entry.id || !toggleIds.includes(entry.id)) continue;
      for (const e of entry.effects || []) {
        if (e.attr === "growth_speed_mult") acc.growth_speed_mult *= e.value;
        else acc[e.attr] += e.value;
      }
    }
    return acc;
  }

  // Same visual shape as the Reference card's own harvest box
  // (makeHarvestBox/HARVEST_ROWS) so a number reads identically in both
  // places - built fresh each render rather than reused, since there's no
  // live checkbox state to update in place here.
  function renderPresetHarvestBox(variant, toggleIds) {
    const values = computeHarvestValues(variant, collectEffectsForIds(variant, toggleIds));
    const box = document.createElement("div");
    box.className = "farming-timing-box";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-timing-label";
    labelEl.textContent = "Harvest with this setup";
    box.appendChild(labelEl);
    for (const [key, label] of HARVEST_ROWS) {
      const [baseText, adjusted] = values[key];
      const row = document.createElement("div");
      row.className = "farming-timing-row";
      const statEl = document.createElement("span");
      statEl.className = "farming-timing-stat";
      statEl.textContent = label;
      row.appendChild(statEl);
      const valueEl = document.createElement("span");
      valueEl.className = "farming-timing-value";
      valueEl.textContent = adjusted === baseText ? baseText : `${baseText} → ${adjusted}`;
      row.appendChild(valueEl);
      box.appendChild(row);
    }
    return box;
  }

  // Orthogonal, bounds-checked grid neighbors of (r, c) in a `grid.length`
  // x `grid[0].length` board - same adjacency CraftMap's own layouts use
  // everywhere else (Finding 19's adjacency model).
  function gridNeighborCells(grid, r, c) {
    const rows = grid.length;
    const cols = grid[0].length;
    const out = [];
    if (r > 0) out.push(grid[r - 1][c]);
    if (r < rows - 1) out.push(grid[r + 1][c]);
    if (c > 0) out.push(grid[r][c - 1]);
    if (c < cols - 1) out.push(grid[r][c + 1]);
    return out;
  }

  // Per-CELL accumulator, unlike collectEffectsForIds' blanket one: a
  // dial/fertilizer toggle (no trigger, or trigger.kind temp/light) always
  // applies - the whole farm shares one dial and a fertilizer choice is
  // uniform across every plot of a variant - but a neighbor-conditioned
  // toggle (trigger.kind neighbor_tag or neighbor_variant) only applies if
  // one of THIS cell's actual grid neighbors satisfies it. Needed for any
  // layout where coverage isn't uniform across every counted cell -
  // checkerboard/solid layouts give the same answer either way, since
  // there every counted cell's neighbor profile is identical.
  function collectEffectsForCell(variant, toggleIds, neighborVariantIds) {
    const acc = { all_speed: 0, growth_speed_mult: 1, fruit_qty: 0, byproduct_qty: 0 };
    const neighborBioTags = neighborVariantIds.map((id) => {
      const entry = variantById.get(id);
      return entry ? entry.variant.bio_tag : null;
    });
    const sources = [...(variant.enrichments || []), ...(variant.neighbor_effects || [])];
    for (const entry of sources) {
      if (!entry.id || !toggleIds.includes(entry.id)) continue;
      const trig = entry.trigger;
      if (trig && trig.kind === "neighbor_tag") {
        if (!neighborBioTags.includes(trig.values[0])) continue;
      } else if (trig && trig.kind === "neighbor_variant") {
        if (!trig.values.some((vid) => neighborVariantIds.includes(vid))) continue;
      }
      for (const e of entry.effects || []) {
        if (e.attr === "growth_speed_mult") acc.growth_speed_mult *= e.value;
        else acc[e.attr] += e.value;
      }
    }
    return acc;
  }

  // The whole reason this feature exists: a layout is picked by FARM
  // TOTAL (per-plant yield times how many plots of this variant the grid
  // actually fits), never by per-plant yield alone - see farming.json's
  // own _meta.per_slot_vs_per_farm for the worked example (Spacekorn
  // Plain) where trusting per-plant numbers alone gave the wrong answer.
  // This box makes that arithmetic visible instead of asking the reader
  // to trust the recommendation blindly. Sums each matching cell's OWN
  // range (collectEffectsForCell, real grid adjacency) rather than
  // multiplying one blanket per-plant number by a count - required for any
  // future sparse/uneven-coverage layout to read correctly; gives the
  // identical answer to a count*single-accumulator shortcut on every
  // uniform-coverage layout (checkerboards, solid packs).
  // Growth time has no farm-total analogue (every plot grows in parallel
  // on its own clock), so only fruit/byproduct appear here.
  function renderFarmTotalBox(variant, toggleIds, layout) {
    const grid = layout.grid;
    let count = 0;
    let fruitLo = 0, fruitHi = 0, byproductLo = 0, byproductHi = 0;
    for (let r = 0; r < grid.length; r++) {
      for (let c = 0; c < grid[r].length; c++) {
        if (grid[r][c] !== variant.id) continue;
        count++;
        const neighborIds = gridNeighborCells(grid, r, c).filter((id) => id != null);
        const acc = collectEffectsForCell(variant, toggleIds, neighborIds);
        const [fLo, fHi] = yieldRange(variant, "fruit_cycle_hours", acc.fruit_qty, acc);
        const [bLo, bHi] = yieldRange(variant, "byproduct_cycle_hours", acc.byproduct_qty, acc);
        fruitLo += fLo; fruitHi += fHi;
        byproductLo += bLo; byproductHi += bHi;
      }
    }

    const box = document.createElement("div");
    box.className = "farming-timing-box farming-farm-total-box";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-timing-label";
    labelEl.textContent = `Farm total (${count} of 15 plots)`;
    box.appendChild(labelEl);

    const rows = [
      ["Fruit, whole farm", fmtCount([fruitLo, fruitHi])],
      ["Byproduct, whole farm", fmtCount([byproductLo, byproductHi])],
    ];
    for (const [label, text] of rows) {
      const row = document.createElement("div");
      row.className = "farming-timing-row";
      const statEl = document.createElement("span");
      statEl.className = "farming-timing-stat";
      statEl.textContent = label;
      row.appendChild(statEl);
      const valueEl = document.createElement("span");
      valueEl.className = "farming-timing-value";
      valueEl.textContent = text;
      row.appendChild(valueEl);
      box.appendChild(row);
    }
    return box;
  }

  // Required fertilizer (always on, regardless of goal) plus whichever
  // optional fertilizer-granting enrichments THIS preset actually turns on
  // (matched by fertilizer_item - see farming.json's own _meta.effects) -
  // the same "what do I load this plot with" question the Reference tab's
  // own Fertilizer requirement line answers, just goal-scoped here instead
  // of listing every possible supplement at once.
  function fmtPresetFertilizer(variant, toggleIds, extraFertilizer) {
    const parts = [];
    if (variant.fertilizer_required && variant.fertilizer_required.length) {
      parts.push(`${variant.fertilizer_required.join(" + ")} (required)`);
    }
    const optional = (variant.enrichments || [])
      .filter((e) => e.fertilizer_item && toggleIds.includes(e.id))
      .map((e) => e.fertilizer_item);
    if (optional.length) parts.push(optional.join(" + "));
    // extraFertilizer (see a layout's own dial_alternates) is a pure
    // germination-safety additive with no enrichment/yield effect of its
    // own for THIS variant - it wouldn't be found by the toggleIds-driven
    // scan above, since there's no toggle for it at all.
    if (extraFertilizer && extraFertilizer.length) parts.push(extraFertilizer.join(" + "));
    if (variant.fertilizer_forbidden && variant.fertilizer_forbidden.length) {
      parts.push(`${variant.fertilizer_forbidden.join(", ")} forbidden`);
    }
    return parts.length ? parts.join(" · ") : "none";
  }

  // Which bio-tag (if any) this preset's neighbor is actually leaned on for
  // - an enrichment with a neighbor_tag trigger (farming.json's own
  // _meta.enrichment_trigger) that's checked "on" in this preset's
  // toggle_ids. Separate from neighbor_restriction_tag below: one is a
  // gate the variant itself imposes on ITS neighbor, the other is a bonus
  // this specific setup collects FROM its neighbor - a variant can have
  // either, both, or neither.
  function findActiveNeighborTagBonus(variant, toggleIds) {
    for (const e of variant.enrichments || []) {
      if (e.trigger && e.trigger.kind === "neighbor_tag" && toggleIds.includes(e.id)) {
        return e.trigger.values[0];
      }
    }
    return null;
  }

  // A layout's own OPTIONAL "dial_alternates" array (currently only Layout
  // F/Sour Vault - see farming.json's own _meta.germination_ambiguity):
  // one or more genuinely equally-good OTHER dial+fertilizer combinations
  // for the SAME grid/toggle_ids, surfaced as their own compact,
  // structured block rather than buried in the layout's free-text note -
  // this is exactly the gap the player flagged (an equivalence documented
  // only in prose never actually reads as "here's a real alternative you
  // can pick"). Each entry names its own dial plus any additional
  // fertilizer item(s) needed ON TOP of the primary setup's own
  // (required + toggled-optional) fertilizer - see fmtPresetFertilizer's
  // own extraFertilizer param.
  function renderDialAlternate(alt, variant, toggleIds) {
    const box = document.createElement("div");
    box.className = "farming-layout-alternate";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-layout-alternate-label";
    labelEl.textContent = "Equally good alternative: " + alt.label;
    box.appendChild(labelEl);
    box.appendChild(makeReqLine("Temperature", makeDialChips(alt.dial.temperature, "temp")));
    box.appendChild(makeReqLine("Light", makeDialChips(alt.dial.light, "light")));
    box.appendChild(
      makeReqLine(
        "Fertilizer",
        makeReqText(fmtPresetFertilizer(variant, toggleIds, alt.extra_fertilizer))
      )
    );
    if (alt.note) {
      const noteEl = document.createElement("div");
      noteEl.className = "farming-layout-note";
      noteEl.textContent = alt.note;
      box.appendChild(noteEl);
    }
    return box;
  }

  function renderPresetPanel(heading, presetEntry, variant) {
    const panel = document.createElement("div");
    panel.className = "farming-layout-panel";
    const head = document.createElement("div");
    head.className = "farming-layout-panel-head";
    head.textContent = heading;
    panel.appendChild(head);

    const layout = layoutsData[presetEntry.layout];
    const nameEl = document.createElement("div");
    nameEl.className = "farming-layout-name";
    nameEl.textContent = layout.label;
    panel.appendChild(nameEl);

    // Same chip/pill vocabulary as the Reference tab's own Requirements
    // block (makeDialChips/makeBioTagChip/makeNeighborRestriction) rather
    // than plain text, so a Temperature/Light/bio-tag reads identically in
    // both views.
    panel.appendChild(makeReqLine("Temperature", makeDialChips(layout.dial.temperature, "temp")));
    panel.appendChild(makeReqLine("Light", makeDialChips(layout.dial.light, "light")));
    panel.appendChild(
      makeReqLine("Fertilizer", makeReqText(fmtPresetFertilizer(variant, presetEntry.toggle_ids)))
    );
    if (variant.neighbor_restriction_tag) {
      panel.appendChild(
        makeReqLine("Neighbor", makeNeighborRestriction(variant.neighbor_restriction_tag))
      );
    }
    const neighborTagBonus = findActiveNeighborTagBonus(variant, presetEntry.toggle_ids);
    if (neighborTagBonus) {
      const bonusEl = document.createElement("span");
      bonusEl.className = "farming-req-chips";
      bonusEl.appendChild(document.createTextNode("Bonus from neighbor tagged "));
      bonusEl.appendChild(makeBioTagChip(neighborTagBonus));
      panel.appendChild(makeReqLine("Neighbor bonus", bonusEl));
    }

    for (const alt of layout.dial_alternates || []) {
      panel.appendChild(renderDialAlternate(alt, variant, presetEntry.toggle_ids));
    }

    panel.appendChild(renderLayoutBoard(layout));
    panel.appendChild(renderLayoutLegend(layout));
    panel.appendChild(renderPresetHarvestBox(variant, presetEntry.toggle_ids));
    panel.appendChild(renderFarmTotalBox(variant, presetEntry.toggle_ids, layout));

    if (layout.note) {
      const noteEl = document.createElement("div");
      noteEl.className = "farming-layout-note";
      noteEl.textContent = layout.note;
      panel.appendChild(noteEl);
    }

    return panel;
  }

  // A goal_presets entry for one (metric, goal) pair is either a normal
  // {layout, toggle_ids} preset, or - only ever seen on Spacekorn Plain's
  // rate/overall - a {no_dominant: true, options: [...]} shape for a
  // genuine Pareto trade-off with no single winner (see farming.json's own
  // _meta.goal_presets_and_layouts). Rendered as its own labeled group of
  // side-by-side options rather than forcing a fake single answer.
  function renderMetricSection(label, presetEntry, variant) {
    if (!presetEntry.no_dominant) {
      return renderPresetPanel(label, presetEntry, variant);
    }
    const section = document.createElement("div");
    section.className = "farming-layout-no-dominant";
    const head = document.createElement("div");
    head.className = "farming-layout-panel-head";
    head.textContent = label;
    section.appendChild(head);
    const note = document.createElement("p");
    note.className = "farming-layout-note";
    note.textContent = presetEntry.note;
    section.appendChild(note);
    for (const option of presetEntry.options) {
      section.appendChild(renderPresetPanel(option.label, option, variant));
    }
    return section;
  }

  function presetsEqual(a, b) {
    const idsA = [...a.toggle_ids].sort();
    const idsB = [...b.toggle_ids].sort();
    return (
      a.layout === b.layout &&
      idsA.length === idsB.length &&
      idsA.every((v, i) => v === idsB[i])
    );
  }

  function renderGoalPresets(variant, goal) {
    const wrap = document.createDocumentFragment();
    const presets = variant.goal_presets;
    if (!presets) {
      const msg = document.createElement("p");
      msg.className = "farming-layout-unavailable";
      msg.textContent = `${variant.name} is unreachable in normal play - there's no real setup to recommend for it.`;
      wrap.appendChild(msg);
      return wrap;
    }
    const ratePreset = presets.rate[goal];
    const harvestPreset = presets.harvest[goal];
    // Several variants recommend the exact same layout+toggles regardless
    // of which framing you're optimizing (Green, Dream, Bitter, Sour,
    // Woolly, and Plain's own harvest table) - merge into one panel rather
    // than showing the same board twice.
    if (!ratePreset.no_dominant && !harvestPreset.no_dominant && presetsEqual(ratePreset, harvestPreset)) {
      wrap.appendChild(
        renderPresetPanel("Same setup for items/hour and items/harvest", ratePreset, variant)
      );
      return wrap;
    }
    wrap.appendChild(renderMetricSection("Items / hour (fastest cycle)", ratePreset, variant));
    wrap.appendChild(
      renderMetricSection("Items / harvest (biggest single haul)", harvestPreset, variant)
    );
    return wrap;
  }

  function renderLayoutsView() {
    layoutsResultEl.innerHTML = "";
    const raw = layoutsVariantSelect.value;
    if (!raw) return;
    const variantId = raw.split(":")[1];
    const entry = variantById.get(variantId);
    if (!entry) return;
    const header = document.createElement("div");
    header.className = "farming-layout-variant-header";
    header.textContent = `${entry.variant.name} → ${entry.variant.fruit} (fruit) · ${entry.variant.byproduct} (byproduct)`;
    layoutsResultEl.appendChild(header);
    layoutsResultEl.appendChild(renderGoalPresets(entry.variant, currentLayoutsGoal));
  }

  function populateLayoutsVariantSelect() {
    layoutsVariantSelect.innerHTML = "";
    for (const cropId of ["spacekorn", "rockwood"]) {
      const crop = cropsData[cropId];
      if (!crop) continue;
      const group = document.createElement("optgroup");
      group.label = cropId === "rockwood" ? "Rockwood Nut" : "Spacekorn";
      for (const variant of crop.variants) {
        // Rockwood Glow has no goal_presets at all - unreachable in normal
        // play (see farming.json's own _meta.unreachable), nothing to
        // recommend a layout for.
        if (variant.unreachable) continue;
        const option = document.createElement("option");
        option.value = `${cropId}:${variant.id}`;
        option.textContent = variant.name;
        group.appendChild(option);
      }
      layoutsVariantSelect.appendChild(group);
    }
  }

  function setFarmingMode(mode) {
    currentFarmingMode = mode;
    modeReferenceBtn.classList.toggle("active", mode === "reference");
    modeLayoutsBtn.classList.toggle("active", mode === "layouts");
    referenceViewEl.classList.toggle("hidden", mode !== "reference");
    layoutsViewEl.classList.toggle("hidden", mode !== "layouts");
    if (mode === "layouts") renderLayoutsView();
  }

  async function ensureDataLoaded() {
    if (cropsData !== null) return;
    const [crops, layouts] = await Promise.all([
      CraftMapApi.call("get_farming_crops"),
      CraftMapApi.call("get_farming_layouts"),
    ]);
    cropsData = {};
    for (const crop of crops) cropsData[crop.id] = crop;
    layoutsData = layouts;
    variantById = new Map();
    for (const cropId of Object.keys(cropsData)) {
      for (const variant of cropsData[cropId].variants) {
        variantById.set(variant.id, { cropId, variant });
      }
    }
    buildGoalIndex();
    populateLayoutsVariantSelect();
  }

  async function init() {
    await ensureDataLoaded();
    render();
    cropTabRockwood.addEventListener("click", () => setCrop("rockwood"));
    cropTabSpacekorn.addEventListener("click", () => setCrop("spacekorn"));
    new LiveDropdown(goalSearchInput, {
      getValues: async () => goalLabels,
      onSelect: onGoalCommit,
    });
    goalSearchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") onGoalCommit();
    });

    modeReferenceBtn.addEventListener("click", () => setFarmingMode("reference"));
    modeLayoutsBtn.addEventListener("click", () => setFarmingMode("layouts"));
    for (const btn of layoutsGoalGroupEl.querySelectorAll("[data-goal]")) {
      btn.addEventListener("click", () => {
        currentLayoutsGoal = btn.dataset.goal;
        for (const b of layoutsGoalGroupEl.querySelectorAll("[data-goal]")) {
          b.classList.toggle("active", b === btn);
        }
        renderLayoutsView();
      });
    }
    layoutsVariantSelect.addEventListener("change", renderLayoutsView);
  }

  init();
})();
