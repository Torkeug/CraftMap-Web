/* Recipe panel: combobox/quantity selector, Breakdown/Totals/Used-In tree
 * modes, and the (read-only) recipe detail form. Direct port of
 * craftmap/overlay.py's recipe-panel section (_build_recipe_panel,
 * _refresh_recipe_breakdown, _refresh_totals_view, _refresh_usedin_view,
 * _on_breakdown_click). The checkbox-cascade tree itself and the
 * alt-recipe/station step popover are shared with the Craft Queue panel -
 * see frontend/js/breakdown-tree.js.
 *
 * The station/output/ingredient rows below are display-only (readonly
 * inputs, no add/remove/save/delete) - recipes are verified against the
 * game's own data (see tools/verify_recipes_match_game_data.py) and hand-
 * editing them here would let that drift. To change a recipe, re-run
 * tools/backfill_recipe_metadata.py against updated game data.
 */
(function () {
  const {
    fmtNum,
    formatCraftMetaSuffix,
    formatByproductsSuffix,
    nodeActiveSeconds,
    nodePathKey,
    collectPathKeysJs,
    ensureFullyResolved,
    subtreeRemainingSeconds,
    nodeHasStepOptions,
    collectTotals,
    collectBasicCrafted,
    buildIngredientLabel,
  } = BreakdownTree;

  // ---- DOM refs ----
  const tree = document.getElementById("recipe-breakdown-tree");
  const recipeCombo = document.getElementById("recipe-combo");
  const recipeQty = document.getElementById("recipe-qty");
  const recipeAddQueueBtn = document.getElementById("recipe-add-queue-btn");
  const modeBreakdown = document.getElementById("mode-breakdown");
  const modeTotals = document.getElementById("mode-totals");
  const modeUsedin = document.getElementById("mode-usedin");
  const recipeName = document.getElementById("recipe-name");
  const stationRowsEl = document.getElementById("recipe-station-rows");
  const outputRowsEl = document.getElementById("recipe-output-rows");
  const ingredientRowsEl = document.getElementById("recipe-ingredient-rows");
  const stepPopupEl = document.getElementById("step-popup");

  const renderer = BreakdownTree.createRenderer({
    treeEl: tree,
    stepPopupEl,
    persistKey: "recipe_breakdown",
  });
  const { makeBdNode, appendDepositLocations, openStepPopup } = renderer;

  // ---- state ----
  let recipeMode = "breakdown"; // 'breakdown' | 'totals' | 'usedin'
  let viewingRecipeId = null; // recipe shown in both the tree and the edit form
  let usedinRecipeId = null;
  // Item name backing Used-In mode when there's no recipe id to derive it
  // from - i.e. a basic/raw resource selected straight from the combo
  // (see selectBasicResource). Ignored whenever usedinRecipeId is set,
  // since that case derives the current output name live instead.
  let usedinItemName = "";
  let usedinNavigatedAway = false;
  let stationRows = [];
  let outputRows = [];
  let ingredientRows = [];

  async function insertBreakdownNode(parentEl, node, recipeId, pathParts, checked) {
    const pathKey = nodePathKey(node, pathParts);
    const isDone = checked.has(pathKey);
    const { label: base, activeSeconds, activeMode } = buildIngredientLabel(node);
    const remaining = subtreeRemainingSeconds(node, pathParts, checked);
    let label = base;
    label += formatCraftMetaSuffix(node.station, activeSeconds, activeMode, remaining);
    label += formatByproductsSuffix(node.byproducts);

    const hasChildren = node.children.length > 0;
    const isRawLeaf = !node.is_recipe && !hasChildren && !node.truncated;
    const hasOptions = nodeHasStepOptions(node);
    // Building a node's children (recursively, all the way down) is
    // deferred behind onFirstExpand - not just the deposit-location
    // fetch, the DOM construction itself. Recursing into every
    // descendant unconditionally on every render meant a checkbox click
    // on a ~100-node tree rebuilt all ~100 rows every time even though at
    // most a handful were ever visible (everything but the root starts
    // collapsed) - this makes a render's cost proportional to what's
    // actually expanded, not the tree's total size.
    const { wrapper, childrenEl, expandPromise } = makeBdNode({
      tagClass: isDone ? "done" : "ingredient",
      label,
      checked: isDone,
      hasChildren: hasChildren || isRawLeaf || node.truncated === true,
      key: pathKey,
      onToggleCheck: async () => {
        await ensureFullyResolved(node, pathParts);
        const keys = collectPathKeysJs(node, pathParts);
        await CraftMapApi.call("set_checked_many", recipeId, keys, !isDone);
        await refreshBreakdown();
      },
      onOpenStep: hasOptions
        ? (e) =>
            openStepPopup(
              e.currentTarget,
              node,
              false,
              async (alt) => {
                await CraftMapApi.call("set_alt_pref", node.name, alt.recipe_id);
                await refreshBreakdown({ forceFull: true });
              },
              async (stName, mode) => {
                await CraftMapApi.call("set_station_pref", node.name, stName, mode);
                await refreshBreakdown({ forceFull: true });
              }
            )
        : null,
      onFirstExpand: node.truncated
        ? async (el) => {
            // get_recipe_breakdown/get_recipe_subtree only resolve a couple
            // of levels up front (see backend/api.py's _INITIAL_RESOLVE_DEPTH)
            // - this node came back as a stub with no real children yet.
            // Mutate `node` in place (rather than only using the result
            // locally) so it's also visible through `cachedTree`, meaning a
            // later plain checkbox toggle (which reuses that cache) sees
            // the real children too instead of re-truncating.
            const subtree = await CraftMapApi.call(
              "get_recipe_subtree",
              node.name,
              node.qty,
              pathParts
            );
            node.children = subtree.children;
            node.truncated = subtree.truncated;
            node.alts = subtree.alts;
            for (const child of node.children) {
              await insertBreakdownNode(el, child, recipeId, [...pathParts, node.name], checked);
            }
          }
        : isRawLeaf
        ? (el) => appendDepositLocations(el, node.name, "    ")
        : hasChildren
        ? async (el) => {
            for (const child of node.children) {
              await insertBreakdownNode(el, child, recipeId, [...pathParts, node.name], checked);
            }
          }
        : undefined,
    });
    parentEl.appendChild(wrapper);
    await expandPromise;
  }

  // ---- mode: breakdown ----
  // Pure render - takes already-fetched data so a plain checkbox toggle
  // (which only changes `checked`) doesn't need to re-resolve the whole
  // tree - see refreshBreakdown's cache.
  async function renderBreakdownMode(recipeId, outputName, node, checked, craftQty) {
    const oqty = node.output_qty || 1.0;
    const crafts = Math.ceil(craftQty / oqty);
    let rootLabel;
    if (craftQty === 1.0) {
      rootLabel = oqty > 1 ? `◆  ${outputName}  ×${fmtNum(oqty)}` : `◆  ${outputName}`;
    } else {
      rootLabel = `◆  ${outputName}  ×${fmtNum(craftQty)}`;
      if (crafts > 1 || oqty > 1) rootLabel += `  (${fmtNum(crafts)} crafts)`;
    }
    const rootHasOptions = nodeHasStepOptions(node);
    if (rootHasOptions) rootLabel += "  ▾";
    const [activeSeconds, activeMode] = nodeActiveSeconds(node);
    const rootRemaining = subtreeRemainingSeconds(node, [], checked);
    rootLabel += formatCraftMetaSuffix(node.station, activeSeconds, activeMode, rootRemaining);
    rootLabel += formatByproductsSuffix(node.byproducts);
    const rootPathKey = nodePathKey(node, []);
    const rootIsDone = checked.has(rootPathKey);

    const { wrapper, expandPromise } = makeBdNode({
      tagClass: "root",
      label: rootLabel,
      checked: rootIsDone,
      hasChildren: node.children.length > 0,
      isRoot: true,
      onToggleCheck: async () => {
        await ensureFullyResolved(node, []);
        const keys = collectPathKeysJs(node, []);
        await CraftMapApi.call("set_checked_many", recipeId, keys, !rootIsDone);
        await refreshBreakdown();
      },
      onOpenStep: rootHasOptions
        ? (e) =>
            openStepPopup(
              e.currentTarget,
              node,
              true,
              async (alt) => {
                // loadRecipeIntoForm already refreshes (with a new recipe
                // id, so the tree cache invalidates on its own).
                await loadRecipeIntoForm(alt.recipe_id, alt.recipe_name);
              },
              async (stName, mode) => {
                await CraftMapApi.call("set_station_pref", outputName, stName, mode);
                await refreshBreakdown({ forceFull: true });
              }
            )
        : null,
      onFirstExpand: async (el) => {
        for (const child of node.children) {
          // pathParts must be [node.name] here, not [] - the persisted
          // cascade keys (written when the root's own checkbox toggles)
          // are prefixed with the root's name, so a child's real path_key
          // is "<rootName>|<childName>". Rendering with [] here would
          // compute just "<childName>" and never match what got
          // persisted, permanently showing every child as unchecked
          // after a root-checkbox cascade - a real bug in the original
          // tkinter app (overlay.py's _refresh_recipe_breakdown has this
          // same mismatch) that's worth fixing here rather than
          // faithfully reproducing.
          await insertBreakdownNode(el, child, recipeId, [node.name], checked);
        }
      },
    });
    tree.appendChild(wrapper);
    await expandPromise;
  }

  // ---- mode: totals ----
  // Pure render, same rationale as renderBreakdownMode above.
  async function renderTotalsMode(recipeId, outputName, node, checked, craftQty) {
    const oqty = node.output_qty || 1.0;
    let rootLabel;
    if (craftQty === 1.0) {
      rootLabel = oqty > 1 ? `◆  ${outputName}  ×${fmtNum(oqty)}` : `◆  ${outputName}`;
    } else {
      const crafts = Math.ceil(craftQty / oqty);
      rootLabel = `◆  ${outputName}  ×${fmtNum(craftQty)}`;
      if (crafts > 1 || oqty > 1) rootLabel += `  (${fmtNum(crafts)} crafts)`;
    }
    const rootHasOptions = nodeHasStepOptions(node);
    if (rootHasOptions) rootLabel += "  ▾";
    const [rootActiveSeconds, rootActiveMode] = nodeActiveSeconds(node);
    const rootRemaining = subtreeRemainingSeconds(node, [], checked);
    rootLabel += formatCraftMetaSuffix(
      node.station,
      rootActiveSeconds,
      rootActiveMode,
      rootRemaining
    );
    rootLabel += formatByproductsSuffix(node.byproducts);
    const rootPathKey = nodePathKey(node, []);
    const rootIsDone = checked.has(rootPathKey);

    const { wrapper, childrenEl } = makeBdNode({
      tagClass: "total_header",
      label: rootLabel,
      checked: rootIsDone,
      hasChildren: true,
      isRoot: true,
      onToggleCheck: async () => {
        await ensureFullyResolved(node, []);
        const keys = collectPathKeysJs(node, []);
        await CraftMapApi.call("set_checked_many", recipeId, keys, !rootIsDone);
        await refreshBreakdown();
      },
      onOpenStep: rootHasOptions
        ? (e) =>
            openStepPopup(
              e.currentTarget,
              node,
              true,
              async (alt) => {
                await loadRecipeIntoForm(alt.recipe_id, alt.recipe_name);
              },
              async (stName, mode) => {
                await CraftMapApi.call("set_station_pref", outputName, stName, mode);
                await refreshBreakdown({ forceFull: true });
              }
            )
        : null,
    });
    tree.appendChild(wrapper);

    function insertRaw(parentEl, resName, qty, pathKey) {
      const isDone = checked.has(pathKey);
      const { wrapper: rawWrapper } = makeBdNode({
        tagClass: isDone ? "done" : "ingredient",
        label: `${fmtNum(qty)}×  ${resName}`,
        checked: isDone,
        hasChildren: true,
        key: pathKey,
        onToggleCheck: async () => {
          await CraftMapApi.call("set_checked_many", recipeId, [pathKey], !isDone);
          await refreshBreakdown();
        },
        onFirstExpand: (el) => appendDepositLocations(el, resName, "    "),
      });
      parentEl.appendChild(rawWrapper);
    }

    const basic = collectBasicCrafted(node);
    const basicEntries = Object.entries(basic).sort((a, b) =>
      a[0].toLowerCase().localeCompare(b[0].toLowerCase())
    );
    if (basicEntries.length) {
      const { wrapper: craftHdr, childrenEl: craftChildren } = makeBdNode({
        tagClass: "section",
        label: "── Crafted ──",
        hasChildren: true,
        key: "__crafted_section__",
      });
      childrenEl.appendChild(craftHdr);

      for (const [resName, info] of basicEntries) {
        const qty = info.qty;
        const oq = info.output_qty;
        const crafts = Math.ceil(qty / oq);
        const pathKey = `__craft__|${resName}`;
        const isDone = checked.has(pathKey);
        const hasOptions = nodeHasStepOptions(info);
        let suffix = oq > 1 ? `  (${fmtNum(crafts)} crafts)` : "";
        if (hasOptions) suffix += "  ▾";
        const [activeSeconds, activeMode] = nodeActiveSeconds(info);
        const ownTime = activeSeconds ? activeSeconds * crafts : 0.0;
        const remaining = isDone ? 0.0 : ownTime;
        suffix += formatCraftMetaSuffix(info.station, activeSeconds, activeMode, remaining);
        suffix += formatByproductsSuffix(info.byproducts);

        const { wrapper: entryWrapper, childrenEl: entryChildren } = makeBdNode({
          tagClass: isDone ? "done" : "ingredient",
          label: `${fmtNum(qty)}×  ${resName}${suffix}`,
          checked: isDone,
          hasChildren: info.raw_names.length > 0,
          key: pathKey,
          onToggleCheck: async () => {
            await CraftMapApi.call("set_checked_many", recipeId, [pathKey], !isDone);
            await refreshBreakdown();
          },
          onOpenStep: hasOptions
            ? (e) =>
                openStepPopup(
                  e.currentTarget,
                  info,
                  false,
                  async (alt) => {
                    await CraftMapApi.call("set_alt_pref", resName, alt.recipe_id);
                    await refreshBreakdown({ forceFull: true });
                  },
                  async (stName, mode) => {
                    await CraftMapApi.call("set_station_pref", resName, stName, mode);
                    await refreshBreakdown({ forceFull: true });
                  }
                )
            : null,
        });
        craftChildren.appendChild(entryWrapper);

        for (const rawName of info.raw_names) {
          const { wrapper: rawWrapper } = makeBdNode({
            tagClass: "location",
            label: `    ${rawName}`,
            hasChildren: true,
            key: `${pathKey}__raw__${rawName}`,
            onFirstExpand: (el) => appendDepositLocations(el, rawName, "      "),
          });
          entryChildren.appendChild(rawWrapper);
        }
      }
    }

    const { wrapper: rawHdr, childrenEl: rawChildren } = makeBdNode({
      tagClass: "section",
      label: "── Raw materials ──",
      hasChildren: true,
      key: "__raw_section__",
    });
    childrenEl.appendChild(rawHdr);
    const totals = collectTotals(node);
    const totalEntries = Object.entries(totals).sort((a, b) =>
      a[0].toLowerCase().localeCompare(b[0].toLowerCase())
    );
    for (const [resName, qty] of totalEntries) {
      insertRaw(rawChildren, resName, qty, `__total__|${resName}`);
    }
  }

  // ---- mode: used in ----
  async function renderUsedinMode() {
    const viewId = usedinRecipeId;
    const itemName =
      viewId !== null
        ? await CraftMapApi.call("get_recipe_output_name", viewId)
        : usedinItemName;
    if (!itemName) {
      const wrapper = document.createElement("div");
      wrapper.className = "bd-node";
      const row = document.createElement("div");
      row.className = "bd-row section";
      const disc = document.createElement("span");
      disc.className = "disclosure";
      row.appendChild(disc);
      const spacer = document.createElement("span");
      spacer.className = "cb-icon-spacer";
      row.appendChild(spacer);
      const labelEl = document.createElement("span");
      labelEl.className = "bd-label";
      labelEl.textContent = "Select a recipe or raw resource above to see where it's used.";
      row.appendChild(labelEl);
      wrapper.appendChild(row);
      tree.appendChild(wrapper);
      return;
    }
    const rows = await CraftMapApi.call("get_recipes_using_ingredient", itemName);
    const recipeName_ = viewId !== null ? await CraftMapApi.call("get_recipe_name", viewId) : "";

    const { wrapper, childrenEl } = makeBdNode({
      tagClass: "root",
      label: `Recipes using  "${itemName}"`,
      hasChildren: true,
      isRoot: true,
    });
    // Clicking the header (not a specific result) loads this item into the
    // edit form without leaving Used-In mode - matches usedin_header in
    // overlay.py's _on_breakdown_click. Only wired up when viewing an
    // actual recipe's output - a basic resource (viewId === null) has no
    // recipe of its own to load.
    if (viewId !== null) {
      wrapper.querySelector(".bd-label").addEventListener("click", async () => {
        if (recipeName_) {
          await loadRecipeIntoForm(viewId, recipeName_);
        }
      });
    }
    tree.appendChild(wrapper);

    if (!rows.length) {
      const noneWrapper = document.createElement("div");
      noneWrapper.className = "bd-node";
      const row = document.createElement("div");
      row.className = "bd-row section";
      const disc = document.createElement("span");
      disc.className = "disclosure";
      row.appendChild(disc);
      const spacer = document.createElement("span");
      spacer.className = "cb-icon-spacer";
      row.appendChild(spacer);
      const labelEl = document.createElement("span");
      labelEl.className = "bd-label";
      labelEl.textContent = "  (none found)";
      row.appendChild(labelEl);
      noneWrapper.appendChild(row);
      childrenEl.appendChild(noneWrapper);
      return;
    }

    for (const row of rows) {
      let label = `×${fmtNum(row.qty)}  →  ${row.recipe_name}`;
      const oqSuffix = row.output_qty !== 1 ? `  ×${fmtNum(row.output_qty)}` : "";
      if (row.output_name !== row.recipe_name) {
        label += `  [${row.output_name}${oqSuffix}]`;
      } else if (oqSuffix) {
        label += oqSuffix;
      }
      const rowWrapper = document.createElement("div");
      rowWrapper.className = "bd-node";
      const rowEl = document.createElement("div");
      rowEl.className = "bd-row ingredient usedin-result";
      const disc = document.createElement("span");
      disc.className = "disclosure";
      rowEl.appendChild(disc);
      const spacer = document.createElement("span");
      spacer.className = "cb-icon-spacer";
      rowEl.appendChild(spacer);
      const labelEl = document.createElement("span");
      labelEl.className = "bd-label";
      labelEl.textContent = label;
      rowEl.appendChild(labelEl);
      rowWrapper.appendChild(rowEl);
      rowEl.addEventListener("dblclick", async () => {
        usedinNavigatedAway = true;
        await loadRecipeIntoForm(row.recipe_id, row.recipe_name);
        await setRecipeMode("breakdown");
      });
      childrenEl.appendChild(rowWrapper);
    }
  }

  // ---- refresh dispatcher ----
  // Caches the last-resolved tree so a plain checkbox toggle (the only
  // thing that changes is `checked`) doesn't have to pay for another
  // resolve_recipe_tree call and cross-process round-trip - only
  // get_checked_paths needs to be fresh. Invalidated (forceFull) whenever
  // something that actually changes the tree's shape happens: switching
  // recipes, changing the quantity, or picking an alt recipe/station.
  let cachedTree = null;
  let cachedOutputName = "";
  let cachedForRecipeId = null;
  let cachedForQty = null;

  async function refreshBreakdown({ forceFull = false } = {}) {
    await renderer.ready;
    tree.innerHTML = "";
    try {
      if (recipeMode === "usedin") {
        await renderUsedinMode();
        return;
      }
      if (viewingRecipeId === null) return;

      let craftQty = parseFloat(recipeQty.value);
      if (!isFinite(craftQty) || craftQty <= 0) craftQty = 1.0;

      const cacheValid =
        !forceFull &&
        cachedTree !== null &&
        cachedForRecipeId === viewingRecipeId &&
        cachedForQty === craftQty;

      let checked;
      if (cacheValid) {
        const checkedList = await CraftMapApi.call("get_checked_paths", viewingRecipeId);
        checked = new Set(checkedList);
      } else {
        const view = await CraftMapApi.call(
          "get_breakdown_view",
          viewingRecipeId,
          craftQty
        );
        if (!view.output_name) return;
        cachedTree = view.tree;
        cachedOutputName = view.output_name;
        cachedForRecipeId = viewingRecipeId;
        cachedForQty = craftQty;
        checked = new Set(view.checked);
      }

      if (recipeMode === "totals") {
        await renderTotalsMode(
          viewingRecipeId,
          cachedOutputName,
          cachedTree,
          checked,
          craftQty
        );
      } else {
        await renderBreakdownMode(
          viewingRecipeId,
          cachedOutputName,
          cachedTree,
          checked,
          craftQty
        );
      }
    } catch (e) {
      CraftMapApi._showError(`refreshBreakdown: ${e.message || e}`);
      throw e;
    }
  }

  // ---- mode tabs ----
  function updateModeTabs() {
    modeBreakdown.classList.toggle("active", recipeMode === "breakdown");
    modeTotals.classList.toggle("active", recipeMode === "totals");
    modeUsedin.classList.toggle("active", recipeMode === "usedin");
  }

  async function setRecipeMode(mode) {
    recipeMode = mode;
    if (mode === "usedin") {
      if (!usedinNavigatedAway) {
        usedinRecipeId = viewingRecipeId;
      } else if (usedinRecipeId !== null) {
        const rname = await CraftMapApi.call("get_recipe_name", usedinRecipeId);
        if (rname) await loadRecipeIntoForm(usedinRecipeId, rname);
      }
      usedinNavigatedAway = false;
    }
    updateModeTabs();
    await refreshBreakdown();
  }

  // ---- detail form: read-only rows ----
  // Plain readonly <input>s (rather than <span>s) so the existing
  // station/output/ingredient-row styling applies unchanged and values
  // stay selectable/copyable - just no add/remove/edit affordances.
  function addStationRow(station = "", auto = "", manual = "") {
    const rowEl = document.createElement("div");
    rowEl.className = "station-row";
    const stationInput = document.createElement("input");
    stationInput.type = "text";
    stationInput.value = station;
    stationInput.readOnly = true;
    const autoInput = document.createElement("input");
    autoInput.type = "text";
    autoInput.value = auto;
    autoInput.className = "narrow-input";
    autoInput.readOnly = true;
    const manualInput = document.createElement("input");
    manualInput.type = "text";
    manualInput.value = manual;
    manualInput.className = "narrow-input";
    manualInput.readOnly = true;
    rowEl.appendChild(stationInput);
    rowEl.appendChild(autoInput);
    rowEl.appendChild(manualInput);
    stationRowsEl.appendChild(rowEl);
    stationRows.push({ stationInput, autoInput, manualInput, rowEl });
  }

  function clearStationRows() {
    for (const row of stationRows) row.rowEl.remove();
    stationRows = [];
  }

  function addOutputRow(name = "", qty = 1) {
    const rowEl = document.createElement("div");
    rowEl.className = "output-row";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = name;
    nameInput.className = "wide-input";
    nameInput.readOnly = true;
    const qtyInput = document.createElement("input");
    qtyInput.type = "text";
    qtyInput.value = String(qty);
    qtyInput.className = "narrow-input";
    qtyInput.readOnly = true;
    rowEl.appendChild(nameInput);
    rowEl.appendChild(qtyInput);
    outputRowsEl.appendChild(rowEl);
    outputRows.push({ nameInput, qtyInput, rowEl });
  }

  function clearOutputRows() {
    for (const row of outputRows) row.rowEl.remove();
    outputRows = [];
  }

  function addIngredientRow(name = "", qty = 1) {
    const rowEl = document.createElement("div");
    rowEl.className = "ingredient-row";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = name;
    nameInput.className = "wide-input";
    nameInput.readOnly = true;
    const qtyInput = document.createElement("input");
    qtyInput.type = "text";
    qtyInput.value = String(qty);
    qtyInput.className = "narrow-input";
    qtyInput.readOnly = true;
    rowEl.appendChild(nameInput);
    rowEl.appendChild(qtyInput);
    ingredientRowsEl.appendChild(rowEl);
    ingredientRows.push({ nameInput, qtyInput, rowEl });
    ingredientRowsEl.scrollTop = ingredientRowsEl.scrollHeight;
  }

  function clearIngredientRows() {
    for (const row of ingredientRows) row.rowEl.remove();
    ingredientRows = [];
  }

  // ---- form load/clear ----
  async function loadRecipeIntoForm(recipeId, rname) {
    if (recipeId !== viewingRecipeId) {
      // A genuinely different recipe's path_keys don't mean anything to
      // this tree - only reset expand state when the *subject* changes,
      // not on every refresh of the recipe already being viewed (that's
      // the whole point of tracking it at all).
      renderer.resetExpandState();
    }
    viewingRecipeId = recipeId;
    recipeCombo.value = rname;
    recipeName.value = rname;

    clearStationRows();
    const stations = await CraftMapApi.call("get_recipe_stations", recipeId);
    for (const s of stations) {
      addStationRow(s.station, s.auto !== null && s.auto !== undefined ? fmtNum(s.auto) : "", s.manual !== null && s.manual !== undefined ? fmtNum(s.manual) : "");
    }

    clearOutputRows();
    const outputs = await CraftMapApi.call("get_recipe_outputs", recipeId);
    for (const o of outputs) addOutputRow(o.name, o.qty);

    clearIngredientRows();
    const ingredients = await CraftMapApi.call("get_recipe_ingredients", recipeId);
    for (const i of ingredients) addIngredientRow(i.name, i.qty);

    await refreshBreakdown();
  }

  // A basic/raw resource has no recipe of its own - nothing to breakdown or
  // show in the detail form, so just clear it and jump straight to Used-In
  // mode for it, keyed by name rather than a recipe id (see usedinItemName).
  async function selectBasicResource(name) {
    viewingRecipeId = null;
    renderer.resetExpandState();
    recipeCombo.value = name;
    recipeName.value = "";
    clearStationRows();
    clearOutputRows();
    clearIngredientRows();
    usedinRecipeId = null;
    usedinItemName = name;
    usedinNavigatedAway = false;
    recipeMode = "usedin";
    updateModeTabs();
    await refreshBreakdown();
  }

  async function onRecipeComboCommit() {
    const name = recipeCombo.value.trim();
    if (!name) return;
    const recipeId = await CraftMapApi.call("get_recipe_by_name", name);
    if (recipeId !== null) {
      usedinRecipeId = recipeId;
      usedinNavigatedAway = false;
      await loadRecipeIntoForm(recipeId, name);
      return;
    }
    const basics = await CraftMapApi.call("get_basic_resources");
    if (basics.includes(name)) {
      await selectBasicResource(name);
    }
  }

  // ---- init ----
  async function init() {
    new LiveDropdown(recipeCombo, {
      getValues: async () => {
        const [recipes, basics] = await Promise.all([
          CraftMapApi.call("get_all_recipes"),
          CraftMapApi.call("get_basic_resources"),
        ]);
        return [...recipes.map((r) => r.name), ...basics];
      },
      onSelect: onRecipeComboCommit,
    });
    recipeCombo.addEventListener("keydown", (e) => {
      if (e.key === "Enter") onRecipeComboCommit();
    });

    recipeQty.addEventListener("keydown", (e) => {
      if (e.key === "Enter") refreshBreakdown();
    });
    recipeQty.addEventListener("blur", refreshBreakdown);

    modeBreakdown.addEventListener("click", () => setRecipeMode("breakdown"));
    modeTotals.addEventListener("click", () => setRecipeMode("totals"));
    modeUsedin.addEventListener("click", () => setRecipeMode("usedin"));

    recipeAddQueueBtn.addEventListener("click", async () => {
      if (viewingRecipeId === null) {
        CraftMapApi._showError("Select a recipe first.");
        return;
      }
      let qty = parseFloat(recipeQty.value);
      if (!isFinite(qty) || qty <= 0) qty = 1.0;
      await CraftMapApi.call("add_to_queue", viewingRecipeId, qty);
      await CraftMapApi.call("show_queue_window");
    });

    updateModeTabs();

    // This tree gets noticeably less vertical space than the deposit
    // tree (the edit form below it - stations/outputs/ingredients - is
    // taller than the deposit form), so the browser's default wheel
    // scroll distance covers a bigger fraction of what's visible here
    // and feels jumpier. Scale it down rather than touching the deposit
    // tree, which is fine at the default.
    tree.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        tree.scrollTop += e.deltaY * 0.15;
      },
      { passive: false }
    );
  }

  init();
})();
