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

  function fmtConcentration(concentration) {
    if (concentration === null || concentration === undefined) return "";
    const rounded = Math.round(concentration * 10) / 10;
    return `${rounded}%`;
  }

  function makeRow(name, concentration) {
    const rowEl = document.createElement("div");
    rowEl.className = "source-row";
    const nameEl = document.createElement("span");
    nameEl.className = "source-row-name";
    nameEl.textContent = name;
    rowEl.appendChild(nameEl);
    const concEl = document.createElement("span");
    concEl.className = "source-row-conc";
    concEl.textContent = fmtConcentration(concentration);
    rowEl.appendChild(concEl);
    return rowEl;
  }

  async function loadResource(name) {
    sourcesCombo.value = name;
    rowsEl.innerHTML = "";
    const sources = await CraftMapApi.call("get_resource_sources", name);
    if (!sources.length) {
      const emptyEl = document.createElement("div");
      emptyEl.className = "source-row source-row-empty";
      emptyEl.textContent = "No known sources for this resource yet.";
      rowsEl.appendChild(emptyEl);
      return;
    }
    for (const s of sources) {
      rowsEl.appendChild(makeRow(s.name, s.concentration));
    }
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
  }

  init();
})();
