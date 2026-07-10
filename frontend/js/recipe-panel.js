/* Recipe panel: combobox/quantity selector, Breakdown/Totals/Used-In tree
 * modes, checkbox-cascade tree, alt-recipe/station step popup, and the
 * recipe edit form. Direct port of craftmap/overlay.py's recipe-panel
 * section (_build_recipe_panel, _refresh_recipe_breakdown,
 * _refresh_totals_view, _refresh_usedin_view, _on_breakdown_click,
 * save_recipe_action/delete_recipe_action, _StepPopup).
 *
 * The tree is real DOM (one .bd-node per row) instead of a ttk.Treeview,
 * so click handlers can be attached directly per row instead of needing
 * an iid->info lookup table and manual dispatch-by-click-position the
 * way overlay.py's _on_breakdown_click did - and CSS text-wrap replaces
 * _wrap_label's manual pixel-measurement entirely.
 */
(function () {
  // ---- pure helpers ported from overlay.py / backend/resolver.py ----

  function fmtNum(n) {
    // Python's f"{x:g}" - trims trailing zeros and a trailing decimal point.
    if (!isFinite(n)) return String(n);
    if (Number.isInteger(n)) return String(n);
    return parseFloat(n.toPrecision(12)).toString();
  }

  function formatDuration(seconds) {
    const total = Math.round(seconds);
    const h = Math.floor(total / 3600);
    const rem = total % 3600;
    const m = Math.floor(rem / 60);
    const s = rem % 60;
    const parts = [];
    if (h) parts.push(`${h}h`);
    if (m) parts.push(`${m}m`);
    if (s || !parts.length) parts.push(`${s}s`);
    return parts.join(" ");
  }

  function remainingPart(seconds) {
    if (!seconds || seconds <= 0) return null;
    return `  ${formatDuration(seconds)} left`;
  }

  function formatCraftMetaSuffix(station, perCraftSeconds, mode, remainingSeconds) {
    mode = mode || "auto";
    const parts = [];
    if (station) parts.push(`@ ${station} · ${mode[0].toUpperCase()}${mode.slice(1)}`);
    const rem = remainingPart(remainingSeconds);
    if (rem) parts.push(rem.trim());
    if (perCraftSeconds) parts.push(`${formatDuration(perCraftSeconds)}/craft`);
    if (!parts.length) return "";
    return "  " + parts.join("  ");
  }

  function formatByproductsSuffix(byproducts) {
    if (!byproducts || !byproducts.length) return "";
    const parts = byproducts.map((b) => `+${fmtNum(b.qty)} ${b.name}`);
    return "  (" + parts.join(", ") + ")";
  }

  function nodeCrafts(node) {
    if (!node.is_recipe) return 0;
    return Math.ceil(node.qty / (node.output_qty || 1.0));
  }

  function nodeActiveSeconds(node) {
    const mode = node.craft_mode || "auto";
    const seconds = mode === "auto" ? node.auto_craft_seconds : node.manual_craft_seconds;
    return [seconds, mode];
  }

  function nodeOwnTime(node) {
    const [seconds] = nodeActiveSeconds(node);
    if (!seconds) return 0.0;
    return seconds * nodeCrafts(node);
  }

  function nodePathKey(node, pathParts) {
    return [...pathParts, node.name].join("|");
  }

  // Mirrors resolver._collect_path_keys exactly (same recursion, same
  // nodePathKey/_node_path_key formula) - computed locally instead of
  // round-tripped through Api.collect_path_keys/toggle_checked_cascade,
  // since sending the *entire* resolved tree back to Python as a call
  // argument just to walk it turned out to cost 200ms+ on a ~100-node
  // tree (payload marshaling size, not call-count, is what's expensive
  // over this pywebview/pythonnet bridge - confirmed by timing every
  // call: plain small-payload calls run in single-digit ms regardless of
  // how many of them fire, but the two calls carrying a full tree in
  // either direction each took several hundred ms). collect_path_keys
  // is simple and low-risk enough to duplicate here; resolve_recipe_tree
  // itself stays server-side.
  function collectPathKeysJs(node, pathParts) {
    const keys = [nodePathKey(node, pathParts)];
    for (const child of node.children) {
      keys.push(...collectPathKeysJs(child, [...pathParts, node.name]));
    }
    return keys;
  }

  // A checkbox cascade must see the *whole* subtree, but a node the user
  // never actually expanded may still be sitting there as a truncated
  // stub (empty children, see resolve_recipe_tree's max_depth) - fetch
  // whatever's still missing before collectPathKeysJs walks it, or a
  // check on an unexpanded deep node would silently only toggle itself.
  // No-ops (no extra round-trip) for anything already resolved, which
  // covers the common case of checking something already visible.
  async function ensureFullyResolved(node, pathParts) {
    if (node.truncated) {
      const subtree = await CraftMapApi.call(
        "get_recipe_subtree",
        node.name,
        node.qty,
        pathParts
      );
      node.children = subtree.children;
      node.truncated = subtree.truncated;
      node.alts = subtree.alts;
    }
    for (const child of node.children) {
      await ensureFullyResolved(child, [...pathParts, node.name]);
    }
  }

  function subtreeRemainingSeconds(node, pathParts, checked) {
    if (checked.has(nodePathKey(node, pathParts))) return 0.0;
    let total = nodeOwnTime(node);
    for (const child of node.children) {
      total += subtreeRemainingSeconds(child, [...pathParts, node.name], checked);
    }
    return total;
  }

  function nodeHasStepOptions(node) {
    if (!node.is_recipe) return false;
    if (node.alts && node.alts.length) return true;
    let modesAvailable = 0;
    for (const st of node.stations || []) {
      if (st[1]) modesAvailable++;
      if (st[2]) modesAvailable++;
    }
    return modesAvailable > 1;
  }

  function collectTotals(node, totals) {
    totals = totals || {};
    if (!node.is_recipe && node.children.length === 0) {
      totals[node.name] = (totals[node.name] || 0) + node.qty;
    }
    for (const child of node.children) collectTotals(child, totals);
    return totals;
  }

  function collectBasicCrafted(node, totals) {
    totals = totals || {};
    for (const child of node.children) {
      if (!child.is_recipe) continue;
      if (child.children.some((c) => c.is_recipe)) {
        collectBasicCrafted(child, totals);
      } else {
        if (!totals[child.name]) {
          totals[child.name] = {
            is_recipe: true,
            qty: 0.0,
            output_qty: child.output_qty || 1.0,
            alts: child.alts || [],
            stations: child.stations || [],
            raw_names: [...new Set(child.children.map((c) => c.name))].sort((a, b) =>
              a.toLowerCase().localeCompare(b.toLowerCase())
            ),
            station: child.station,
            auto_craft_seconds: child.auto_craft_seconds,
            manual_craft_seconds: child.manual_craft_seconds,
            craft_mode: child.craft_mode || "auto",
            byproducts: child.byproducts || [],
          };
        }
        totals[child.name].qty += child.qty;
      }
    }
    return totals;
  }

  // ---- DOM refs ----
  const tree = document.getElementById("recipe-breakdown-tree");
  const recipeCombo = document.getElementById("recipe-combo");
  const recipeNewBtn = document.getElementById("recipe-new-btn");
  const recipeQty = document.getElementById("recipe-qty");
  const modeBreakdown = document.getElementById("mode-breakdown");
  const modeTotals = document.getElementById("mode-totals");
  const modeUsedin = document.getElementById("mode-usedin");
  const recipeName = document.getElementById("recipe-name");
  const stationRowsEl = document.getElementById("recipe-station-rows");
  const outputRowsEl = document.getElementById("recipe-output-rows");
  const ingredientRowsEl = document.getElementById("recipe-ingredient-rows");
  const stepPopup = document.getElementById("step-popup");

  // ---- state ----
  let recipeMode = "breakdown"; // 'breakdown' | 'totals' | 'usedin'
  let viewingRecipeId = null; // recipe shown in both the tree and the edit form
  let usedinRecipeId = null;
  let usedinNavigatedAway = false;
  let recipeRootOpen = true;
  // Every node's expand/collapse state survives a tree rebuild (checkbox
  // clicks, quantity changes, alt/station picks all rebuild the whole
  // tree) - tracked by path_key since node identity itself doesn't
  // survive a rebuild. overlay.py's tkinter version only kept the root's
  // state across a rebuild and re-collapsed everything else every time;
  // that read as "the tree collapsed on me" here since a click anywhere
  // deep in a large expanded tree wiped out all that manual drilling-down.
  let openNodeKeys = new Set();
  // A checkbox click's own visual feedback only lands after the full
  // collect_path_keys + set_checked_many + refreshBreakdown round-trip
  // (a few hundred ms of real IPC latency) - with nothing shown in the
  // meantime, an impatient second click before that lands fires the same
  // toggle again, flipping it right back off (or on) and netting no
  // visible change at all, which looked exactly like "cascade doesn't
  // work." This guard makes every checkbox a no-op while one toggle for
  // this tree is still in flight.
  let breakdownBusy = false;
  let stationRows = [];
  let outputRows = [];
  let ingredientRows = [];

  // ---- checkbox icon ----
  function makeCheckboxIcon(checked) {
    const span = document.createElement("span");
    span.className = "cb-icon " + (checked ? "checked" : "unchecked");
    return span;
  }

  // ---- breakdown tree row builders ----
  function makeBdNode({
    tagClass,
    label,
    checked,
    hasChildren,
    onToggleCheck,
    onOpenStep,
    key,
    onFirstExpand,
  }) {
    const wrapper = document.createElement("div");
    wrapper.className = "bd-node";
    if (key) wrapper.dataset.key = key;
    const startsOpen =
      key === "recipe_root" ? recipeRootOpen : key && openNodeKeys.has(key);
    if (hasChildren && !startsOpen) {
      wrapper.classList.add("collapsed");
    }

    const row = document.createElement("div");
    row.className = "bd-row " + tagClass;

    const disc = document.createElement("span");
    disc.className = "disclosure";
    let expandLoaded = !onFirstExpand;
    if (hasChildren) {
      disc.textContent = "▸";
      disc.addEventListener("click", async (e) => {
        e.stopPropagation();
        const wasCollapsed = wrapper.classList.contains("collapsed");
        // Deposit-location lookups are a real IPC round-trip here (unlike
        // the tkinter app, where the same lookup was an in-process SQLite
        // call) - fetching them eagerly for every raw-resource leaf in a
        // large tree meant dozens of sequential round-trips per render,
        // which is what made a checkbox click on a big subtree look like
        // it "didn't cascade" (the tree was still mid-render when checked).
        // Deferring the fetch to first-expand means a render only ever
        // pays for the nodes actually visible.
        if (wasCollapsed && !expandLoaded) {
          expandLoaded = true;
          await onFirstExpand(childrenEl);
        }
        wrapper.classList.toggle("collapsed");
        const nowOpen = !wrapper.classList.contains("collapsed");
        if (key === "recipe_root") {
          recipeRootOpen = nowOpen;
        } else if (key) {
          if (nowOpen) openNodeKeys.add(key);
          else openNodeKeys.delete(key);
        }
      });
    }
    row.appendChild(disc);

    if (checked !== undefined) {
      const cb = makeCheckboxIcon(checked);
      cb.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (breakdownBusy) return;
        breakdownBusy = true;
        // Instant feedback before the round-trip lands, so the click
        // doesn't feel like it did nothing (see breakdownBusy above).
        // Flips whichever way it's currently facing - not hardcoded to
        // "checked", since this same handler also unchecks.
        cb.classList.toggle("checked");
        cb.classList.toggle("unchecked");
        cb.classList.add("pending");
        try {
          await onToggleCheck();
        } finally {
          breakdownBusy = false;
        }
      });
      row.appendChild(cb);
    } else {
      const spacer = document.createElement("span");
      spacer.className = "cb-icon-spacer";
      row.appendChild(spacer);
    }

    const labelEl = document.createElement("span");
    labelEl.className = "bd-label";
    labelEl.textContent = label;
    row.appendChild(labelEl);

    if (onOpenStep) {
      labelEl.classList.add("has-options");
      labelEl.addEventListener("click", (e) => onOpenStep(e));
    }

    wrapper.appendChild(row);
    const childrenEl = document.createElement("div");
    childrenEl.className = "bd-children";
    wrapper.appendChild(childrenEl);

    // A node that starts open (the root, or one the user previously
    // expanded) needs its children built right away, same as a real
    // expand-click would - but nothing here waited for a click, so drive
    // it directly and hand the caller a promise to await instead of
    // firing it from inside the disclosure's click handler.
    let expandPromise = Promise.resolve();
    if (startsOpen && hasChildren && onFirstExpand && !expandLoaded) {
      expandLoaded = true;
      expandPromise = onFirstExpand(childrenEl);
    }

    return { wrapper, childrenEl, expandPromise };
  }

  function makeLocationRow(text) {
    const wrapper = document.createElement("div");
    wrapper.className = "bd-node";
    const row = document.createElement("div");
    row.className = "bd-row location";
    const disc = document.createElement("span");
    disc.className = "disclosure";
    row.appendChild(disc);
    const spacer = document.createElement("span");
    spacer.className = "cb-icon-spacer";
    row.appendChild(spacer);
    const labelEl = document.createElement("span");
    labelEl.className = "bd-label";
    labelEl.textContent = text;
    row.appendChild(labelEl);
    wrapper.appendChild(row);
    return wrapper;
  }

  async function appendDepositLocations(childrenEl, resourceName, indent) {
    const locs = await CraftMapApi.call("get_deposits_for_ingredient", resourceName);
    for (const loc of locs) {
      const parts = [loc.sector, loc.system_name, loc.planet].filter(Boolean);
      let text = `${indent}\u{1F4CD} ${parts.join(" / ")}`;
      if (loc.status && loc.status !== "Unknown" && loc.status !== "") {
        text += `  [${loc.status}]`;
      }
      childrenEl.appendChild(makeLocationRow(text));
    }
  }

  function buildIngredientLabel(node) {
    const qtyStr = fmtNum(node.qty);
    let label = `${qtyStr}×  ${node.name}`;
    const usedRecipe = node.recipe_name || node.name;
    if (usedRecipe && usedRecipe !== node.name) label += `  [${usedRecipe}]`;
    if (nodeHasStepOptions(node)) label += "  ▾";
    const [activeSeconds, activeMode] = nodeActiveSeconds(node);
    return { label, activeSeconds, activeMode };
  }

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
    // deferred behind the SAME onFirstExpand mechanism as the deposit-
    // location lookup above - not just the fetch, the DOM construction
    // itself. Recursing into every descendant unconditionally on every
    // render meant a checkbox click on a ~100-node tree rebuilt all ~100
    // rows every time even though at most a handful were ever visible
    // (everything but the root starts collapsed) - this makes a render's
    // cost proportional to what's actually expanded, not the tree's total
    // size. makeBdNode fires this immediately (instead of waiting for a
    // click) for anything that starts open, i.e. the root and anything
    // the user had already expanded.
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
        ? (e) => openStepPopup(e.currentTarget, node, node.name, false)
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

  // ---- step popup (alt-recipe / station+mode picker) ----
  function closeStepPopup() {
    stepPopup.classList.add("hidden");
    stepPopup.innerHTML = "";
    document.removeEventListener("mousedown", onStepPopupOutsideClick, true);
    document.removeEventListener("keydown", onStepPopupEscape, true);
  }

  function onStepPopupOutsideClick(e) {
    if (!stepPopup.contains(e.target)) closeStepPopup();
  }

  function onStepPopupEscape(e) {
    if (e.key === "Escape") closeStepPopup();
  }

  function addPopupOption(label, selected, onPick) {
    const row = document.createElement("div");
    row.className = "step-option" + (selected ? " selected" : "");
    row.textContent = (selected ? "●  " : "    ") + label;
    row.addEventListener("mousedown", (e) => {
      e.preventDefault();
      onPick();
      closeStepPopup();
    });
    stepPopup.appendChild(row);
  }

  function addPopupSectionLabel(text) {
    const lbl = document.createElement("div");
    lbl.className = "step-section-label";
    lbl.textContent = text;
    stepPopup.appendChild(lbl);
  }

  function openStepPopup(anchorEl, node, ingredientName, isRoot) {
    stepPopup.innerHTML = "";
    const alts = node.alts || [];
    if (alts.length) {
      addPopupSectionLabel("ALTERNATE RECIPE");
      for (const alt of alts) {
        addPopupOption(alt.recipe_name, false, async () => {
          if (isRoot) {
            // loadRecipeIntoForm already refreshes (with a new recipe id,
            // so the tree cache below invalidates on its own) - an extra
            // call here would just re-fetch the same thing a second time.
            await loadRecipeIntoForm(alt.recipe_id, alt.recipe_name);
          } else {
            await CraftMapApi.call("set_alt_pref", ingredientName, alt.recipe_id);
            await refreshBreakdown({ forceFull: true });
          }
        });
      }
    }

    const stations = node.stations || [];
    let modesAvailable = 0;
    for (const st of stations) {
      if (st[1]) modesAvailable++;
      if (st[2]) modesAvailable++;
    }
    if (modesAvailable > 1) {
      if (alts.length) {
        const sep = document.createElement("div");
        sep.className = "step-separator";
        stepPopup.appendChild(sep);
      }
      addPopupSectionLabel("STATION & MODE");
      const curStation = node.station;
      const curMode = node.craft_mode || "auto";
      for (const [stName, stAuto, stManual] of stations) {
        if (stAuto) {
          addPopupOption(
            `${stName} · Auto  (${formatDuration(stAuto)}/craft)`,
            stName === curStation && curMode === "auto",
            async () => {
              await CraftMapApi.call("set_station_pref", ingredientName, stName, "auto");
              await refreshBreakdown({ forceFull: true });
            }
          );
        }
        if (stManual) {
          addPopupOption(
            `${stName} · Manual  (${formatDuration(stManual)}/craft)`,
            stName === curStation && curMode === "manual",
            async () => {
              await CraftMapApi.call("set_station_pref", ingredientName, stName, "manual");
              await refreshBreakdown({ forceFull: true });
            }
          );
        }
      }
    }

    if (!stepPopup.children.length) return;

    stepPopup.classList.remove("hidden");
    const rect = anchorEl.getBoundingClientRect();
    const popRect = stepPopup.getBoundingClientRect();
    let x = rect.left;
    let y = rect.bottom;
    const w = Math.max(popRect.width, 180);
    if (x + w > window.innerWidth) x = window.innerWidth - w;
    if (y + popRect.height > window.innerHeight) y = Math.max(0, rect.top - popRect.height);
    stepPopup.style.left = `${Math.max(0, x)}px`;
    stepPopup.style.top = `${y}px`;

    setTimeout(() => {
      document.addEventListener("mousedown", onStepPopupOutsideClick, true);
      document.addEventListener("keydown", onStepPopupEscape, true);
    }, 0);
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
      key: "recipe_root",
      onToggleCheck: async () => {
        await ensureFullyResolved(node, []);
        const keys = collectPathKeysJs(node, []);
        await CraftMapApi.call("set_checked_many", recipeId, keys, !rootIsDone);
        await refreshBreakdown();
      },
      onOpenStep: rootHasOptions
        ? (e) => openStepPopup(e.currentTarget, node, outputName, true)
        : null,
      onFirstExpand: async (el) => {
        for (const child of node.children) {
          // pathParts must be [node.name] here, not [] - collect_path_keys
          // (the persistence side, run when the root's own checkbox
          // cascades) threads path_parts + [node.name] into each child, so
          // a child's real stored path_key is "<rootName>|<childName>".
          // Rendering with [] here would compute just "<childName>" and
          // never match what got persisted, permanently showing every
          // child as unchecked after a root-checkbox cascade - a real bug
          // in the original tkinter app (overlay.py's
          // _refresh_recipe_breakdown has this same mismatch) that's worth
          // fixing here rather than faithfully reproducing.
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
      key: "recipe_root",
      onToggleCheck: async () => {
        await ensureFullyResolved(node, []);
        const keys = collectPathKeysJs(node, []);
        await CraftMapApi.call("set_checked_many", recipeId, keys, !rootIsDone);
        await refreshBreakdown();
      },
      onOpenStep: rootHasOptions
        ? (e) => openStepPopup(e.currentTarget, node, outputName, true)
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
            ? (e) => openStepPopup(e.currentTarget, info, resName, false)
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
    const itemName = viewId !== null ? await CraftMapApi.call("get_recipe_output_name", viewId) : "";
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
      labelEl.textContent = "Select a recipe above to see where it's used.";
      row.appendChild(labelEl);
      wrapper.appendChild(row);
      tree.appendChild(wrapper);
      return;
    }
    const rows = await CraftMapApi.call("get_recipes_using_ingredient", itemName);
    const recipeName_ = await CraftMapApi.call("get_recipe_name", viewId);

    const { wrapper, childrenEl } = makeBdNode({
      tagClass: "root",
      label: `Recipes using  "${itemName}"`,
      hasChildren: true,
      key: "recipe_root",
    });
    // Clicking the header (not a specific result) loads this item into the
    // edit form without leaving Used-In mode - matches usedin_header in
    // overlay.py's _on_breakdown_click.
    wrapper.querySelector(".bd-label").addEventListener("click", async () => {
      if (viewId !== null && recipeName_) {
        await loadRecipeIntoForm(viewId, recipeName_);
      }
    });
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

  // ---- edit form: dynamic rows ----
  function makeRemoveButton(onRemove) {
    const btn = document.createElement("button");
    btn.className = "row-remove-btn";
    btn.textContent = "×";
    btn.addEventListener("click", onRemove);
    return btn;
  }

  function addStationRow(station = "", auto = "", manual = "") {
    const rowEl = document.createElement("div");
    rowEl.className = "station-row";
    const stationInput = document.createElement("input");
    stationInput.type = "text";
    stationInput.value = station;
    const autoInput = document.createElement("input");
    autoInput.type = "text";
    autoInput.value = auto;
    autoInput.className = "narrow-input";
    const manualInput = document.createElement("input");
    manualInput.type = "text";
    manualInput.value = manual;
    manualInput.className = "narrow-input";
    rowEl.appendChild(stationInput);
    rowEl.appendChild(autoInput);
    rowEl.appendChild(manualInput);
    const row = { stationInput, autoInput, manualInput, rowEl };
    const removeBtn = makeRemoveButton(() => {
      if (stationRows.length <= 1) return;
      stationRows = stationRows.filter((r) => r !== row);
      rowEl.remove();
    });
    rowEl.appendChild(removeBtn);
    stationRowsEl.appendChild(rowEl);
    new LiveDropdown(stationInput, { getValues: () => CraftMapApi.call("get_all_stations") });
    stationRows.push(row);
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
    const qtyInput = document.createElement("input");
    qtyInput.type = "text";
    qtyInput.value = String(qty);
    qtyInput.className = "narrow-input";
    rowEl.appendChild(nameInput);
    rowEl.appendChild(qtyInput);
    const row = { nameInput, qtyInput, rowEl };
    const removeBtn = makeRemoveButton(() => {
      if (outputRows.length <= 1) return;
      outputRows = outputRows.filter((r) => r !== row);
      rowEl.remove();
    });
    rowEl.appendChild(removeBtn);
    outputRowsEl.appendChild(rowEl);
    new LiveDropdown(nameInput, { getValues: () => CraftMapApi.call("get_all_output_names") });
    outputRows.push(row);
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
    const qtyInput = document.createElement("input");
    qtyInput.type = "text";
    qtyInput.value = String(qty);
    qtyInput.className = "narrow-input";
    rowEl.appendChild(nameInput);
    rowEl.appendChild(qtyInput);
    const row = { nameInput, qtyInput, rowEl };
    const removeBtn = makeRemoveButton(() => {
      ingredientRows = ingredientRows.filter((r) => r !== row);
      rowEl.remove();
    });
    rowEl.appendChild(removeBtn);
    ingredientRowsEl.appendChild(rowEl);
    new LiveDropdown(nameInput, {
      getValues: () => CraftMapApi.call("get_all_ingredient_options"),
    });
    ingredientRows.push(row);
    ingredientRowsEl.scrollTop = ingredientRowsEl.scrollHeight;
  }

  function clearIngredientRows() {
    for (const row of ingredientRows) row.rowEl.remove();
    ingredientRows = [];
  }

  // ---- form load/clear/save/delete ----
  async function loadRecipeIntoForm(recipeId, rname) {
    if (recipeId !== viewingRecipeId) {
      // A genuinely different recipe's path_keys don't mean anything to
      // this tree - only reset expand state when the *subject* changes,
      // not on every refresh of the recipe already being viewed (that's
      // the whole point of tracking it at all).
      recipeRootOpen = true;
      openNodeKeys = new Set();
    }
    viewingRecipeId = recipeId;
    recipeCombo.value = rname;
    recipeName.value = rname;

    clearStationRows();
    const stations = await CraftMapApi.call("get_recipe_stations", recipeId);
    for (const s of stations) {
      addStationRow(s.station, s.auto !== null && s.auto !== undefined ? fmtNum(s.auto) : "", s.manual !== null && s.manual !== undefined ? fmtNum(s.manual) : "");
    }
    if (!stationRows.length) addStationRow();

    clearOutputRows();
    const outputs = await CraftMapApi.call("get_recipe_outputs", recipeId);
    for (const o of outputs) addOutputRow(o.name, o.qty);
    if (!outputRows.length) addOutputRow();

    clearIngredientRows();
    const ingredients = await CraftMapApi.call("get_recipe_ingredients", recipeId);
    for (const i of ingredients) addIngredientRow(i.name, i.qty);

    await refreshBreakdown();
  }

  function clearRecipeForm() {
    viewingRecipeId = null;
    recipeRootOpen = true;
    openNodeKeys = new Set();
    recipeCombo.value = "";
    recipeName.value = "";
    clearStationRows();
    addStationRow();
    clearOutputRows();
    addOutputRow();
    clearIngredientRows();
    tree.innerHTML = "";
  }

  async function onRecipeComboCommit() {
    const name = recipeCombo.value.trim();
    const recipeId = await CraftMapApi.call("get_recipe_by_name", name);
    if (recipeId === null) return;
    usedinRecipeId = recipeId;
    usedinNavigatedAway = false;
    await loadRecipeIntoForm(recipeId, name);
  }

  async function saveRecipeAction() {
    const name = recipeName.value.trim();
    if (!name) {
      CraftMapApi._showError("Recipe name is required.");
      return;
    }
    const ingredients = [];
    for (const row of ingredientRows) {
      const ingName = row.nameInput.value.trim();
      if (!ingName) continue;
      const qty = parseFloat(row.qtyInput.value.trim());
      if (!isFinite(qty)) {
        CraftMapApi._showError(`Invalid quantity for '${ingName}'.`);
        return;
      }
      ingredients.push({ name: ingName, qty });
    }
    if (!ingredients.length) {
      CraftMapApi._showError("Add at least one ingredient.");
      return;
    }
    const outputs = [];
    for (const row of outputRows) {
      const outName = row.nameInput.value.trim();
      if (!outName) continue;
      const qty = parseFloat(row.qtyInput.value.trim());
      if (!isFinite(qty) || qty <= 0) {
        CraftMapApi._showError(`Invalid quantity for output '${outName}'.`);
        return;
      }
      outputs.push({ name: outName, qty });
    }
    if (!outputs.length) {
      CraftMapApi._showError("Add at least one output.");
      return;
    }
    const existingId = await CraftMapApi.call("get_recipe_by_name", name);
    if (existingId !== null && existingId !== viewingRecipeId) {
      CraftMapApi._showError(`A recipe named '${name}' already exists.`);
      return;
    }
    const stations = [];
    for (const row of stationRows) {
      const stName = row.stationInput.value.trim();
      if (!stName) continue;
      const autoStr = row.autoInput.value.trim();
      const manualStr = row.manualInput.value.trim();
      const auto = autoStr ? parseFloat(autoStr) : null;
      const manual = manualStr ? parseFloat(manualStr) : null;
      if ((autoStr && !isFinite(auto)) || (manualStr && !isFinite(manual))) {
        CraftMapApi._showError("Craft time must be a number of seconds.");
        return;
      }
      stations.push({ station: stName, auto, manual });
    }
    if (!stations.length) {
      CraftMapApi._showError("Add at least one station.");
      return;
    }

    let rid;
    try {
      rid = await CraftMapApi.call(
        "save_recipe",
        viewingRecipeId,
        name,
        outputs,
        ingredients,
        stations
      );
    } catch (e) {
      return;
    }
    viewingRecipeId = rid;
    recipeCombo.value = name;
    // forceFull: saving can change this recipe's own ingredients/outputs/
    // stations while its id stays the same, so the id-based cache check
    // alone wouldn't notice the tree needs re-resolving.
    await refreshBreakdown({ forceFull: true });
  }

  async function deleteRecipeAction() {
    if (viewingRecipeId === null) {
      CraftMapApi._showError("Select a recipe first.");
      return;
    }
    if (!confirm("Delete this recipe?")) return;
    await CraftMapApi.call("delete_recipe", viewingRecipeId);
    clearRecipeForm();
  }

  // ---- init ----
  async function init() {
    new LiveDropdown(recipeCombo, {
      getValues: async () => {
        const recipes = await CraftMapApi.call("get_all_recipes");
        return recipes.map((r) => r.name);
      },
      onSelect: onRecipeComboCommit,
    });
    recipeCombo.addEventListener("keydown", (e) => {
      if (e.key === "Enter") onRecipeComboCommit();
    });

    recipeNewBtn.addEventListener("click", clearRecipeForm);
    recipeQty.addEventListener("keydown", (e) => {
      if (e.key === "Enter") refreshBreakdown();
    });
    recipeQty.addEventListener("blur", refreshBreakdown);

    modeBreakdown.addEventListener("click", () => setRecipeMode("breakdown"));
    modeTotals.addEventListener("click", () => setRecipeMode("totals"));
    modeUsedin.addEventListener("click", () => setRecipeMode("usedin"));

    document.getElementById("btn-add-station").addEventListener("click", () => addStationRow());
    document.getElementById("btn-add-output").addEventListener("click", () => addOutputRow());
    document
      .getElementById("btn-add-ingredient")
      .addEventListener("click", () => addIngredientRow());
    document.getElementById("btn-recipe-save").addEventListener("click", saveRecipeAction);
    document.getElementById("btn-recipe-clear").addEventListener("click", clearRecipeForm);
    document.getElementById("btn-recipe-delete").addEventListener("click", deleteRecipeAction);

    addStationRow();
    addOutputRow();
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
