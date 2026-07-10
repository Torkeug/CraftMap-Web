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

  const renderer = BreakdownTree.createRenderer({ treeEl: tree, stepPopupEl });
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
  function insertTotalsSections(parentEl, queueId, crafted, raw, checked) {
    const craftedEntries = Object.entries(crafted).sort((a, b) =>
      a[0].toLowerCase().localeCompare(b[0].toLowerCase())
    );
    if (craftedEntries.length) {
      const { wrapper: craftHdr, childrenEl: craftChildren } = makeBdNode({
        tagClass: "section",
        label: "── Crafted ──",
        hasChildren: true,
        key: `__crafted__${queueId}`,
      });
      parentEl.appendChild(craftHdr);

      for (const [resName, info] of craftedEntries) {
        const qty = info.qty;
        const oq = info.output_qty || 1.0;
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
          hasChildren: (info.raw_names || []).length > 0,
          key: `${queueId}|${pathKey}`,
          onToggleCheck: async () => {
            await CraftMapApi.call("set_queue_checked_many", queueId, [pathKey], !isDone);
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
                    await refreshBreakdown();
                  },
                  async (stName, m) => {
                    await CraftMapApi.call("set_station_pref", resName, stName, m);
                    await refreshBreakdown();
                  }
                )
            : null,
        });
        craftChildren.appendChild(entryWrapper);

        for (const rawName of info.raw_names || []) {
          const { wrapper: rawWrapper } = makeBdNode({
            tagClass: "location",
            label: `    ${rawName}`,
            hasChildren: true,
            key: `${queueId}|${pathKey}__raw__${rawName}`,
            onFirstExpand: (el) => appendDepositLocations(el, rawName, "      "),
          });
          entryChildren.appendChild(rawWrapper);
        }
      }
    }

    const { wrapper: rawHdr, childrenEl: rawChildren } = makeBdNode({
      tagClass: "section",
      label: "── Raw Materials ──",
      hasChildren: true,
      key: `__raw__${queueId}`,
    });
    parentEl.appendChild(rawHdr);
    const rawEntries = Object.entries(raw).sort((a, b) =>
      a[0].toLowerCase().localeCompare(b[0].toLowerCase())
    );
    for (const [resName, qty] of rawEntries) {
      const pathKey = `__total__|${resName}`;
      const isDone = checked.has(pathKey);
      const { wrapper: rawWrapper } = makeBdNode({
        tagClass: isDone ? "done" : "ingredient",
        label: `${fmtNum(qty)}×  ${resName}`,
        checked: isDone,
        hasChildren: true,
        key: `${queueId}|${pathKey}`,
        onToggleCheck: async () => {
          await CraftMapApi.call("set_queue_checked_many", queueId, [pathKey], !isDone);
          await refreshBreakdown();
        },
        onFirstExpand: (el) => appendDepositLocations(el, resName, "    "),
      });
      rawChildren.appendChild(rawWrapper);
    }
  }

  async function renderTotalsMode() {
    const view = await CraftMapApi.call("get_queue_totals_view");
    if (!view.jobs_count) {
      const { wrapper } = makeBdNode({
        tagClass: "section",
        label: "Queue is empty.",
        hasChildren: false,
      });
      tree.appendChild(wrapper);
      return;
    }
    const allChecked = new Set(await CraftMapApi.call("get_queue_checked_paths", 0));
    const { wrapper, childrenEl } = makeBdNode({
      tagClass: "root",
      label: `◆  All Jobs  (${view.combined_count})`,
      hasChildren: true,
      isRoot: true,
      key: "__all_jobs__",
    });
    tree.appendChild(wrapper);
    insertTotalsSections(childrenEl, 0, view.all_crafted, view.all_raw, allChecked);

    if (view.jobs_count > 1) {
      const { wrapper: perHdr, childrenEl: perChildren } = makeBdNode({
        tagClass: "section",
        label: "── Per Recipe ──",
        hasChildren: true,
        key: "__per_recipe__",
      });
      tree.appendChild(perHdr);
      for (const job of view.per_job) {
        const jobChecked = new Set(
          await CraftMapApi.call("get_queue_checked_paths", job.queue_id)
        );
        const { wrapper: jobRoot, childrenEl: jobChildren } = makeBdNode({
          tagClass: "root",
          label: `◆  ${job.recipe_name}  ×${fmtNum(job.qty)}`,
          hasChildren: true,
          key: `__job__${job.queue_id}`,
        });
        perChildren.appendChild(jobRoot);
        insertTotalsSections(jobChildren, job.queue_id, job.crafted, job.raw, jobChecked);
      }
    }
  }

  // ---- refresh dispatcher ----
  async function refreshBreakdown({ forceFull = false } = {}) {
    tree.innerHTML = "";
    try {
      if (mode === "totals") {
        await renderTotalsMode();
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
    await refreshBreakdown();
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
