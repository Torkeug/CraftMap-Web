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
 * isolation. A filled ◆ marks a purely POI-anchored planet (already priced
 * into the ranking, not a separate judgment) vs a plain · for scattered/
 * mixed ones. Climate/water chips only render for non-default attributes -
 * a plain Temperate row gets no chip at all.
 *
 * Cross-references js/deposits.js's own manually-logged deposits for the
 * same node name (get_deposits_for_ingredient, the same lookup
 * breakdown-tree.js's ingredient-location popup already uses) to mark
 * rows you've already found in-game with a LOGGED pin - the one place
 * manual and automatic data actually meet.
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
  const nonPoiCheckbox = document.getElementById("galaxy-filter-non-poi");
  const climateFilterEl = document.getElementById("galaxy-climate-filter");
  const countLabelEl = document.getElementById("galaxy-count-label");
  const rowsEl = document.getElementById("galaxy-rows");
  const currentSystemInput = document.getElementById("galaxy-current-system");
  const sortRankBtn = document.getElementById("galaxy-sort-rank");
  const sortDistanceBtn = document.getElementById("galaxy-sort-distance");

  let currentNode = null;
  let currentRows = []; // raw rows from the last fetch (post asteroid-filter, pre climate-filter)
  const climateFilterState = new Map(); // chip label -> checked (session-only, rebuilt per node)
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
  let sortMode = "rank"; // "rank" (density-based, server order) | "distance" (hop count)

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

  function chipsForRow(row) {
    return [climateChip(row), waterChip(row)].filter(Boolean);
  }

  // ---- filter row (dynamic, rebuilt per node - only chips actually
  // present get a checkbox, mirroring js/deposits.js's own type-filter) ----
  function rebuildClimateFilter(rows) {
    const present = new Map(); // label -> cls
    for (const row of rows) {
      for (const chip of chipsForRow(row)) present.set(chip.label, chip.cls);
    }
    climateFilterEl.innerHTML = "";
    for (const [label, cls] of present) {
      if (!climateFilterState.has(label)) climateFilterState.set(label, true);
      const lbl = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = climateFilterState.get(label);
      cb.addEventListener("change", () => {
        climateFilterState.set(label, cb.checked);
        renderRows();
      });
      lbl.appendChild(cb);
      const chipEl = document.createElement("span");
      chipEl.className = `chip ${cls}`;
      chipEl.textContent = label;
      lbl.appendChild(chipEl);
      climateFilterEl.appendChild(lbl);
    }
    for (const stale of [...climateFilterState.keys()].filter((l) => !present.has(l))) {
      climateFilterState.delete(stale);
    }
  }

  // Reuses row.pure_poi (same field driving the ◆/· mark - see makeRow)
  // rather than a looser "has any poi tag at all" test: a "general,poi2"
  // row is already shown with a plain "·" since most of the resource is
  // still scattered planet-wide, so it belongs with the non-POI rows here
  // too - otherwise the checkboxes would disagree with the marks already
  // on screen.
  function passesPoiFilter(row) {
    return row.pure_poi ? poiCheckbox.checked : nonPoiCheckbox.checked;
  }

  function passesClimateFilter(row) {
    const chips = chipsForRow(row);
    if (!chips.length) return true; // plain Temperate/no-attribute rows always show
    return chips.every((c) => climateFilterState.get(c.label) !== false);
  }

  // ---- POI detail (revealed on row click - see makeRow's disclosure) ----
  function poiDescription(row) {
    if (!row.poi_tags) return "No POI placement data available for this planet.";
    const tags = row.poi_tags.split(",");
    const pois = tags.filter((t) => t !== "general");
    const hasGeneral = tags.includes("general");
    if (pois.length && !hasGeneral) {
      const plural = pois.length > 1 ? "s" : "";
      return `Concentrated at ${pois.length} POI${plural}: ${pois.join(", ")} - every node reachable without crossing the planet.`;
    }
    if (pois.length && hasGeneral) {
      return `Partly concentrated (${pois.join(", ")}) and partly scattered across the rest of the planet.`;
    }
    return "Scattered across the whole planet - no POI anchor.";
  }

  function makeExpandDetail(row) {
    const el = document.createElement("div");
    el.className = "galaxy-row-expand";

    const poiLine = document.createElement("div");
    poiLine.textContent = poiDescription(row);
    el.appendChild(poiLine);

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

  // ---- row rendering ----
  function makeRow(row, rank, isTop, effective, best, logged, highlighted, hops) {
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

    const markEl = document.createElement("span");
    markEl.className = "galaxy-mark" + (row.pure_poi ? "" : " scattered");
    markEl.textContent = row.pure_poi ? "◆" : "·";
    top.appendChild(markEl);

    const planetEl = document.createElement("span");
    planetEl.className = "galaxy-planet";
    planetEl.textContent = row.planet;
    planetEl.title = row.planet; // still truncates on very long names - full name on hover
    top.appendChild(planetEl);

    if (logged) {
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

    for (const chip of chipsForRow(row)) {
      const sep = document.createElement("span");
      sep.className = "galaxy-sep";
      sep.textContent = " · ";
      detail.appendChild(sep);
      const chipEl = document.createElement("span");
      chipEl.className = `chip ${chip.cls}`;
      chipEl.textContent = chip.label;
      detail.appendChild(chipEl);
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
    const visible = currentRows.filter((row) => passesPoiFilter(row) && passesClimateFilter(row));
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
    const loggedRows = await CraftMapApi.call("get_deposits_for_ingredient", currentNode);
    const loggedKeys = new Set(loggedRows.map((r) => `${r.system_name}|${r.planet}`));
    // Max, not visible[0] - visible[0] is only the best-density row when
    // still in the backend's own density-sorted order, which distance
    // sorting below deliberately overrides.
    const best = Math.max(...visible.map((row) => row.poi_area_density ?? row.density));

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
    }

    let highlightEl = null;
    visible.forEach((row, i) => {
      const effective = row.poi_area_density ?? row.density;
      const logged = loggedKeys.has(`${row.system_name}|${row.planet}`);
      const highlighted = isHighlightedRow(row);
      const hops = hopFor(row);
      const rowEl = makeRow(row, i + 1, i === 0, effective, best, logged, highlighted, hops);
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

  function setSortMode(mode) {
    sortMode = mode;
    sortRankBtn.classList.toggle("active", mode === "rank");
    sortDistanceBtn.classList.toggle("active", mode === "distance");
    renderRows();
  }

  sortRankBtn.addEventListener("click", () => setSortMode("rank"));
  sortDistanceBtn.addEventListener("click", () => setSortMode("distance"));

  asteroidCheckbox.addEventListener("change", () => {
    if (currentNode) loadNode(currentNode);
  });

  poiCheckbox.addEventListener("change", () => renderRows());
  nonPoiCheckbox.addEventListener("change", () => renderRows());

  setupDropdown();
  setupCurrentSystemDropdown();
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
