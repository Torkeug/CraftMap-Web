/* Galaxy sub-tab (Resource tab, js/deposits.js's own #resource-mode-tabs):
 * ranked, real per-planet data for a single NODE TYPE (not a raw material -
 * see backend.db.get_galaxy_sources_for_resource's own docstring; this is
 * the same node-type namespace as resource_sources' source_name column,
 * populated entirely from a live galaxy-wide dump, see
 * tools/backfill_galaxy_resources.py).
 *
 * Ranked by "effective density" (poi_area_density when set, else plain
 * density - both already on the same scale server-side, see
 * backend.db.get_galaxy_sources_for_resource) - shown here as a relative
 * bar/multiplier against the best row CURRENTLY shown, re-baselining
 * whenever a filter changes, since the raw number has no meaning in
 * isolation. A 3-way mark (poiState) shows ◆ for a purely POI-anchored
 * planet (its rank IS area-adjusted - a real, honest number), ◐ for one
 * where the resource is BOTH at a POI and scattered elsewhere, and a plain
 * · for one where it's scattered with no POI at all. The ◐/· distinction
 * is display-only, NOT priced into the rank - both fall back to identical
 * plain-density ranking (the live-memory dump only ever gives a per-planet
 * TOTAL, never split between a resource's general and POI portions, so a
 * mixed row's POI-anchored slice can't be area-adjusted out from its
 * general slice - see get_galaxy_sources_for_resource's own docstring). So
 * a ◐ row and a · row of equal density tie in rank despite the ◐ one
 * having a genuine practical edge (part of it IS walkable-POI-concentrated)
 * - the mark is what surfaces that, since the number can't. Climate/water
 * chips only render for non-default attributes - a plain Temperate row
 * gets no chip at all.
 *
 * Day/Night/Twilight POI chips (sunChips) are a separate filter dimension
 * from climate/water, driven by poi_landmarks - every in-game POI turns out
 * to have a landmark (one of 3 kinds - Meteor Crater/High Peak/Natural
 * Canyon, see tools/extract_poi_icons.py; confirmed empirically, poiSizes
 * and poiLandmarks share the exact same index set for every planet), so
 * this filter applies to every pure/mixed row, never just a lucky subset.
 * Unlike climate/water's AND-across-chips semantics (passesClimateFilter),
 * a row can carry BOTH a Day and a Night chip at once (different POIs on
 * the same planet), so this filter is OR-within-category (passesSunFilter):
 * unchecking "Night POI" only hides a row that's night-side EVERYWHERE it
 * has a landmark, not one that still has an unchecked-off Day POI. The
 * moment any lighting chip is unchecked, ranking for the WHOLE list
 * switches from poi_area_density's rate to an estimated surviving quantity
 * (density * area-weighted survival fraction, see densityFor/
 * survivingAreaFraction) - a rate can't honestly shrink from excluding
 * part of its own footprint (mathematically invariant under the uniform-
 * density assumption it relies on), so only a quantity estimate, applied
 * consistently to every row at once, can actually respond to the filter.
 * Real, stable per-POI data (planets don't rotate
 * in this game) - not a "goes stale" snapshot. Per-planet-accurate POI
 * marker COLOR (poiMarkerColor) IS reproduced now - reverse-engineered
 * from the game's own bytecode (ui.comp.ResourceIcon's constructor): a
 * POI's color is purely (its ordinal position in the planet's own POI
 * list) % 5, cycling through 5 fixed palette colors - NOT tied to landmark
 * kind, so two Meteor Craters on different planets can have different
 * colors. Our own poi_index ("poi0"/"poi1"/...) already IS that exact
 * ordinal position (confirmed against the same bytecode), so this needed
 * no new data capture, just the formula.
 *
 * "Best value" (sortMode "combined") re-ranks by density AND node_count
 * together - density alone answers "most concentrated per trip" but says
 * nothing about total quantity available, so a planet with 200 nodes
 * scattered planet-wide can rank far below a 3-node POI cluster under the
 * default sort despite having vastly more total resource; raw node_count
 * alone has the opposite problem (no sense of how much travel it costs to
 * actually collect them, and it's on a totally different, resource-
 * dependent scale than density so it can't just be added in). The combined
 * score is a geometric mean of each row's density and node_count, each
 * first normalized to its own max among the rows CURRENTLY shown (0-1
 * ratio) so the two differently-scaled metrics contribute fairly instead of
 * whichever has the bigger raw range dominating - see effectiveFor. A row
 * that's #1 in only one dimension still loses to one that's strong in
 * both, which is the point.
 *
 * Cross-references js/deposits.js's own manually-logged deposits for the
 * same node name (get_deposits_for_ingredient, the same lookup
 * breakdown-tree.js's ingredient-location popup already uses) to mark
 * rows you've already found in-game with a LOGGED pin - the one place
 * manual and automatic data actually meet. A logged row's own notes (if
 * any) render inline in its detail line; a not-yet-logged row instead
 * gets an inline "+ note" control (see buildAddNoteControl) - saving one
 * calls add_galaxy_note (backend/api.py), which inserts a deposits row
 * with res_type left blank, i.e. it's really just "log this planet" with
 * no type set, so the row picks up its own LOGGED pin on the next render.
 *
 * "Current system" (galaxy-current-system) is a manually re-typed stand-in
 * for where the player currently is - CraftMap never reads the live game
 * process (see this project's own CLAUDE.md), so there's no other way to
 * know. Once set, every row gets a jump-hop-count badge (BFS over
 * galaxy_systems' nearSystemNames graph - see backend.db.
 * get_galaxy_hop_distances' own docstring for why hop count, not
 * straight-line distance, is the meaningful "closest" metric here) shown
 * regardless of sort mode; the rank/distance toggle only changes ORDER.
 */
(function () {
  const comboInput = document.getElementById("galaxy-combo");
  const breadcrumbEl = document.getElementById("galaxy-breadcrumb");
  const asteroidCheckbox = document.getElementById("galaxy-filter-asteroids");
  const poiCheckbox = document.getElementById("galaxy-filter-poi");
  const mixedPoiCheckbox = document.getElementById("galaxy-filter-mixed-poi");
  const nonPoiCheckbox = document.getElementById("galaxy-filter-non-poi");
  const climateFilterEl = document.getElementById("galaxy-climate-filter");
  const climateFilterRowEl = document.getElementById("galaxy-climate-filter-row");
  const sunFilterEl = document.getElementById("galaxy-sun-filter");
  const sunFilterRowEl = document.getElementById("galaxy-sun-filter-row");
  const sectorFilterInput = document.getElementById("galaxy-sector-filter-input");
  const sectorFilterClearEl = document.getElementById("galaxy-sector-filter-clear");
  const countLabelEl = document.getElementById("galaxy-count-label");
  const rowsEl = document.getElementById("galaxy-rows");
  const currentSystemInput = document.getElementById("galaxy-current-system");
  const sortRankBtn = document.getElementById("galaxy-sort-rank");
  const sortDistanceBtn = document.getElementById("galaxy-sort-distance");
  const sortCombinedBtn = document.getElementById("galaxy-sort-combined");

  let currentNode = null;
  let currentRows = []; // raw rows from the last fetch (post asteroid-filter, pre climate-filter)
  const climateFilterState = new Map(); // chip label -> checked (session-only, rebuilt per node)
  const sunFilterState = new Map(); // "Day POI"/"Night POI"/"Twilight POI" -> checked, see passesSunFilter
  // Unlike climate (a handful of fixed categories - checkboxes work fine),
  // a resource can turn up in dozens of distinct sectors, so this is a
  // single free-typed/autocompleted filter (same LiveDropdown pattern as
  // "Current system" below) rather than a checkbox per sector. Empty
  // string = no filter (show every sector).
  let sectorFilter = "";
  // {systemName, planet} of a specific entry someone jumped here from (a
  // deposit leaf's or Sources row's double-click - see showForNode) -
  // survives filter-driven re-renders of the SAME node (so the row stays
  // marked even after toggling asteroids/climate), cleared on loadNode's
  // own logic once a genuinely different node is loaded.
  let highlightTarget = null;

  // "Current system" (js/deposits.js has no notion of this - CraftMap
  // never reads the live game process, see this project's own CLAUDE.md,
  // so this is a manually-typed stand-in for "where you are right now",
  // re-entered as you travel during a session, not persisted across app
  // restarts). sortMode "distance" only actually reorders rows once
  // hopDistances has resolved for the current pick - see setCurrentSystem.
  let currentSystemName = null;
  let hopDistances = null; // {system_name: hop_count} for currentSystemName, or null
  const hopDistancesCache = new Map(); // system_name -> already-fetched hop dict
  let sortMode = "rank"; // "rank" (density) | "distance" (hop count) | "combined" (density+qty)

  // isLightingFilterNarrowed/survivingAreaFraction are declared further
  // below (function hoisting) - see densityFor's own comment for the full
  // reasoning on why the ranking basis switches entirely, for every row,
  // the moment any lighting chip is unchecked, rather than only adjusting
  // the specific rows that have an excluded POI.
  function densityFor(row) {
    if (!isLightingFilterNarrowed()) return row.poi_area_density ?? row.density;
    return row.density * survivingAreaFraction(row);
  }

  // Describes ranking with the lighting filter at its default (fully
  // checked) state - see densityFor for how this changes once it's
  // narrowed. "pure" (poi_tags set, no "general") ranks on
  // poi_area_density - a real area-adjusted figure. "none" (no poi_tags,
  // or only "general") ranks on plain density with nothing else
  // contributing. "mixed" (poi_tags has BOTH a real POI and "general")
  // ALSO ranks on plain density - see
  // backend.db.get_galaxy_sources_for_resource's own docstring for why
  // (the dump never splits a planet's total density between its general
  // and POI portions, so there's no honest denominator to area-adjust
  // with) - meaning a mixed row ties with a "none" row of equal density
  // even though it has a real advantage (part of it IS at a walkable POI).
  // The ranking number can't reflect that; this mark exists so the row
  // itself still shows it.
  function poiState(row) {
    if (!row.poi_tags) return "none";
    const tags = row.poi_tags.split(",");
    const hasPoi = tags.some((t) => t !== "general");
    const hasGeneral = tags.includes("general");
    if (hasPoi && hasGeneral) return "mixed";
    if (hasPoi) return "pure";
    return "none";
  }

  function quantityFor(row) {
    return row.node_count || 0;
  }

  function isHighlightedRow(row) {
    return (
      !!highlightTarget &&
      row.system_name === highlightTarget.systemName &&
      row.planet === highlightTarget.planet
    );
  }

  // ---- climate/water chip classification ----
  function climateChip(row) {
    const id = row.temperature;
    if (!id || id === "PlanetTemperate") return null;
    if (id.startsWith("PlanetHot")) {
      const tier = Number(id.slice(-1)) || 1;
      return { cls: tier >= 2 ? "chip-veryhot" : "chip-hot", label: row.temperature_name };
    }
    if (id.startsWith("PlanetCold")) {
      return { cls: "chip-frozen", label: row.temperature_name };
    }
    return null;
  }

  function waterChip(row) {
    const names = (row.attribute_names || "").toLowerCase();
    if (!names.includes("water")) return null;
    return { cls: "chip-water", label: "Water" };
  }

  // One chip per distinct sun_side among this row's own poi_landmarks (see
  // backend.db.get_galaxy_sources_for_resource) - a row split across a Day
  // POI and a Night POI gets BOTH chips. Kept OUT of chipsForRow/
  // climateFilterState on purpose: that filter is AND-across-chips (a row
  // needs EVERY chip it has currently checked to show - fine for
  // independent attributes like climate+water, which a row has at most one
  // of each of), but a mixed Day+Night row has TWO chips from the SAME
  // dimension, and unchecking "Night POI" should only hide a row that is
  // EXCLUSIVELY night-side, not one that still has an unchecked-off Day POI
  // to offer - see passesSunFilter's own OR-within-category logic.
  const SUN_CHIPS = {
    day: { cls: "chip-sun-day", label: "Day POI" },
    twilight: { cls: "chip-sun-twilight", label: "Twilight POI" },
    night: { cls: "chip-sun-night", label: "Night POI" },
  };

  function sunChips(row) {
    return (row.poi_sun_states || []).map((s) => SUN_CHIPS[s]).filter(Boolean);
  }

  function chipsForRow(row) {
    return [climateChip(row), waterChip(row)].filter(Boolean);
  }

  const LANDMARK_ICONS = {
    BalisePOI: "assets/poi/meteor-crater.png",
    BalisePOI1: "assets/poi/high-peak.png",
    BalisePOI2: "assets/poi/natural-canyon.png",
  };

  // Real in-game POI marker colors (data.cdb's resource sheet, ColorPOI1..5
  // rows) and the real in-game SELECTION rule, reverse-engineered from the
  // game's own bytecode (ui.comp.ResourceIcon's constructor, findex 13872):
  // colorSlot = (index % 5) + 1, where `index` is simply the POI's own
  // ordinal position in the planet's POI list - NOT tied to landmark kind
  // at all (a Meteor Crater and a High Peak on the same planet can get any
  // of the 5 colors; it's purely "which position in the list is this POI"
  // that decides it). Confirmed our own poi_index ("poi0"/"poi1"/..., see
  // tools/backfill_galaxy_resources.py's load_poi_landmark_rows) already IS
  // that same raw ordinal position (dump_planet_resources.py's
  // read_planet_poi_landmarks iterates the identical array in the identical
  // order, index-for-index - traced independently against the same
  // bytecode range and found to agree exactly), so this is computable
  // directly from data already stored - no new capture needed.
  const POI_MARKER_COLORS = ["#E71000", "#0074F6", "#00F24F", "#FFE400", "#D800CB"];

  function poiMarkerColor(poiIndex) {
    const n = parseInt(String(poiIndex).replace("poi", ""), 10);
    return Number.isNaN(n) ? null : POI_MARKER_COLORS[n % 5];
  }

  // The raw ColorPOI1..5 values are the game's own fully-saturated HUD
  // marker colors - rendered solid at 100% opacity here they read as too
  // bright against this app's dark panel background (this is a small
  // detail-line badge, not the game's own HUD). Blended down to 55% over
  // the badge's own dark background instead of dimming the hue itself, so
  // it's still unambiguously "which of the 5 colors" at a glance.
  function poiMarkerBadgeColor(poiIndex) {
    const hex = poiMarkerColor(poiIndex);
    if (!hex) return null;
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `rgba(${r}, ${g}, ${b}, 0.55)`;
  }

  // ---- filter row (dynamic, rebuilt per node - only chips actually
  // present get a checkbox, mirroring js/deposits.js's own type-filter) ----
  // Shared by rebuildClimateFilter and rebuildSunFilter - the AND-vs-OR
  // filtering semantics live in passesClimateFilter/passesSunFilter, not
  // here; this only builds "one checkbox per chip label currently present,
  // defaulting to checked, pruning stale ones" for whichever (rows, chipsFn,
  // stateMap, containerEl, rowEl) combination is passed in. rowEl (the
  // labeled "Climate:"/"Lighting:" sub-row - see index.html's
  // #galaxy-filters) is hidden entirely when no row currently has a chip
  // of that kind, rather than showing a bare label with nothing next to
  // it - most resources never trigger climate OR lighting chips at all.
  function rebuildChipFilter(rows, chipsFn, stateMap, containerEl, rowEl) {
    const present = new Map(); // label -> cls
    for (const row of rows) {
      for (const chip of chipsFn(row)) present.set(chip.label, chip.cls);
    }
    containerEl.innerHTML = "";
    for (const [label, cls] of present) {
      if (!stateMap.has(label)) stateMap.set(label, true);
      const lbl = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = stateMap.get(label);
      cb.addEventListener("change", () => {
        stateMap.set(label, cb.checked);
        renderRows();
      });
      lbl.appendChild(cb);
      const chipEl = document.createElement("span");
      chipEl.className = `chip ${cls}`;
      chipEl.textContent = label;
      lbl.appendChild(chipEl);
      containerEl.appendChild(lbl);
    }
    for (const stale of [...stateMap.keys()].filter((l) => !present.has(l))) {
      stateMap.delete(stale);
    }
    rowEl.classList.toggle("hidden", present.size === 0);
  }

  function rebuildClimateFilter(rows) {
    rebuildChipFilter(rows, chipsForRow, climateFilterState, climateFilterEl, climateFilterRowEl);
  }

  function rebuildSunFilter(rows) {
    rebuildChipFilter(rows, sunChips, sunFilterState, sunFilterEl, sunFilterRowEl);
  }

  // 3-way, matching poiState/the ◆◐· mark exactly (see makeRow) so the
  // checkboxes never disagree with what's actually shown on screen - a
  // "general,poi2" row is its own "Mixed" category now, not lumped into
  // "Non-POI" (that used to hide the fact it had ANY POI presence at all).
  function passesPoiFilter(row) {
    const state = poiState(row);
    if (state === "pure") return poiCheckbox.checked;
    if (state === "mixed") return mixedPoiCheckbox.checked;
    return nonPoiCheckbox.checked;
  }

  function passesClimateFilter(row) {
    const chips = chipsForRow(row);
    if (!chips.length) return true; // plain Temperate/no-attribute rows always show
    return chips.every((c) => climateFilterState.get(c.label) !== false);
  }

  // OR-within-category (unlike passesClimateFilter's AND-across-chips): a
  // row with no landmark data at all always passes (a resource that's never
  // POI-anchored on this planet has nothing for the filter to judge), and a
  // row WITH landmark data passes as long as AT LEAST ONE of its sun states
  // is still checked - so a Day+Night mixed row only disappears once BOTH
  // are unchecked, and a Night-only row disappears as soon as "Night POI" is.
  function passesSunFilter(row) {
    const chips = sunChips(row);
    if (!chips.length) return true;
    return chips.some((c) => sunFilterState.get(c.label) !== false);
  }

  // True once ANY lighting checkbox has been unchecked (regardless of
  // which rows that actually affects) - densityFor uses this to switch
  // ranking basis for the WHOLE visible list at once, not just rows with
  // an excluded POI. Necessary because poi_area_density is a RATE (density
  // per unit area) that's mathematically invariant to which subset of a
  // row's own footprint you look at (under the uniform-density-per-area
  // assumption it already relies on: excluding part of the footprint
  // shrinks the numerator and denominator by the same proportion, leaving
  // the ratio unchanged) - so there's no way to shrink JUST the affected
  // rows' numbers while leaving everyone else on the rate scale; that
  // would compare two different kinds of numbers in one sort. So instead
  // every row moves to the same (density * survivingAreaFraction) scale
  // together the moment filtering starts, and back once it stops.
  function isLightingFilterNarrowed() {
    return [...sunFilterState.values()].some((v) => v === false);
  }

  // Estimate of how much of a row's density is still "reachable" once
  // some of its POIs are excluded by the lighting filter, weighted by
  // each POI's own AREA (galaxy_poi_landmarks.area - see
  // import_galaxy_poi_landmarks's own docstring) rather than assuming
  // every POI on a planet is equally sized: a night POI that's 90% of a
  // resource's combined POI footprint should demote the row far more than
  // one that's a sliver of it. Returns 1 (no reduction) for a row with no
  // area data to weight by, or with nothing currently excluded - so an
  // unaffected row's density stays exactly its own density, same scale as
  // an affected row's reduced estimate.
  function survivingAreaFraction(row) {
    const landmarks = (row.poi_landmarks || []).filter((lm) => lm.area != null);
    if (!landmarks.length) return 1;
    const total = landmarks.reduce((sum, lm) => sum + lm.area, 0);
    if (!total) return 1;
    const surviving = landmarks.reduce((sum, lm) => {
      const chip = SUN_CHIPS[lm.sun_side];
      const excluded = chip && sunFilterState.get(chip.label) === false;
      return sum + (excluded ? 0 : lm.area);
    }, 0);
    return surviving / total;
  }

  function passesSectorFilter(row) {
    return !sectorFilter || row.sector === sectorFilter;
  }

  // ---- POI detail (revealed on row click - see makeRow's disclosure) ----
  // One inline (icon-badge + text) unit for a single POI index - the badge
  // sits directly in front of ITS OWN poi's name/sun-side text (not in a
  // separate strip elsewhere in the row), so which marker belongs to which
  // POI is never ambiguous even when a row lists several. No badge only if
  // this specific poi_index has no matching entry in row.poi_landmarks at
  // all (shouldn't happen in practice - every in-game POI has a landmark -
  // but kept as a safe fallback to the bare "poiN" tag as text, e.g. for
  // older/incomplete data imported before this table existed).
  function makePoiSegment(poiIndex, row) {
    const seg = document.createElement("span");
    seg.className = "galaxy-poi-segment";
    seg.title = poiIndex; // the raw "poiN" tag - kept as a hover tooltip, not shown as text
    const lm = (row.poi_landmarks || []).find((l) => l.poi_index === poiIndex);
    const src = lm && LANDMARK_ICONS[lm.indicator_id];
    if (lm && src) {
      const badge = document.createElement("span");
      badge.className = "poi-landmark-badge";
      const color = poiMarkerBadgeColor(lm.poi_index);
      if (color) badge.style.backgroundColor = color;
      const img = document.createElement("img");
      img.className = "poi-landmark-icon";
      img.src = src;
      badge.appendChild(img);
      seg.appendChild(badge);
    }
    // The icon badge IS the identifier once one exists - no need to also
    // spell out "poiN" in the visible text, that's an internal index the
    // player never sees in-game. Falls back to the bare poiIndex only when
    // there's no landmark/icon to show instead (nothing else to go on).
    const text = document.createElement("span");
    text.textContent = lm && lm.name ? `${lm.name}${lm.sun_side ? ` (${lm.sun_side})` : ""}` : poiIndex;
    seg.appendChild(text);
    return seg;
  }

  function appendPoiList(container, poiIndexes, row) {
    poiIndexes.forEach((poiIndex, i) => {
      if (i > 0) container.appendChild(document.createTextNode(", "));
      container.appendChild(makePoiSegment(poiIndex, row));
    });
  }

  function makePoiLine(row) {
    const poiLine = document.createElement("div");
    poiLine.className = "galaxy-poi-line";
    if (!row.poi_tags) {
      poiLine.textContent = "No POI placement data available for this planet.";
      return poiLine;
    }
    const tags = row.poi_tags.split(",");
    const pois = tags.filter((t) => t !== "general");
    const hasGeneral = tags.includes("general");
    if (pois.length && !hasGeneral) {
      const plural = pois.length > 1 ? "s" : "";
      poiLine.appendChild(document.createTextNode(`Concentrated at ${pois.length} POI${plural}: `));
      appendPoiList(poiLine, pois, row);
      poiLine.appendChild(
        document.createTextNode(" - every node reachable without crossing the planet.")
      );
    } else if (pois.length && hasGeneral) {
      poiLine.appendChild(document.createTextNode("Partly concentrated ("));
      appendPoiList(poiLine, pois, row);
      poiLine.appendChild(document.createTextNode(") and partly scattered across the rest of the planet."));
    } else {
      poiLine.textContent = "Scattered across the whole planet - no POI anchor.";
    }
    return poiLine;
  }

  function makeExpandDetail(row) {
    const el = document.createElement("div");
    el.className = "galaxy-row-expand";

    el.appendChild(makePoiLine(row));

    const statsLine = document.createElement("div");
    statsLine.className = "galaxy-row-stats";
    const parts = [`node_count ${row.node_count}`, `density ${row.density.toFixed(4)}`];
    if (row.poi_area_density !== null && row.poi_area_density !== undefined) {
      parts.push(`poi_area_density ${row.poi_area_density.toFixed(4)}`);
    }
    statsLine.textContent = parts.join(" · ");
    el.appendChild(statsLine);

    return el;
  }

  // ---- add-note control (rows with no matching deposit yet) ----
  // Clicking "+ note" swaps to an inline input + Save button, right there
  // in the detail line - saving calls add_galaxy_note (backend/api.py),
  // which is functionally "log this planet" with res_type left blank, so
  // the row picks up its own LOGGED pin + note on the next render same as
  // any other logged planet. e.stopPropagation() throughout since the
  // whole row also has its own click-to-expand handler (see makeRow) that
  // would otherwise fire on every click inside this control.
  function buildAddNoteControl(row) {
    const container = document.createElement("span");
    container.className = "galaxy-note-add";

    function renderLink() {
      container.innerHTML = "";
      const link = document.createElement("a");
      link.className = "galaxy-note-link";
      link.textContent = "+ note";
      link.addEventListener("click", (e) => {
        e.stopPropagation();
        renderForm();
      });
      container.appendChild(link);
    }

    function renderForm() {
      container.innerHTML = "";
      const input = document.createElement("input");
      input.type = "text";
      input.className = "galaxy-note-input";
      input.placeholder = "Add a note...";
      input.addEventListener("click", (e) => e.stopPropagation());
      input.addEventListener("input", () => {
        saveBtn.disabled = !input.value.trim();
      });
      input.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Enter") save();
        else if (e.key === "Escape") renderLink();
      });
      container.appendChild(input);

      const saveBtn = document.createElement("button");
      saveBtn.className = "galaxy-note-save";
      saveBtn.textContent = "Save";
      // Starts disabled (input starts empty) - an empty note has nothing
      // to show inline and would just silently consume the "+ note"
      // affordance without leaving anything behind, so there's nothing
      // meaningful to save yet.
      saveBtn.disabled = true;
      saveBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        save();
      });
      container.appendChild(saveBtn);

      input.focus();

      async function save() {
        const notes = input.value.trim();
        if (!notes) return; // guards the Enter-key path too, not just the button
        saveBtn.disabled = true;
        try {
          await CraftMapApi.call(
            "add_galaxy_note",
            currentNode,
            row.sector,
            row.system_name,
            row.planet,
            notes
          );
        } catch (e) {
          saveBtn.disabled = false;
          return; // error banner already shown by CraftMapApi.call
        }
        await renderRows();
      }
    }

    renderLink();
    return container;
  }

  // ---- row rendering ----
  // deposit (or null): the matching get_deposits_for_ingredient row for
  // this exact system/planet, if any - {id, sector, system_name, planet,
  // notes}. Truthy deposit is what the LOGGED pin means; its notes (if
  // any) render inline, and its absence is what shows the add-note control
  // instead.
  function makeRow(row, rank, isTop, effective, best, deposit, highlighted, hops) {
    const wrapper = document.createElement("div");
    wrapper.className =
      "galaxy-row" + (isTop ? " top" : "") + (highlighted ? " highlighted expanded" : "");

    const top = document.createElement("div");
    top.className = "galaxy-row-top";

    const disclosureEl = document.createElement("span");
    disclosureEl.className = "disclosure";
    disclosureEl.textContent = highlighted ? "▾" : "▸";
    top.appendChild(disclosureEl);

    const rankEl = document.createElement("span");
    rankEl.className = "galaxy-rank";
    rankEl.textContent = `#${rank}`;
    top.appendChild(rankEl);

    const state = poiState(row);
    const MARK_TEXT = { pure: "◆", mixed: "◐", none: "·" };
    const markEl = document.createElement("span");
    markEl.className = "galaxy-mark" + (state === "none" ? " scattered" : state === "mixed" ? " mixed" : "");
    markEl.textContent = MARK_TEXT[state];
    markEl.title =
      state === "pure"
        ? "Purely POI-anchored - ranked by area-adjusted density"
        : state === "mixed"
        ? "Partly POI-anchored, partly scattered - ranked by plain density (can't be area-adjusted, see docs)"
        : "Scattered planet-wide, no POI anchor";
    top.appendChild(markEl);

    const planetEl = document.createElement("span");
    planetEl.className = "galaxy-planet";
    planetEl.textContent = row.planet;
    planetEl.title = row.planet; // still truncates on very long names - full name on hover
    top.appendChild(planetEl);

    if (deposit) {
      const pinEl = document.createElement("span");
      pinEl.className = "galaxy-pin";
      pinEl.textContent = "LOGGED";
      top.appendChild(pinEl);
    }

    // Only rendered once a current system is set AND its hop-distance graph
    // has resolved (see setCurrentSystem) - shown regardless of sortMode,
    // since it's useful context even while sorted by rank. hops === null
    // means the row's own system hasn't been confirmed reachable through
    // any explored jump lane yet (not necessarily unreachable - just not
    // seen in the dump's own nearSystemNames data).
    if (hops !== undefined) {
      const hopsEl = document.createElement("span");
      if (hops === null) {
        hopsEl.className = "galaxy-hops unreachable";
        hopsEl.textContent = "? hops";
        hopsEl.title = "No known jump-lane path from your current system yet";
      } else {
        hopsEl.className = "galaxy-hops";
        hopsEl.textContent = hops === 0 ? "here" : `${hops} hop${hops === 1 ? "" : "s"}`;
      }
      top.appendChild(hopsEl);
    }

    const relEl = document.createElement("span");
    relEl.className = "galaxy-rel";
    relEl.textContent = `${(effective / best).toFixed(2)}×`;
    top.appendChild(relEl);

    wrapper.appendChild(top);

    // Its own full-width row, not sharing a line with the variable-width
    // planet name/LOGGED pin above - either of those competing for space
    // with the bar meant its start position shifted per row, defeating
    // visual length comparison across the list (the whole point of a bar).
    const barTrack = document.createElement("div");
    barTrack.className = "galaxy-bar-track";
    const barFill = document.createElement("div");
    barFill.className = "galaxy-bar-fill";
    barFill.style.width = `${Math.max(2, Math.round((effective / best) * 100))}%`;
    barTrack.appendChild(barFill);
    wrapper.appendChild(barTrack);

    const detail = document.createElement("div");
    detail.className = "galaxy-row-detail";
    if (row.sector) {
      const secEl = document.createElement("span");
      secEl.className = "galaxy-sector";
      secEl.textContent = row.sector;
      detail.appendChild(secEl);
      detail.appendChild(document.createTextNode(" / "));
    }
    const sysEl = document.createElement("span");
    sysEl.className = "galaxy-system";
    sysEl.textContent = row.system_name;
    detail.appendChild(sysEl);

    const sep1 = document.createElement("span");
    sep1.className = "galaxy-sep";
    sep1.textContent = " · ";
    detail.appendChild(sep1);
    const nodesEl = document.createElement("span");
    nodesEl.className = "galaxy-nodes";
    nodesEl.textContent = `${row.node_count} nodes`;
    detail.appendChild(nodesEl);

    // sunChips kept separate from chipsForRow (see that function's own
    // comment - passesClimateFilter's AND-across-chips semantics don't fit
    // a row that legitimately carries both a Day and a Night chip at once),
    // but both render as ordinary pills right here on the row.
    for (const chip of [...chipsForRow(row), ...sunChips(row)]) {
      const sep = document.createElement("span");
      sep.className = "galaxy-sep";
      sep.textContent = " · ";
      detail.appendChild(sep);
      const chipEl = document.createElement("span");
      chipEl.className = `chip ${chip.cls}`;
      chipEl.textContent = chip.label;
      detail.appendChild(chipEl);
    }

    if (deposit && deposit.notes) {
      const sep = document.createElement("span");
      sep.className = "galaxy-sep";
      sep.textContent = " · ";
      detail.appendChild(sep);
      const noteEl = document.createElement("span");
      noteEl.className = "galaxy-note";
      noteEl.textContent = `📝 ${deposit.notes}`;
      noteEl.title = deposit.notes;
      detail.appendChild(noteEl);
    } else if (!deposit) {
      detail.appendChild(buildAddNoteControl(row));
    }

    wrapper.appendChild(detail);

    const expandEl = makeExpandDetail(row);
    wrapper.appendChild(expandEl);

    wrapper.addEventListener("click", () => {
      const expanded = wrapper.classList.toggle("expanded");
      disclosureEl.textContent = expanded ? "▾" : "▸";
    });

    return wrapper;
  }

  async function renderRows({ scrollToHighlight = false } = {}) {
    rowsEl.innerHTML = "";
    const visible = currentRows.filter(
      (row) =>
        passesPoiFilter(row) && passesClimateFilter(row) && passesSunFilter(row) && passesSectorFilter(row)
    );
    countLabelEl.textContent = currentNode
      ? `${visible.length} of ${currentRows.length} explored planets`
      : "";
    if (!currentNode) {
      const empty = document.createElement("div");
      empty.className = "galaxy-empty";
      empty.textContent = "Select a node type to see where it's been found.";
      rowsEl.appendChild(empty);
      return;
    }
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "galaxy-empty";
      empty.textContent = "No matches for the current filters.";
      rowsEl.appendChild(empty);
      return;
    }
    const depositRows = await CraftMapApi.call("get_deposits_for_ingredient", currentNode);
    // Keyed by system+planet only (not sector/id) - matches the LOGGED-pin
    // lookup this replaced; a stray duplicate for the same planet (e.g.
    // logged once with a typo'd sector, once without) just means the first
    // one found wins for note display purposes.
    const depositByKey = new Map();
    for (const d of depositRows) {
      const key = `${d.system_name}|${d.planet}`;
      if (!depositByKey.has(key)) depositByKey.set(key, d);
    }
    // Normalize each dimension to its own max among the CURRENTLY shown
    // rows first (0-1 ratio) - density and node_count are on unrelated
    // scales (a resource-dependent raw count vs. an already-area-rescaled
    // density), so only their ratios-to-best are comparable, not the raw
    // numbers themselves.
    const maxDensity = Math.max(...visible.map(densityFor));
    const maxQuantity = Math.max(...visible.map(quantityFor));
    const effectiveFor = (row) => {
      if (sortMode !== "combined") return densityFor(row);
      const dRatio = maxDensity > 0 ? densityFor(row) / maxDensity : 0;
      const qRatio = maxQuantity > 0 ? quantityFor(row) / maxQuantity : 0;
      return Math.sqrt(dRatio * qRatio);
    };
    // Max, not visible[0] - visible[0] is only the best row for whichever
    // metric the backend/prior sort already left it in, which the distance
    // and combined sorts below deliberately override.
    const best = Math.max(...visible.map(effectiveFor));

    const hopFor = (row) =>
      hopDistances ? (Object.prototype.hasOwnProperty.call(hopDistances, row.system_name)
        ? hopDistances[row.system_name]
        : null) : undefined;

    if (sortMode === "distance" && hopDistances) {
      visible.sort((a, b) => {
        const ha = hopFor(a);
        const hb = hopFor(b);
        const da = ha === null ? Infinity : ha;
        const db = hb === null ? Infinity : hb;
        return da - db;
      });
    } else {
      // "rank" and "combined" both re-sort by effectiveFor client-side,
      // rather than trusting currentRows' existing backend-provided order,
      // because effectiveFor/densityFor can now differ from the backend's
      // own poi_area_density/density whenever the lighting filter is
      // narrowed (isLightingFilterNarrowed) - the backend has no notion of
      // which sun-state chips are currently unchecked, only the frontend
      // does. Re-sorting here (not just adjusting the displayed bar width)
      // is what actually moves a demoted row down in rank position.
      visible.sort((a, b) => effectiveFor(b) - effectiveFor(a));
    }

    let highlightEl = null;
    visible.forEach((row, i) => {
      const effective = effectiveFor(row);
      const deposit = depositByKey.get(`${row.system_name}|${row.planet}`) || null;
      const highlighted = isHighlightedRow(row);
      const hops = hopFor(row);
      const rowEl = makeRow(row, i + 1, i === 0, effective, best, deposit, highlighted, hops);
      if (highlighted) highlightEl = rowEl;
      rowsEl.appendChild(rowEl);
    });
    if (scrollToHighlight && highlightEl) {
      highlightEl.scrollIntoView({ block: "center" });
    }
  }

  // highlight ({systemName, planet}), when given, marks and scrolls to
  // that exact row once loaded. Omitted (e.g. the asteroid-filter
  // checkbox reloading the SAME node) keeps whatever highlightTarget is
  // already set; loading a genuinely different node always clears it.
  async function loadNode(nodeName, highlight) {
    const sameNode = nodeName === currentNode;
    currentNode = nodeName;
    comboInput.value = nodeName;
    if (highlight) {
      highlightTarget = highlight;
    } else if (!sameNode) {
      highlightTarget = null;
    }
    currentRows = await CraftMapApi.call(
      "get_galaxy_sources",
      nodeName,
      !asteroidCheckbox.checked
    );
    rebuildClimateFilter(currentRows);
    rebuildSunFilter(currentRows);
    await renderRows({ scrollToHighlight: !!highlight });
  }

  function clearBreadcrumb() {
    breadcrumbEl.classList.remove("show");
    breadcrumbEl.innerHTML = "";
  }

  function showBreadcrumb(fromLabel, nodeName) {
    breadcrumbEl.innerHTML = "";
    breadcrumbEl.classList.add("show");
    breadcrumbEl.appendChild(document.createTextNode(`from Sources: ${fromLabel} → `));
    const nodeSpan = document.createElement("span");
    nodeSpan.textContent = nodeName;
    breadcrumbEl.appendChild(nodeSpan);
    breadcrumbEl.appendChild(document.createTextNode(" "));
    const closeLink = document.createElement("a");
    closeLink.textContent = "✕";
    closeLink.addEventListener("click", clearBreadcrumb);
    breadcrumbEl.appendChild(closeLink);
  }

  function setupDropdown() {
    new LiveDropdown(comboInput, {
      getValues: () => CraftMapApi.call("get_galaxy_resource_names"),
      onSelect: (name) => {
        clearBreadcrumb();
        loadNode(name);
      },
    });
    comboInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const name = comboInput.value.trim();
        if (name) {
          clearBreadcrumb();
          loadNode(name);
        }
      }
    });
  }

  // Fetches (and caches, per system name - the graph doesn't depend on
  // which node type is currently shown) the hop-distance map for a newly
  // picked "current system", then re-renders so hop badges/sort react
  // immediately. A name with no known system_name match resolves to an
  // empty dict server-side (see backend.db.get_galaxy_hop_distances) -
  // every row's hop badge then reads as "? hops" rather than silently
  // doing nothing, so a typo is visible instead of invisible.
  async function setCurrentSystem(name) {
    currentSystemName = name || null;
    hopDistances = null;
    if (!currentSystemName) {
      await renderRows();
      return;
    }
    if (hopDistancesCache.has(currentSystemName)) {
      hopDistances = hopDistancesCache.get(currentSystemName);
    } else {
      hopDistances = await CraftMapApi.call("get_galaxy_hop_distances", currentSystemName);
      hopDistancesCache.set(currentSystemName, hopDistances);
    }
    await renderRows();
  }

  function setupCurrentSystemDropdown() {
    new LiveDropdown(currentSystemInput, {
      getValues: () => CraftMapApi.call("get_galaxy_system_names"),
      onSelect: (name) => setCurrentSystem(name),
    });
    currentSystemInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        setCurrentSystem(currentSystemInput.value.trim());
      }
    });
  }

  // Suggestions are scoped to sectors the CURRENTLY loaded node actually
  // turns up in (like the climate filter's chips), not every sector in the
  // galaxy - no point suggesting one this resource was never found in.
  function setSectorFilter(name) {
    sectorFilter = name || "";
    sectorFilterInput.value = sectorFilter;
    sectorFilterClearEl.classList.toggle("show", !!sectorFilter);
    renderRows();
  }

  function setupSectorFilterDropdown() {
    new LiveDropdown(sectorFilterInput, {
      getValues: () => [...new Set(currentRows.map((r) => r.sector).filter(Boolean))].sort(),
      onSelect: (name) => setSectorFilter(name),
    });
    sectorFilterInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        setSectorFilter(sectorFilterInput.value.trim());
      }
    });
    sectorFilterClearEl.addEventListener("click", () => setSectorFilter(""));
  }

  function setSortMode(mode) {
    sortMode = mode;
    sortRankBtn.classList.toggle("active", mode === "rank");
    sortDistanceBtn.classList.toggle("active", mode === "distance");
    sortCombinedBtn.classList.toggle("active", mode === "combined");
    renderRows();
  }

  sortRankBtn.addEventListener("click", () => setSortMode("rank"));
  sortDistanceBtn.addEventListener("click", () => setSortMode("distance"));
  sortCombinedBtn.addEventListener("click", () => setSortMode("combined"));

  asteroidCheckbox.addEventListener("change", () => {
    if (currentNode) loadNode(currentNode);
  });

  poiCheckbox.addEventListener("change", () => renderRows());
  mixedPoiCheckbox.addEventListener("change", () => renderRows());
  nonPoiCheckbox.addEventListener("change", () => renderRows());

  setupDropdown();
  setupCurrentSystemDropdown();
  setupSectorFilterDropdown();
  renderRows();

  // ---- external entry point: js/sources.js's double-click, or
  // js/deposits.js's own sub-tab switch, drive this rather than owning any
  // of the DOM/state above directly ----
  window.GalaxyView = {
    showForNode(nodeName, fromLabel, highlight) {
      if (fromLabel) {
        showBreadcrumb(fromLabel, nodeName);
      } else {
        clearBreadcrumb();
      }
      loadNode(nodeName, highlight);
    },
  };
})();
