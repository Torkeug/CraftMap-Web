/* Sources screen: shows which gatherable node names yield a given raw
 * resource (e.g. "a-Carbon" <- "Coal Clump", "Coal Deposit", "Vitreous
 * Carbon") - separate from the deposit tracker (frontend/js/deposits.js),
 * which logs specific manually-found in-game locations, not general
 * node-type categories.
 *
 * Read-only by design: this data is derived from the game's own files by
 * tools/backfill_resource_sources.py, not hand-maintained - unlike
 * deposits/recipes, there's no "your own observation" to record here, so
 * letting it drift from the game data via hand-edits would just make it
 * wrong. To change it, re-run the backfill script against updated game
 * data (see game_data_extract/README.md).
 */
(function () {
  const sourcesCombo = document.getElementById("sources-combo");
  const rowsEl = document.getElementById("sources-rows");
  const sortHeaders = {
    concentration: document.getElementById("sources-sort-concentration"),
    expected_qty: document.getElementById("sources-sort-expected_qty"),
  };

  // Sources come back from the backend already sorted (concentration desc,
  // name), but both columns are worth sorting by - a resource with lots of
  // near-tied concentrations is exactly the case expected_qty exists to
  // break, so re-sorting by it needs to be just as easy. Re-sorts the
  // already-fetched list client-side rather than re-querying, since both
  // fields are already present on every row.
  let currentSources = [];
  let sortState = { key: "concentration", dir: "desc" };

  function compareSortValue(a, b, key, dir) {
    const av = a[key];
    const bv = b[key];
    const aNull = av === null || av === undefined;
    const bNull = bv === null || bv === undefined;
    if (aNull && bNull) return 0;
    if (aNull) return 1; // nulls always sort last, regardless of direction
    if (bNull) return -1;
    return dir === "asc" ? av - bv : bv - av;
  }

  function sortedSources() {
    return [...currentSources].sort((a, b) =>
      compareSortValue(a, b, sortState.key, sortState.dir)
    );
  }

  function updateSortHeaders() {
    for (const [key, el] of Object.entries(sortHeaders)) {
      el.classList.toggle("sort-active", key === sortState.key);
      const arrow = key === sortState.key ? (sortState.dir === "asc" ? " ▲" : " ▼") : "";
      el.textContent = (key === "concentration" ? "Concentration" : "Avg Qty") + arrow;
    }
  }

  function fmtConcentration(concentration) {
    if (concentration === null || concentration === undefined) return "";
    const rounded = Math.round(concentration * 10) / 10;
    return `${rounded}%`;
  }

  // Concentration is a *relative* share among a node's same-kind siblings -
  // two different items at two different nodes can land on the exact same
  // % by coincidence. expectedQty is the average quantity actually
  // obtained per harvest of that node (the same number the game's own
  // Encyclopedia shows next to each contained item), an absolute figure
  // that breaks those ties - see tools/backfill_resource_sources.py.
  function fmtExpectedQty(expectedQty) {
    if (expectedQty === null || expectedQty === undefined) return "";
    return expectedQty.toFixed(2);
  }

  // Source nodes here are node TYPES (e.g. "Clay Shell"), a completely
  // different namespace from the raw material being searched for (e.g.
  // "Aquamarine") - galaxy_resources only ever holds live per-node
  // placement data, never a raw-material aggregate (see
  // backend.db.get_galaxy_sources_for_resource's own docstring), so a
  // single link off the search box can't work: two different node rows
  // for the same raw material can have completely unrelated galaxy
  // rankings. Double-clicking a specific row is the only correct link.
  function makeRow(name, concentration, expectedQty) {
    const rowEl = document.createElement("div");
    rowEl.className = "source-row linkable";
    rowEl.title = "Double-click to see where this node has been found";
    const nameEl = document.createElement("span");
    nameEl.className = "source-row-name";
    nameEl.textContent = name;
    rowEl.appendChild(nameEl);
    const concEl = document.createElement("span");
    concEl.className = "source-row-conc";
    concEl.textContent = fmtConcentration(concentration);
    rowEl.appendChild(concEl);
    const qtyEl = document.createElement("span");
    qtyEl.className = "source-row-qty";
    qtyEl.textContent = fmtExpectedQty(expectedQty);
    rowEl.appendChild(qtyEl);
    rowEl.addEventListener("dblclick", () => {
      document.getElementById("tab-resource").click();
      window.DepositsTabs.showGalaxyForNode(name, sourcesCombo.value.trim());
    });
    return rowEl;
  }

  function renderRows() {
    rowsEl.innerHTML = "";
    if (!currentSources.length) {
      const emptyEl = document.createElement("div");
      emptyEl.className = "source-row source-row-empty";
      emptyEl.textContent = "No known sources for this resource yet.";
      rowsEl.appendChild(emptyEl);
      return;
    }
    for (const s of sortedSources()) {
      rowsEl.appendChild(makeRow(s.name, s.concentration, s.expected_qty));
    }
  }

  async function loadResource(name) {
    sourcesCombo.value = name;
    currentSources = await CraftMapApi.call("get_resource_sources", name);
    renderRows();
  }

  async function onSourcesComboCommit() {
    const name = sourcesCombo.value.trim();
    if (!name) return;
    await loadResource(name);
  }

  async function init() {
    new LiveDropdown(sourcesCombo, {
      getValues: async () => {
        const [basics, sourced] = await Promise.all([
          CraftMapApi.call("get_basic_resources"),
          CraftMapApi.call("get_resources_with_sources"),
        ]);
        return [...new Set([...basics, ...sourced])].sort((a, b) =>
          a.toLowerCase().localeCompare(b.toLowerCase())
        );
      },
      onSelect: onSourcesComboCommit,
    });
    sourcesCombo.addEventListener("keydown", (e) => {
      if (e.key === "Enter") onSourcesComboCommit();
    });
    for (const [key, el] of Object.entries(sortHeaders)) {
      el.addEventListener("click", () => {
        // Both columns default to "biggest first" on first click of a new
        // column - that's the useful direction for either (highest
        // concentration or highest expected yield is the better source).
        sortState =
          sortState.key === key
            ? { key, dir: sortState.dir === "desc" ? "asc" : "desc" }
            : { key, dir: "desc" };
        updateSortHeaders();
        renderRows();
      });
    }
    updateSortHeaders();
  }

  init();
})();
