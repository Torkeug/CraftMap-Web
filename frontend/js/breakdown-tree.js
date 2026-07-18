/* Shared recipe-breakdown-tree renderer, used by both the recipe panel
 * (frontend/js/recipe-panel.js) and the Craft Queue panel (frontend/js/
 * queue-panel.js) - factored out per the migration plan since both need
 * the identical checkbox-cascade tree with alt-recipe/station step
 * popover, just fed different root data (one recipe vs. a selected queue
 * job / aggregated queue totals).
 *
 * Pure, stateless helpers (formatting, node math, path-key collection)
 * are exposed directly on `BreakdownTree`. `BreakdownTree.createRenderer`
 * returns a renderer bound to one tree container + one step-popup
 * element, owning the per-instance state that must NOT be shared between
 * the recipe panel's tree and the queue panel's tree (each node's
 * expand/collapse survival across a rebuild, and the checkbox
 * busy-guard) - see makeBdNode's own comments for why both exist.
 */
const BreakdownTree = (function () {
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

  function formatSourcesSuffix(sources) {
    // Only worth a note once an item is demanded from more than one
    // parent - with a single source it's redundant with the row's own
    // qty (see resolver.aggregate_item_occurrences's `sources` field).
    if (!sources || sources.length < 2) return "";
    const parts = sources.map((s) => `${fmtNum(s.qty)} via ${s.parent_name}`);
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
  // round-tripped through an Api method that walks the whole tree, since
  // sending the *entire* resolved tree back to Python as a call argument
  // just to walk it turned out to cost 200ms+ on a ~100-node tree
  // (payload marshaling size, not call-count, is what's expensive over
  // this pywebview/pythonnet bridge). Simple and low-risk enough to
  // duplicate here; resolve_recipe_tree itself stays server-side.
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
    // alts check comes before the is_recipe gate: a node forced to "Raw
    // Material" via set_alt_pref has is_recipe false but still carries
    // alts (the real recipes it could switch back to) - see resolver.py's
    // _node_has_step_options for the matching backend logic.
    if (node.alts && node.alts.length) return true;
    if (!node.is_recipe) return false;
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
      // alts carries a real recipe here whenever this raw leaf is a
      // curated raw material currently defaulting to raw (see resolver.
      // py's db.get_raw_material_names) - preserved so insertRaw can still
      // offer switching it to crafted, same as a genuinely raw node (no
      // recipe at all, alts always []) just never gets the option.
      if (!totals[node.name]) totals[node.name] = { qty: 0.0, alts: node.alts || [] };
      totals[node.name].qty += node.qty;
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
            // qty-by-name needed via THIS crafted item specifically, summed
            // across every occurrence of it in the tree - unlike totals[name]
            // itself (which mixes in demand from every OTHER parent too),
            // this is what a raw row nested under this crafted item's own
            // row should actually display.
            raw_qty: {},
            station: child.station,
            auto_craft_seconds: child.auto_craft_seconds,
            manual_craft_seconds: child.manual_craft_seconds,
            craft_mode: child.craft_mode || "auto",
            byproducts: child.byproducts || [],
          };
        }
        totals[child.name].qty += child.qty;
        for (const c of child.children) {
          totals[child.name].raw_qty[c.name] = (totals[child.name].raw_qty[c.name] || 0) + c.qty;
        }
      }
    }
    return totals;
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

  // ---- per-instance renderer (DOM construction + expand/busy state) ----
  function createRenderer({ treeEl, stepPopupEl, persistKey }) {
    // Every node's expand/collapse state survives a tree rebuild
    // (checkbox clicks, quantity changes, alt/station picks all rebuild
    // the whole tree) - tracked by path_key since node identity itself
    // doesn't survive a rebuild. overlay.py's tkinter version only kept
    // the root's state across a rebuild and re-collapsed everything else
    // every time; that read as "the tree collapsed on me" here since a
    // click anywhere deep in a large expanded tree wiped out all that
    // manual drilling-down.
    let rootOpen = true;
    let openNodeKeys = new Set();
    // A checkbox click's own visual feedback only lands after the full
    // cascade + refresh round-trip (a few hundred ms of real IPC
    // latency) - with nothing shown in the meantime, an impatient second
    // click before that lands fires the same toggle again, flipping it
    // right back off (or on) and netting no visible change at all, which
    // looked exactly like "cascade doesn't work." This guard makes every
    // checkbox a no-op while one toggle for this tree is still in flight.
    let busy = false;

    // In-memory-only (see above) means this resets on every app restart -
    // `persistKey`, when given, mirrors js/deposits.js's own collapsed_
    // nodes persistence (Api.get_tree_expand_state/set_tree_expand_state,
    // config.json-backed) so a tree that was left mostly expanded reopens
    // the same way next launch instead of starting fully collapsed again.
    // `ready` resolves once that initial load lands - callers with a
    // persistKey should await it before their first render, same as
    // screens.js's window.__viewModeReady exists so drag-resize's launch-
    // time min-size measurement waits for the real saved view first.
    const ready = persistKey
      ? CraftMapApi.call("get_tree_expand_state", persistKey).then((state) => {
          rootOpen = state.root_open !== false;
          openNodeKeys = new Set(state.open_keys || []);
        })
      : Promise.resolve();

    function persistExpandState() {
      if (!persistKey) return;
      CraftMapApi.call("set_tree_expand_state", persistKey, {
        root_open: rootOpen,
        open_keys: [...openNodeKeys],
      });
    }

    function resetExpandState() {
      rootOpen = true;
      openNodeKeys = new Set();
    }

    function makeCheckboxIcon(checked) {
      // Tri-state: true/false as before, plus "indeterminate" for a
      // merged Totals-mode item where some but not all of its underlying
      // occurrences are checked (see resolver.aggregate_item_occurrences's
      // any_checked/fully_checked).
      const span = document.createElement("span");
      const state = checked === "indeterminate" ? "indeterminate" : checked ? "checked" : "unchecked";
      span.className = "cb-icon " + state;
      return span;
    }

    function makeBdNode({
      tagClass,
      label,
      checked,
      hasChildren,
      onToggleCheck,
      onOpenStep,
      key,
      isRoot,
      onFirstExpand,
    }) {
      const wrapper = document.createElement("div");
      wrapper.className = "bd-node";
      if (key) wrapper.dataset.key = key;
      const startsOpen = isRoot ? rootOpen : key && openNodeKeys.has(key);
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
          // Deposit-location lookups (and, for a truncated node, the
          // subtree fetch itself) are a real IPC round-trip here (unlike
          // the tkinter app, where the same lookup was an in-process
          // SQLite call) - fetching them eagerly for every node in a
          // large tree meant dozens of sequential round-trips per
          // render. Deferring to first-expand means a render only ever
          // pays for the nodes actually visible.
          if (wasCollapsed && !expandLoaded) {
            expandLoaded = true;
            await onFirstExpand(childrenEl);
          }
          wrapper.classList.toggle("collapsed");
          const nowOpen = !wrapper.classList.contains("collapsed");
          if (isRoot) {
            rootOpen = nowOpen;
          } else if (key) {
            if (nowOpen) openNodeKeys.add(key);
            else openNodeKeys.delete(key);
          }
          persistExpandState();
        });
      }
      row.appendChild(disc);

      if (checked !== undefined) {
        const cb = makeCheckboxIcon(checked);
        cb.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (busy) return;
          busy = true;
          // Instant feedback before the round-trip lands, so the click
          // doesn't feel like it did nothing (see `busy` above). Tri-state
          // convention: unchecked OR indeterminate -> fully checks;
          // fully-checked -> fully unchecks - indeterminate is a passive,
          // data-driven display state only, never itself a click target
          // to preserve.
          const wasChecked = cb.classList.contains("checked");
          cb.classList.remove("checked", "unchecked", "indeterminate");
          cb.classList.add(wasChecked ? "unchecked" : "checked");
          cb.classList.add("pending");
          try {
            await onToggleCheck();
          } finally {
            busy = false;
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
      // expand-click would - but nothing here waited for a click, so
      // drive it directly and hand the caller a promise to await instead
      // of firing it from inside the disclosure's click handler.
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
        const text = `${indent}\u{1F4CD} ${parts.join(" / ")}`;
        childrenEl.appendChild(makeLocationRow(text));
      }
    }

    // ---- step popup (alt-recipe / station+mode picker) ----
    function closeStepPopup() {
      stepPopupEl.classList.add("hidden");
      stepPopupEl.innerHTML = "";
      document.removeEventListener("mousedown", onStepPopupOutsideClick, true);
      document.removeEventListener("keydown", onStepPopupEscape, true);
    }

    function onStepPopupOutsideClick(e) {
      if (!stepPopupEl.contains(e.target)) closeStepPopup();
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
      stepPopupEl.appendChild(row);
    }

    function addPopupSectionLabel(text) {
      const lbl = document.createElement("div");
      lbl.className = "step-section-label";
      lbl.textContent = text;
      stepPopupEl.appendChild(lbl);
    }

    // onAlt(alt, isRoot) / onStation(stationName, mode, isRoot) are the
    // caller's business logic for what an alt-recipe/station pick means
    // (recipe panel loads a different recipe into the form for a root
    // pick and sets a plain alt_pref otherwise; the queue panel updates
    // the queued job's station instead of a generic station_pref for its
    // root). Both are expected to trigger their own refresh afterward.
    function openStepPopup(anchorEl, node, isRoot, onAlt, onStation) {
      stepPopupEl.innerHTML = "";
      const alts = isRoot ? [] : node.alts || [];
      if (alts.length) {
        addPopupSectionLabel("ALTERNATE RECIPE");
        for (const alt of alts) {
          addPopupOption(alt.recipe_name, false, () => onAlt(alt));
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
          stepPopupEl.appendChild(sep);
        }
        addPopupSectionLabel("STATION & MODE");
        const curStation = node.station;
        const curMode = node.craft_mode || "auto";
        for (const [stName, stAuto, stManual] of stations) {
          if (stAuto) {
            addPopupOption(
              `${stName} · Auto  (${formatDuration(stAuto)}/craft)`,
              stName === curStation && curMode === "auto",
              () => onStation(stName, "auto")
            );
          }
          if (stManual) {
            addPopupOption(
              `${stName} · Manual  (${formatDuration(stManual)}/craft)`,
              stName === curStation && curMode === "manual",
              () => onStation(stName, "manual")
            );
          }
        }
      }

      if (!stepPopupEl.children.length) return;

      stepPopupEl.classList.remove("hidden");
      const rect = anchorEl.getBoundingClientRect();
      const popRect = stepPopupEl.getBoundingClientRect();
      let x = rect.left;
      let y = rect.bottom;
      const w = Math.max(popRect.width, 180);
      if (x + w > window.innerWidth) x = window.innerWidth - w;
      if (y + popRect.height > window.innerHeight) y = Math.max(0, rect.top - popRect.height);
      stepPopupEl.style.left = `${Math.max(0, x)}px`;
      stepPopupEl.style.top = `${y}px`;

      setTimeout(() => {
        document.addEventListener("mousedown", onStepPopupOutsideClick, true);
        document.addEventListener("keydown", onStepPopupEscape, true);
      }, 0);
    }

    return {
      makeBdNode,
      makeLocationRow,
      appendDepositLocations,
      openStepPopup,
      closeStepPopup,
      resetExpandState,
      ready,
    };
  }

  return {
    fmtNum,
    formatDuration,
    formatCraftMetaSuffix,
    formatByproductsSuffix,
    formatSourcesSuffix,
    nodeCrafts,
    nodeActiveSeconds,
    nodeOwnTime,
    nodePathKey,
    collectPathKeysJs,
    ensureFullyResolved,
    subtreeRemainingSeconds,
    nodeHasStepOptions,
    collectTotals,
    collectBasicCrafted,
    buildIngredientLabel,
    createRenderer,
  };
})();
