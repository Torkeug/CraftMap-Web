/* Craft Queue window: job list (top pane) + selected job's breakdown, or
 * an aggregated Totals view, in the bottom pane. Direct port of
 * craftmap/overlay.py's CraftQueuePanel (_refresh_job_list, _render_
 * breakdown, _render_totals, _on_bd_click, _add_job, etc). Reuses
 * frontend/js/breakdown-tree.js's shared renderer/step-popup exactly like
 * frontend/js/recipe-panel.js does.
 *
 * Differs from the tkinter original in one deliberate way: Totals-mode
 * aggregation across every queued job runs server-side now
 * (Api.get_queue_totals_view, see backend/api.py) instead of resolving N
 * full recipe trees here and flattening them in JS - shipping several full
 * (non-depth-limited) trees across the pywebview bridge just to throw away
 * everything but a handful of aggregate numbers would be exactly the
 * payload-size cost the recipe panel's depth-limited fetching was built to
 * avoid (see backend/api.py's module docstring).
 */
(function () {
  const {
    fmtNum,
    formatCraftMetaSuffix,
    formatByproductsSuffix,
    formatSourcesSuffix,
    nodeActiveSeconds,
    nodePathKey,
    collectPathKeysJs,
    ensureFullyResolved,
    subtreeRemainingSeconds,
    nodeHasStepOptions,
  } = BreakdownTree;

  // ---- DOM refs ----
  const tree = document.getElementById("queue-breakdown-tree");
  const jobListEl = document.getElementById("queue-job-list");
  const modeQueueBtn = document.getElementById("queue-mode-queue");
  const modeTotalsBtn = document.getElementById("queue-mode-totals");
  const addRecipeInput = document.getElementById("queue-add-recipe");
  const addQtyInput = document.getElementById("queue-add-qty");
  const addBtn = document.getElementById("queue-add-btn");
  const clearDoneBtn = document.getElementById("queue-clear-done-btn");
  const pinBtn = document.getElementById("pin-btn");
  const splitEl = document.getElementById("queue-split");
  const stepPopupEl = document.getElementById("step-popup");

  const renderer = BreakdownTree.createRenderer({
    treeEl: tree,
    stepPopupEl,
    persistKey: "queue_breakdown",
  });
  const { makeBdNode, appendDepositLocations, openStepPopup } = renderer;

  // ---- state ----
  let mode = "queue"; // 'queue' | 'totals'
  let selectedJob = null; // {queue_id, recipe_id, recipe_name, output_name, qty, station, station_mode}
  let cachedTree = null;
  let cachedOutputName = "";
  let cachedForQueueId = null;

  // ---- job list ----
  function makeJobCheckboxIcon(checked) {
    const span = document.createElement("span");
    span.className = "cb-icon " + (checked ? "checked" : "unchecked");
    return span;
  }

  async function refreshJobList() {
    const jobs = await CraftMapApi.call("get_craft_queue");
    jobListEl.innerHTML = "";
    if (!jobs.length) {
      const empty = document.createElement("div");
      empty.className = "queue-job-empty";
      empty.textContent = "No jobs — add one below.";
      jobListEl.appendChild(empty);
      return jobs;
    }
    for (const job of jobs) {
      const isSel = selectedJob !== null && selectedJob.queue_id === job.queue_id;
      const row = document.createElement("div");
      row.className = "queue-job-row" + (isSel ? " selected" : "");

      const combineCb = makeJobCheckboxIcon(job.combine);
      combineCb.addEventListener("click", async (e) => {
        e.stopPropagation();
        await CraftMapApi.call("update_queue_combine", job.queue_id, !job.combine);
        await refreshJobList();
        if (mode === "totals") await refreshBreakdown();
      });
      row.appendChild(combineCb);

      const label = document.createElement("span");
      label.className = "queue-job-label";
      label.textContent = job.output_name;
      row.appendChild(label);

      const qtyInput = document.createElement("input");
      qtyInput.type = "text";
      qtyInput.className = "queue-job-qty";
      qtyInput.value = fmtNum(job.qty);
      qtyInput.addEventListener("click", (e) => e.stopPropagation());
      const commitQty = async () => {
        const qty = parseFloat(qtyInput.value);
        if (!isFinite(qty) || qty <= 0) return;
        await CraftMapApi.call("update_queue_qty", job.queue_id, qty);
        if (selectedJob && selectedJob.queue_id === job.queue_id) {
          selectedJob.qty = qty;
          await refreshBreakdown();
        }
      };
      qtyInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") commitQty();
      });
      qtyInput.addEventListener("blur", commitQty);
      row.appendChild(qtyInput);

      const rmBtn = document.createElement("button");
      rmBtn.className = "queue-job-remove";
      rmBtn.textContent = "×";
      rmBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await CraftMapApi.call("remove_from_queue", job.queue_id);
        if (selectedJob && selectedJob.queue_id === job.queue_id) selectedJob = null;
        await refreshJobList();
        await refreshBreakdown();
      });
      row.appendChild(rmBtn);

      row.addEventListener("click", () => selectJob(job));
      jobListEl.appendChild(row);
    }
    return jobs;
  }

  function selectJob(job) {
    if (!selectedJob || selectedJob.queue_id !== job.queue_id) {
      renderer.resetExpandState();
    }
    selectedJob = {
      queue_id: job.queue_id,
      recipe_id: job.recipe_id,
      recipe_name: job.recipe_name,
      output_name: job.output_name,
      qty: job.qty,
      station: job.station,
      station_mode: job.station_mode,
    };
    refreshJobList();
    if (mode === "queue") refreshBreakdown();
  }

  // ---- add-job row ----
  // No station picker here anymore - once a job exists, its root breakdown
  // node's own step popup (see renderQueueMode's onOpenStep below) already
  // lets you pick the station/mode by clicking the recipe, which makes a
  // separate up-front station field at add-time redundant.
  async function addJob() {
    const name = addRecipeInput.value.trim();
    if (!name) return;
    const recipeId = await CraftMapApi.call("get_recipe_by_name", name);
    if (recipeId === null) return;
    let qty = parseFloat(addQtyInput.value);
    if (!isFinite(qty) || qty <= 0) qty = 1.0;
    await CraftMapApi.call("add_to_queue", recipeId, qty, null);
    addRecipeInput.value = "";
    addQtyInput.value = "1";
    await refreshJobList();
    if (mode === "totals") await refreshBreakdown();
  }

  async function clearAllDone() {
    await CraftMapApi.call("clear_all_queue_checked");
    await refreshBreakdown();
  }

  // ---- shared node insertion (see module docstring - a small, low-risk
  // duplicate of recipe-panel.js's insertBreakdownNode rather than a
  // shared export, since the two differ in which Api persistence call
  // they make and the queue's root step popup deliberately excludes
  // alt-recipe switches - same rationale breakdown-tree.js already gives
  // for duplicating collectPathKeysJs instead of round-tripping through
  // Python) ----
  async function insertQueueNode(parentEl, node, queueId, pathParts, checked) {
    const pathKey = nodePathKey(node, pathParts);
    const isDone = checked.has(pathKey);
    const qtyStr = fmtNum(node.qty);
    let label = `${qtyStr}×  ${node.name}`;
    const usedRecipe = node.recipe_name || node.name;
    if (usedRecipe && usedRecipe !== node.name) label += `  [${usedRecipe}]`;
    const hasOptions = nodeHasStepOptions(node);
    if (hasOptions) label += "  ▾";
    const [activeSeconds, activeMode] = nodeActiveSeconds(node);
    const remaining = subtreeRemainingSeconds(node, pathParts, checked);
    label += formatCraftMetaSuffix(node.station, activeSeconds, activeMode, remaining);
    label += formatByproductsSuffix(node.byproducts);

    const hasChildren = node.children.length > 0;
    const isRawLeaf = !node.is_recipe && !hasChildren && !node.truncated;

    const { wrapper, childrenEl, expandPromise } = makeBdNode({
      tagClass: isDone ? "done" : "ingredient",
      label,
      checked: isDone,
      hasChildren: hasChildren || isRawLeaf || node.truncated === true,
      key: pathKey,
      onToggleCheck: async () => {
        await ensureFullyResolved(node, pathParts);
        const keys = collectPathKeysJs(node, pathParts);
        await CraftMapApi.call("set_queue_checked_many", queueId, keys, !isDone);
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
              async (stName, m) => {
                await CraftMapApi.call("set_station_pref", node.name, stName, m);
                await refreshBreakdown({ forceFull: true });
              }
            )
        : null,
      onFirstExpand: node.truncated
        ? async (el) => {
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
              await insertQueueNode(el, child, queueId, [...pathParts, node.name], checked);
            }
          }
        : isRawLeaf
        ? (el) => appendDepositLocations(el, node.name, "    ")
        : hasChildren
        ? async (el) => {
            for (const child of node.children) {
              await insertQueueNode(el, child, queueId, [...pathParts, node.name], checked);
            }
          }
        : undefined,
    });
    parentEl.appendChild(wrapper);
    await expandPromise;
  }

  // A queued job's root step options deliberately exclude alt-recipes (a
  // job is tied to the specific recipe_id it was queued with - see
  // openStepPopup's isRoot handling, which already forces alts to [] for
  // any root call) - so unlike nodeHasStepOptions, only station/mode
  // combinations decide whether the root shows a popover at all.
  function queueRootHasStepOptions(node) {
    let modesAvailable = 0;
    for (const [, stAuto, stManual] of node.stations || []) {
      if (stAuto) modesAvailable++;
      if (stManual) modesAvailable++;
    }
    return modesAvailable > 1;
  }

  async function renderQueueMode(forceFull) {
    if (!selectedJob) {
      const { wrapper } = makeBdNode({
        tagClass: "section",
        label: "← Select a job above to see its breakdown.",
        hasChildren: false,
      });
      tree.appendChild(wrapper);
      return;
    }
    const cacheValid =
      !forceFull && cachedTree !== null && cachedForQueueId === selectedJob.queue_id;
    let checked;
    if (cacheValid) {
      const list = await CraftMapApi.call("get_queue_checked_paths", selectedJob.queue_id);
      checked = new Set(list);
    } else {
      const view = await CraftMapApi.call("get_queue_breakdown_view", selectedJob.queue_id);
      if (!view.output_name) {
        cachedTree = null;
        return;
      }
      cachedTree = view.tree;
      cachedOutputName = view.output_name;
      cachedForQueueId = selectedJob.queue_id;
      checked = new Set(view.checked);
    }
    const node = cachedTree;
    const outputName = cachedOutputName;
    const qty = selectedJob.qty;
    const oqty = node.output_qty || 1.0;
    const crafts = Math.ceil(qty / oqty);
    let rootLabel = `◆  ${outputName}  ×${fmtNum(qty)}`;
    if (crafts > 1 || oqty > 1) rootLabel += `  (${fmtNum(crafts)} crafts)`;
    const rootHasOptions = queueRootHasStepOptions(node);
    if (rootHasOptions) rootLabel += "  ▾";
    const [activeSeconds, activeMode] = nodeActiveSeconds(node);
    const rootRemaining = subtreeRemainingSeconds(node, [], checked);
    rootLabel += formatCraftMetaSuffix(node.station, activeSeconds, activeMode, rootRemaining);
    rootLabel += formatByproductsSuffix(node.byproducts);
    const rootPathKey = nodePathKey(node, []);
    const rootIsDone = checked.has(rootPathKey);
    const queueId = selectedJob.queue_id;

    const { wrapper, expandPromise } = makeBdNode({
      tagClass: "root",
      label: rootLabel,
      checked: rootIsDone,
      hasChildren: node.children.length > 0,
      isRoot: true,
      onToggleCheck: async () => {
        await ensureFullyResolved(node, []);
        const keys = collectPathKeysJs(node, []);
        await CraftMapApi.call("set_queue_checked_many", queueId, keys, !rootIsDone);
        await refreshBreakdown();
      },
      onOpenStep: rootHasOptions
        ? (e) =>
            openStepPopup(
              e.currentTarget,
              node,
              true,
              null,
              async (stName, m) => {
                await CraftMapApi.call("update_queue_station", queueId, stName, m);
                selectedJob.station = stName;
                selectedJob.station_mode = m;
                await refreshBreakdown({ forceFull: true });
              }
            )
        : null,
      onFirstExpand: async (el) => {
        for (const child of node.children) {
          // pathParts must be [node.name], not [] - matches recipe-panel.js's
          // renderBreakdownMode (see its comment): _collect_path_keys/
          // collectPathKeysJs prefix a root-checkbox cascade's descendant
          // keys with the root's own name, so the initial render has to use
          // the same prefix or a root-checked job would show every child
          // as unchecked.
          await insertQueueNode(el, child, queueId, [node.name], checked);
        }
      },
    });
    tree.appendChild(wrapper);
    await expandPromise;
  }

  // ---- mode: totals ----
  // Checked state now lives inside each aggregated `items` entry itself
  // (fully_checked/any_checked/occurrences - see resolver.aggregate_item_
  // occurrences), not in a separately-fetched Set keyed by synthetic path
  // keys - a merged row's checkbox cascades onto every real per-job
  // occurrence it represents via Api.set_totals_item_checked, so there's
  // no client-side path-key bookkeeping left to do here at all.
  function checkboxState(info) {
    return info.fully_checked ? true : info.any_checked ? "indeterminate" : false;
  }

  function craftedNameSort(a, b) {
    return a[0].toLowerCase().localeCompare(b[0].toLowerCase());
  }

  // Builds the actual merged BOM TREE (the approved "Option D" mockup),
  // not a flat list: each unique crafted item gets a full row exactly
  // once, with its own crafted_names nested directly beneath it (same as
  // raw_names becomes a deposit-location expando) - if the SAME item is
  // reached again via a different parent, that second occurrence renders
  // as a muted, non-expandable cross-reference row instead of a duplicate
  // subtree, clicking it jumps to and flashes the one real row.
  function insertTotalsSections(parentEl, scopeKey, items) {
    const craftedEntries = Object.entries(items).filter(([, info]) => info.is_recipe);
    const rawEntries = Object.entries(items)
      .filter(([, info]) => !info.is_recipe)
      .sort(craftedNameSort);

    if (craftedEntries.length) {
      const { wrapper: craftHdr, childrenEl: craftChildren } = makeBdNode({
        tagClass: "section",
        label: "── Crafted ──",
        hasChildren: true,
        key: `${scopeKey}|crafted_hdr`,
      });
      parentEl.appendChild(craftHdr);

      const rendered = new Set();

      function renderXref(container, resName, info, parentName) {
        const rowKey = `${scopeKey}|crafted|${resName}`;
        // `sources` only tracks UNCHECKED contributions (see resolver.
        // aggregate_item_occurrences) - crafted_names still lists this
        // parent-child edge even once fully checked off (it's a
        // structural, checked-state-independent field), so a missing
        // lookup here means "0 remaining from this parent," not "show
        // the item's whole total instead."
        const src = (info.sources || []).find((s) => s.parent_name === parentName);
        const fromHere = src ? src.qty : 0;

        // Scoped to just THIS parent's own occurrences - checking a
        // cross-reference row must only affect the slice attributable to
        // its own parent (e.g. "Metal Sheet via Cargo Hold"), not cascade
        // every occurrence of the item everywhere the way the item's own
        // main row does.
        const parentOccs = (info.occurrences || []).filter(
          (o) => o.parent_name === parentName
        );
        const parentCheckedCount = parentOccs.filter((o) => o.checked).length;
        const parentChecked =
          parentOccs.length > 0 && parentCheckedCount === parentOccs.length
            ? true
            : parentCheckedCount > 0
            ? "indeterminate"
            : false;

        const jumpToReal = () => {
          const target = tree.querySelector(`[data-key="${CSS.escape(rowKey)}"] > .bd-row`);
          if (!target) return;
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.remove("flash");
          void target.offsetWidth;
          target.classList.add("flash");
        };
        // A cross-reference only ever exists for an item that's "promoted"
        // (root-demand or shared across 2+ parents - see the Phase 1/2
        // comments below), which always has a real, findable home (its own
        // row under Crafted or under Shared Components) - so the jump link
        // is always meaningful here, never a dead-end. No directional
        // "see above" claim in the label either - which one renders first
        // depends on alphabetical position interacting with nesting depth,
        // so the real row can legitimately end up either above or below
        // this one; jumpToReal finds it either way.
        const { wrapper: xrefWrapper } = makeBdNode({
          tagClass: "xref",
          label: `${fmtNum(fromHere)}×  ${resName}  (view full entry)`,
          checked: parentChecked,
          hasChildren: false,
          onToggleCheck: async () => {
            await CraftMapApi.call(
              "set_totals_item_checked",
              parentOccs,
              parentChecked !== true
            );
            await refreshBreakdown();
          },
          onOpenStep: jumpToReal,
        });
        container.appendChild(xrefWrapper);
      }

      // Builds resName's own full row (assumes it isn't rendered yet -
      // callers check `rendered` themselves, see below) and returns its
      // childrenEl for the caller to expand into (kept separate from
      // expandCraftedChildren so Phase 1 below can give every promoted
      // item its row before ANY of them recurse into children - see the
      // phase comment for why that ordering matters).
      function makeCraftedRow(container, resName, info) {
        rendered.add(resName);
        const oq = info.output_qty || 1.0;
        const crafts = Math.ceil(info.qty / oq);
        const hasOptions = nodeHasStepOptions(info);
        let suffix = oq > 1 ? `  (${fmtNum(crafts)} crafts)` : "";
        if (hasOptions) suffix += "  ▾";
        const [activeSeconds, activeMode] = nodeActiveSeconds(info);
        const remaining = activeSeconds ? activeSeconds * crafts : 0.0;
        suffix += formatCraftMetaSuffix(info.station, activeSeconds, activeMode, remaining);
        suffix += formatByproductsSuffix(info.byproducts);
        suffix += formatSourcesSuffix(info.sources);

        const hasNestedChildren =
          (info.raw_names || []).length > 0 || (info.crafted_names || []).length > 0;

        const { wrapper: entryWrapper, childrenEl: entryChildren } = makeBdNode({
          tagClass: info.fully_checked ? "done" : "ingredient",
          label: `${fmtNum(info.qty)}×  ${resName}${suffix}`,
          checked: checkboxState(info),
          hasChildren: hasNestedChildren,
          key: `${scopeKey}|crafted|${resName}`,
          onToggleCheck: async () => {
            await CraftMapApi.call(
              "set_totals_item_checked",
              info.occurrences,
              !info.fully_checked
            );
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
                    // Global, ingredient-name-keyed preference - can change
                    // ANY job's tree shape without changing that job's own
                    // row, so the per-job resolved-tree cache can't detect
                    // it on its own (see Api._get_totals_job_specs).
                    await refreshBreakdown({ forceFull: true });
                  },
                  async (stName, m) => {
                    await CraftMapApi.call("set_station_pref", resName, stName, m);
                    await refreshBreakdown({ forceFull: true });
                  }
                )
            : null,
        });
        container.appendChild(entryWrapper);
        return entryChildren;
      }

      function expandCraftedChildren(entryChildren, resName, info) {
        for (const childName of [...(info.crafted_names || [])].sort()) {
          renderNested(entryChildren, childName, resName);
        }
        for (const rawName of info.raw_names || []) {
          // Look up the item's real aggregate entry (not just its bare
          // name) so a raw material nested here - same as one in the flat
          // Raw Materials section - can still carry alts if it's a
          // curated raw material currently overridden to a real recipe,
          // or a real recipe currently defaulting to raw (see resolver.
          // py's db.get_raw_material_names/RAW_MATERIAL_PREF). Previously
          // this was a bare label with zero picker support, which is why
          // an item reached only through a crafted parent's ingredient
          // list (rather than its own promoted Raw Materials row) had no
          // way to switch its recipe at all.
          const rawInfo = items[rawName];
          const rawHasOptions = rawInfo ? nodeHasStepOptions(rawInfo) : false;
          // Same "qty attributable to THIS parent" lookup as renderXref -
          // rawInfo.qty is the item's grand total across every parent, which
          // would overstate what's actually needed via this one crafted row.
          const rawSrc = rawInfo
            ? (rawInfo.sources || []).find((s) => s.parent_name === resName)
            : null;
          const rawQty = rawSrc ? rawSrc.qty : rawInfo ? rawInfo.qty : 0;
          const { wrapper: rawWrapper } = makeBdNode({
            tagClass: "location",
            label: `${fmtNum(rawQty)}×  ${rawName}${rawHasOptions ? "  ▾" : ""}`,
            hasChildren: true,
            key: `${scopeKey}|crafted|${resName}__raw__${rawName}`,
            onOpenStep: rawHasOptions
              ? (e) =>
                  openStepPopup(
                    e.currentTarget,
                    rawInfo,
                    false,
                    async (alt) => {
                      await CraftMapApi.call("set_alt_pref", rawName, alt.recipe_id);
                      await refreshBreakdown({ forceFull: true });
                    },
                    async (stName, m) => {
                      await CraftMapApi.call("set_station_pref", rawName, stName, m);
                      await refreshBreakdown({ forceFull: true });
                    }
                  )
              : null,
            onFirstExpand: (el) => appendDepositLocations(el, rawName, "      "),
          });
          entryChildren.appendChild(rawWrapper);
        }
      }

      // Used only for items reached by recursing into SOME parent's own
      // crafted_names (never for a promoted item's own guaranteed slot -
      // see Phase 1 below) - renders a full row + recurses if this is the
      // first time resName has been seen at all, or an attributed cross-
      // reference (real parentName, so the "X of Y needed here" math
      // means something) if it was already rendered elsewhere.
      function renderNested(container, resName, parentName) {
        const info = items[resName];
        if (!info) return; // shouldn't happen - defensive only
        if (rendered.has(resName)) {
          renderXref(container, resName, info, parentName);
          return;
        }
        const entryChildren = makeCraftedRow(container, resName, info);
        expandCraftedChildren(entryChildren, resName, info);
      }

      // "Promoted" items get a guaranteed, stable row of their own -
      // either because they're root-demand (a direct ingredient of some
      // queued job) or because they're genuinely shared (2+ distinct
      // parents, even if none of those parents is a job root - e.g. an
      // intermediate part reused by several different assemblies). Both
      // cases give a cross-reference a real, findable destination to
      // point at; an item with neither property has exactly one real
      // parent, so it just nests there directly with nothing to promote.
      const rootDemanded = craftedEntries
        .filter(([, info]) => info.is_root_demand)
        .sort(craftedNameSort);
      const sharedOnly = craftedEntries
        .filter(([, info]) => !info.is_root_demand && info.is_shared)
        .sort(craftedNameSort);

      // Phase 1: give EVERY promoted item its own row first, before ANY
      // of them recurse into their own children. This has to happen
      // before Phase 2 - otherwise, whichever promoted item happens to
      // sort/traverse first "wins" and can render a PEER promoted item as
      // its own nested child purely by reaching it first during
      // recursion, burying something that deserved its own stable slot
      // under an unrelated assembly and leaving its own slot to produce a
      // meaningless cross-reference with no real parent to attribute
      // (this was a real bug, not hypothetical).
      const promotedChildrenEls = new Map();
      for (const [resName, info] of rootDemanded) {
        promotedChildrenEls.set(resName, makeCraftedRow(craftChildren, resName, info));
      }
      // Shared-but-not-root items get their own row too, but nested one
      // level inside Crafted under a "Shared Components" sub-header -
      // still crafted items, just grouped separately for *why* they
      // earned a stable slot, rather than a third top-level peer next to
      // Crafted/Raw Materials (which would make the reader learn a third,
      // invisible category just to know where to look for something).
      if (sharedOnly.length) {
        const { wrapper: sharedHdr, childrenEl: sharedChildren } = makeBdNode({
          tagClass: "section",
          label: "── Shared Components ──",
          hasChildren: true,
          key: `${scopeKey}|shared_hdr`,
        });
        craftChildren.appendChild(sharedHdr);
        for (const [resName, info] of sharedOnly) {
          promotedChildrenEls.set(resName, makeCraftedRow(sharedChildren, resName, info));
        }
      }
      // Phase 2: now expand every promoted item's own children - any
      // OTHER promoted item encountered here is already in `rendered`
      // (from Phase 1), so it correctly becomes an attributed cross-
      // reference instead of getting rendered a second time.
      for (const [resName, info] of [...rootDemanded, ...sharedOnly]) {
        expandCraftedChildren(promotedChildrenEls.get(resName), resName, info);
      }
      // Safety net: anything never reached from a promoted item
      // (shouldn't happen - every occurrence has a parent chain back to
      // some job's root, and that chain always passes through at least
      // one promoted item) still gets its own top-level row rather than
      // silently vanishing.
      for (const [resName] of craftedEntries.sort(craftedNameSort)) {
        if (!rendered.has(resName)) renderNested(craftChildren, resName, null);
      }
    }

    const { wrapper: rawHdr, childrenEl: rawChildren } = makeBdNode({
      tagClass: "section",
      label: "── Raw Materials ──",
      hasChildren: true,
      key: `${scopeKey}|raw_hdr`,
    });
    parentEl.appendChild(rawHdr);
    for (const [resName, info] of rawEntries) {
      // A raw entry can still carry alts if it's a real recipe currently
      // forced to "Raw Material" (see resolver.py's RAW_MATERIAL_PREF) -
      // offer the same picker crafted rows get, so it can be switched back.
      const hasOptions = nodeHasStepOptions(info);
      const { wrapper: rawWrapper } = makeBdNode({
        tagClass: info.fully_checked ? "done" : "ingredient",
        label: `${fmtNum(info.qty)}×  ${resName}${formatSourcesSuffix(info.sources)}${
          hasOptions ? "  ▾" : ""
        }`,
        checked: checkboxState(info),
        hasChildren: true,
        key: `${scopeKey}|raw|${resName}`,
        onToggleCheck: async () => {
          await CraftMapApi.call(
            "set_totals_item_checked",
            info.occurrences,
            !info.fully_checked
          );
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
                async (stName, m) => {
                  await CraftMapApi.call("set_station_pref", resName, stName, m);
                  await refreshBreakdown({ forceFull: true });
                }
              )
          : null,
        onFirstExpand: (el) => appendDepositLocations(el, resName, "    "),
      });
      rawChildren.appendChild(rawWrapper);
    }
  }

  async function renderTotalsMode(forceFull) {
    const view = await CraftMapApi.call("get_queue_totals_view", forceFull);
    if (!view.jobs_count) {
      const { wrapper } = makeBdNode({
        tagClass: "section",
        label: "Queue is empty.",
        hasChildren: false,
      });
      tree.appendChild(wrapper);
      return;
    }
    const { wrapper, childrenEl } = makeBdNode({
      tagClass: "root",
      label: `◆  All Jobs  (${view.combined_count})`,
      hasChildren: true,
      isRoot: true,
      key: "__all_jobs__",
    });
    tree.appendChild(wrapper);
    // "All Jobs" is the section actually being looked at almost always, so
    // it's built eagerly - but each individual job's own breakdown below
    // (usually not even open) is deferred behind onFirstExpand, same as
    // recipe-panel.js's insertBreakdownNode: a render's cost should be
    // proportional to what's actually expanded, not to how many jobs are
    // queued.
    insertTotalsSections(childrenEl, "all", view.all_items);

    if (view.jobs_count > 1) {
      const { wrapper: perHdr, childrenEl: perChildren } = makeBdNode({
        tagClass: "section",
        label: "── Per Recipe ──",
        hasChildren: true,
        key: "__per_recipe__",
      });
      tree.appendChild(perHdr);
      for (const job of view.per_job) {
        const { wrapper: jobRoot } = makeBdNode({
          tagClass: "root",
          label: `◆  ${job.recipe_name}  ×${fmtNum(job.qty)}`,
          hasChildren: true,
          key: `__job__${job.queue_id}`,
          // A job's own breakdown is fetched only once its section is
          // actually opened - get_queue_totals_view deliberately doesn't
          // carry every job's items eagerly (see its docstring), since
          // most never get looked at.
          onFirstExpand: async (el) => {
            const jobView = await CraftMapApi.call("get_queue_totals_job_view", job.queue_id);
            insertTotalsSections(el, `job:${job.queue_id}`, jobView.items);
          },
        });
        perChildren.appendChild(jobRoot);
      }
    }
  }

  // ---- refresh dispatcher ----
  async function refreshBreakdown({ forceFull = false } = {}) {
    await renderer.ready;
    tree.innerHTML = "";
    try {
      if (mode === "totals") {
        await renderTotalsMode(forceFull);
      } else {
        await renderQueueMode(forceFull);
      }
    } catch (e) {
      CraftMapApi._showError(`refreshBreakdown: ${e.message || e}`);
      throw e;
    }
  }

  // Called from Python (see backend/api.py's _notify_queue_window_changed)
  // whenever a job is added from a different window/document than this
  // one - the recipe panel's '+ Queue' button, currently the only such
  // path (every other queue mutation only ever happens from within this
  // same window, which already refreshes itself locally afterward).
  window.QueuePanel = {
    async refresh() {
      await refreshJobList();
      if (mode === "totals") await refreshBreakdown();
    },
  };

  async function setMode(m) {
    mode = m;
    modeQueueBtn.classList.toggle("active", mode === "queue");
    modeTotalsBtn.classList.toggle("active", mode === "totals");
    // Entering Totals mode always forces a full recompute: an alt-recipe/
    // station pick made while in Queue mode is a global, ingredient-name-
    // keyed preference that the Totals tree cache's per-job key can't see
    // (see Api._get_totals_job_specs) - mode switches are rare enough that
    // paying for a fresh resolve here isn't worth tracking that edge case
    // instead.
    await refreshBreakdown({ forceFull: mode === "totals" });
  }

  // ---- job-list / breakdown split (mirrors the tkinter PanedWindow sash) ----
  function initSplit() {
    let dragState = null;
    splitEl.addEventListener("pointerdown", (e) => {
      dragState = { startY: e.screenY, startH: jobListEl.offsetHeight };
      splitEl.setPointerCapture(e.pointerId);
    });
    splitEl.addEventListener("pointermove", (e) => {
      if (!dragState) return;
      const h = Math.max(40, dragState.startH + (e.screenY - dragState.startY));
      jobListEl.style.height = `${h}px`;
    });
    splitEl.addEventListener("pointerup", () => {
      if (dragState) {
        dragState = null;
        CraftMapApi.call("save_queue_split", jobListEl.offsetHeight);
      }
    });
  }

  // ---- pin ----
  async function initPin() {
    const setPinVisual = (pinned) => pinBtn.classList.toggle("active", pinned);
    setPinVisual(await CraftMapApi.call("get_queue_pinned"));
    pinBtn.addEventListener("click", async () => {
      const pinned = await CraftMapApi.call("toggle_queue_pin");
      setPinVisual(pinned);
    });
  }

  // ---- init ----
  async function init() {
    const split = await CraftMapApi.call("get_queue_split");
    jobListEl.style.height = `${split}px`;
    initSplit();
    await initPin();

    new LiveDropdown(addRecipeInput, {
      getValues: async () => {
        const recipes = await CraftMapApi.call("get_all_recipes");
        return recipes.map((r) => r.name);
      },
    });
    addRecipeInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") addJob();
    });

    addBtn.addEventListener("click", addJob);
    clearDoneBtn.addEventListener("click", clearAllDone);
    modeQueueBtn.addEventListener("click", () => setMode("queue"));
    modeTotalsBtn.addEventListener("click", () => setMode("totals"));

    // Same rationale as recipe-panel.js's tree: this pane gets even less
    // vertical space, so scale the wheel-scroll distance down.
    tree.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        tree.scrollTop += e.deltaY * 0.15;
      },
      { passive: false }
    );
    jobListEl.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        jobListEl.scrollTop += e.deltaY * 0.5;
      },
      { passive: false }
    );

    await refreshJobList();
    await refreshBreakdown();
  }

  init();
})();
