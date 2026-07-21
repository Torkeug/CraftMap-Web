/* Farming screen: a "what do I need to set up to grow X" reference for the
 * Xenic Farm's crop variants (Rockwood Nut / Spacekorn). Data comes from
 * game_data_extract/farming.json (backend/farming.py's get_farming_crops),
 * hand-transcribed from the sibling shipbuilder repo's game_logic_notes.md
 * Findings 13/14 - see that file for the original decompile-sourced tables.
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
  const mechanicsNoteEl = document.getElementById("farming-mechanics-note");
  const variantsEl = document.getElementById("farming-variants");

  let cropsData = null; // {rockwood: crop, spacekorn: crop}, fetched once
  let currentCrop = "spacekorn";
  // label (fruit/byproduct/variant name, lowercased) -> {cropId, variant} -
  // built once alongside cropsData so the goal search can jump to a variant
  // by anything the player might actually type, not just its own name (a
  // player wanting "Dreamwood Fruit" has no reason to already know that's
  // produced by "Rockwood Dream"). goalLabels keeps the original casing,
  // separately, purely for what the dropdown displays.
  let goalIndex = null;
  let goalLabels = null;

  function fmtRange(range) {
    if (!range) return "";
    const [lo, hi] = range;
    return lo === hi ? `${lo}h` : `${lo}-${hi}h`;
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
  // "Reclusive"/"Invasive" reads identically everywhere on a card.
  function makeBioTagChip(tag) {
    const chip = document.createElement("span");
    chip.className = "farming-bio-tag" + (BIO_TAG_CLASS[tag] ? ` ${BIO_TAG_CLASS[tag]}` : "");
    chip.textContent = tag;
    return chip;
  }

  // A gate's own list IS the set of dial positions that satisfy it (empty
  // = unconstrained, matching farming.json's encoding of both Rockwood
  // Glow's literal-0 and Spacekorn's absent-key cases - see
  // game_logic_notes.md Finding 14's own note on that) - an unconstrained
  // gate gets one neutral "Any" chip rather than one chip per possible
  // dial position, since every position already satisfies it.
  function makeDialChips(values, kind) {
    const wrap = document.createElement("span");
    wrap.className = "farming-req-chips";
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
    // Distinct from an empty fertilizer_required (= no SPECIFIC fertilizer
    // needed, any or none is fine) - this means no fertilizer of ANY kind
    // may be present at all. See farming.json's own _meta.fertilizer_forbidden_any
    // for why these two "none" cases are genuinely different, not just two
    // ways of writing the same thing.
    if (variant.fertilizer_forbidden_any) {
      return "must be empty - no fertilizer of any kind";
    }
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

  function fmtHours(v) {
    // 2dp is enough precision for anything derived from these ranges (the
    // fastest base cycle, Rockwood Glow's, is already sub-hour at 2dp) -
    // more would just be display noise from float division.
    return String(Math.round(v * 100) / 100);
  }

  function fmtAdjustedRange(range) {
    const [lo, hi] = range;
    return lo === hi ? `${fmtHours(lo)}h` : `${fmtHours(lo)}-${fmtHours(hi)}h`;
  }

  // additive stacks by summing (two +50%s make +100%, matching how the
  // enrichment bonuses' own ARatio is described - Finding 13's own
  // semantics), multiplicative stacks by multiplying (two ×0.8s make
  // ×0.64) - independent accumulators since they're different operations
  // on the base duration (divide by (1+sum) vs divide by product).
  function adjustRange(baseRange, stat) {
    const factor = (1 + stat.add) * stat.mult;
    return baseRange.map((v) => v / factor);
  }

  // Reads every currently-checked toggle inside this card (both the
  // variant's own speed-affecting enrichments and any neighbor_effects -
  // see farming.json's _meta.speed_effect) and recomputes/repaints the
  // timing box from them. The DOM's own checked state IS the source of
  // truth here (no parallel JS state to keep in sync) - INPUT_EFFECTS maps
  // each input straight to the speed_effect array it was built from.
  const INPUT_EFFECTS = new WeakMap();

  const TIMING_STATS = [
    ["growth", "Growth", "growth_hours"],
    ["fruit", "Fruit cycle", "fruit_cycle_hours"],
    ["byproduct", "Byproduct cycle", "byproduct_cycle_hours"],
  ];

  function updateTiming(card, variant, timingEls) {
    const stats = {
      growth: { add: 0, mult: 1 },
      fruit: { add: 0, mult: 1 },
      byproduct: { add: 0, mult: 1 },
    };
    let anyChecked = false;
    for (const input of card.querySelectorAll(".farming-toggle-input:checked")) {
      anyChecked = true;
      for (const e of INPUT_EFFECTS.get(input) || []) {
        if (e.type === "additive") stats[e.stat].add += e.value;
        else stats[e.stat].mult *= e.value;
      }
    }
    for (const [key, , field] of TIMING_STATS) {
      const baseRange = variant[field];
      const adjusted = adjustRange(baseRange, stats[key]);
      timingEls[key].valueEl.textContent = fmtAdjustedRange(adjusted);
      timingEls[key].baseEl.textContent = anyChecked ? `base ${fmtRange(baseRange)}` : "";
    }
  }

  function makeTimingBox(variant) {
    const box = document.createElement("div");
    box.className = "farming-timing-box";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-timing-label";
    labelEl.textContent = "Timing";
    box.appendChild(labelEl);

    const timingEls = {};
    for (const [key, label, field] of TIMING_STATS) {
      const row = document.createElement("div");
      row.className = "farming-timing-row";
      const statEl = document.createElement("span");
      statEl.className = "farming-timing-stat";
      statEl.textContent = label;
      row.appendChild(statEl);
      const valueEl = document.createElement("span");
      valueEl.className = "farming-timing-value";
      valueEl.textContent = fmtRange(variant[field]);
      row.appendChild(valueEl);
      const baseEl = document.createElement("span");
      baseEl.className = "farming-timing-base";
      row.appendChild(baseEl);
      box.appendChild(row);
      timingEls[key] = { valueEl, baseEl };
    }
    return { box, timingEls };
  }

  // Toggle inputs that share a dial_group are mutually exclusive (checking
  // one unchecks any other sibling in the same group before recomputing) -
  // the farm only has one Temperature and one Light position at a time,
  // so e.g. a variant's own "Light dial = UV" enrichment and a "Neighboring
  // Rockwood Glow" neighbor_effect (which mirrors being UV-lit) can't both
  // apply at once even though they're rendered in different sections. See
  // farming.json's _meta.speed_effect for the full rationale.
  function makeToggleInput(variantKey, entry) {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "farming-toggle-input";
    INPUT_EFFECTS.set(input, entry.speed_effect);
    if (entry.dial_group) {
      input.dataset.dialGroup = `${variantKey}|${entry.dial_group}`;
    }
    return input;
  }

  function wireToggleInput(input, card, variant, timingEls) {
    input.addEventListener("change", () => {
      if (input.checked && input.dataset.dialGroup) {
        for (const sibling of card.querySelectorAll(
          `.farming-toggle-input[data-dial-group="${input.dataset.dialGroup}"]`
        )) {
          if (sibling !== input) sibling.checked = false;
        }
      }
      updateTiming(card, variant, timingEls);
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
  // An entry with a "speed_effect" (see farming.json's _meta.speed_effect)
  // gets a checkbox that feeds the Timing box above - toggling it live-
  // recomputes Growth/Fruit/Byproduct. An entry without one (a pure
  // output-quantity bonus, which this app doesn't track at all) stays
  // plain, non-interactive text, same as before - there's nothing for a
  // checkbox to do there.
  function makeEnrichmentSection(label, enrichments, variantKey, card, variant, timingEls) {
    const section = document.createElement("div");
    section.className = "farming-variant-section";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-variant-section-label";
    labelEl.textContent = label;
    section.appendChild(labelEl);
    const list = document.createElement("ul");
    for (const e of enrichments) {
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

      if (e.speed_effect) {
        const inputEntry = { speed_effect: e.speed_effect, dial_group: e.dial_group };
        const input = makeToggleInput(variantKey, inputEntry);
        const toggleLabel = document.createElement("label");
        toggleLabel.className = "farming-toggle-label";
        toggleLabel.appendChild(input);
        toggleLabel.appendChild(conditionEl);
        li.appendChild(toggleLabel);
        wireToggleInput(input, card, variant, timingEls);
      } else {
        li.appendChild(conditionEl);
      }

      const arrowEl = document.createElement("span");
      arrowEl.className = "farming-bonus-arrow";
      arrowEl.textContent = "→";
      li.appendChild(arrowEl);
      const effectEl = document.createElement("span");
      effectEl.className = "farming-bonus-effect";
      effectEl.textContent = e.effect;
      li.appendChild(effectEl);
      list.appendChild(li);
    }
    section.appendChild(list);
    return section;
  }

  // Cross-variant bonuses (farming.json's own "neighbor_effects" -
  // currently just Spacekorn Plain's self-buff from a neighboring Plain,
  // and Rockwood Glow's "neighbor treated as UV-lit" mirrored onto
  // whichever variants have their own Light=UV enrichment) - same toggle
  // shape as makeEnrichmentSection's interactive rows, but there's no
  // "effect" prose string to show (the label already says what it is), so
  // just the checkbox + label, no arrow/effect pair.
  function makeNeighborEffectsSection(neighborEffects, variantKey, card, variant, timingEls) {
    const section = document.createElement("div");
    section.className = "farming-variant-section";
    const labelEl = document.createElement("div");
    labelEl.className = "farming-variant-section-label";
    labelEl.textContent = "Neighbor conditions that also affect timing:";
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
      wireToggleInput(input, card, variant, timingEls);
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
      const tagEl = document.createElement("span");
      tagEl.className = "farming-bio-tag" + (tagClass ? ` ${tagClass}` : "");
      tagEl.title = "Relevant to nearby plants' own neighbor restrictions";
      tagEl.textContent = variant.bio_tag;
      header.appendChild(tagEl);
    }
    card.appendChild(header);

    const producesEl = document.createElement("div");
    producesEl.className = "farming-variant-produces";
    producesEl.textContent = `Produces: ${variant.fruit} (fruit) · ${variant.byproduct} (byproduct)`;
    card.appendChild(producesEl);

    const reqSection = document.createElement("div");
    reqSection.className = "farming-variant-section";
    const reqLabelEl = document.createElement("div");
    reqLabelEl.className = "farming-variant-section-label";
    reqLabelEl.textContent = "Requirements to grow it:";
    reqSection.appendChild(reqLabelEl);
    reqSection.appendChild(makeReqLine("Temperature", makeDialChips(variant.temperature, "temp")));
    reqSection.appendChild(makeReqLine("Light", makeDialChips(variant.light, "light")));
    reqSection.appendChild(makeReqLine("Fertilizer", makeReqText(fmtFertilizerRequirement(variant))));
    reqSection.appendChild(makeReqLine("Neighbor", makeNeighborRestriction(variant.neighbor_restriction_tag)));
    card.appendChild(reqSection);

    // Built before the toggle sections below (which need timingEls to wire
    // their change handlers into) but appended here, right under
    // Requirements, so the numbers it live-updates stay prominent and
    // above-the-fold rather than buried under every modifier.
    const { box: timingBox, timingEls } = makeTimingBox(variant);
    card.appendChild(timingBox);

    if (variant.enrichments && variant.enrichments.length) {
      card.appendChild(
        makeEnrichmentSection(
          "Speed & yield modifiers:",
          variant.enrichments,
          variantKey,
          card,
          variant,
          timingEls
        )
      );
    }
    if (variant.neighbor_effects && variant.neighbor_effects.length) {
      card.appendChild(
        makeNeighborEffectsSection(variant.neighbor_effects, variantKey, card, variant, timingEls)
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
    if (crop.note) {
      const noteLine = document.createElement("div");
      noteLine.className = "farming-crop-note";
      noteLine.textContent = crop.note;
      infoRowEl.appendChild(noteLine);
    }

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

  async function ensureDataLoaded() {
    if (cropsData !== null) return;
    const [crops, mechanicsNote] = await Promise.all([
      CraftMapApi.call("get_farming_crops"),
      CraftMapApi.call("get_farming_mechanics_note"),
    ]);
    cropsData = {};
    for (const crop of crops) cropsData[crop.id] = crop;
    buildGoalIndex();
    // Crop-independent (same Xenic Farm building/mechanic either way) -
    // rendered once here rather than in render(), which only ever redraws
    // the parts that actually change on a crop switch.
    mechanicsNoteEl.textContent = mechanicsNote;
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
  }

  init();
})();
