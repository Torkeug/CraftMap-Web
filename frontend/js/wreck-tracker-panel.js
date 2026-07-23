/* Wreck Tracker window: a flat heading-strip HUD (like a flight-sim compass
 * ribbon) showing where currently-tracked wreck hulls/crates/black boxes are
 * relative to the player ship's own facing - not just distance, since "how
 * far" alone doesn't tell you which way to turn. Polls backend/api.py's
 * get_live_wreck_snapshot (the sibling spacecraft-memory-research repo's
 * wreck_tracker.py poller's own overwritten-every-cycle JSON snapshot,
 * passed through as-is) independently of whatever the main window's Wrecks
 * tab is doing - this window has its own lifecycle (see main.py's
 * App.show_wreck_tracker_window/hide_wreck_tracker_window), same as the
 * queue window keeps refreshing while the main window is hidden.
 *
 * Bearing math: ship_forward/ship_up (see wreck_tracker.py's
 * read_player_ship_orientation) are confirmed-live unit vectors, orthogonal
 * to each other (dot product ~0) - see that function's own docstring. right
 * = cross(up, forward) completes an orthonormal frame; a target's bearing is
 * the signed angle between "straight ahead" and its direction in that
 * frame's horizontal (forward/right) plane. cross(up, forward), not
 * cross(forward, up) - confirmed live against an actual in-game turn (the
 * first version had it backwards: turning right moved markers left on the
 * strip). If this ever needs re-deriving, the confirming test is simple:
 * turn the ship one way in-game and check the strip's markers sweep the
 * SAME way, not opposite. No elevation axis - wreck/crate nodes sit on the
 * planet surface, so an above/below indicator was dead weight (removed per
 * user feedback); all markers render on one horizontal line, distinguished
 * by bearing (left-right position) and distance (dot size/opacity - see
 * markerScale) only.
 */
(function () {
  const statusEl = document.getElementById("wreck-tracker-status");
  const planetEl = document.getElementById("wreck-tracker-planet");
  const stripMarkersEl = document.getElementById("heading-strip-markers");
  const stripTicksEl = document.getElementById("heading-strip-ticks");
  const pinBtn = document.getElementById("pin-btn");
  const legendShipEl = document.getElementById("wreck-tracker-legend-ship");
  const legendOnFootEl = document.getElementById("wreck-tracker-legend-onfoot");

  // Matches wreck_tracker.py's own --ship-interval default (1/60s, NOT
  // --interval - that one's just the slower wreck/crate node-scan
  // cadence, decoupled from ship position/heading freshness on purpose,
  // see that script's own module docstring). Polling much slower than
  // the poller's own write cadence was the actual bottleneck at every
  // earlier step of speeding this up - this file's own POLL_MS always
  // has to keep pace with whatever the poller side achieves, or none of
  // that speedup is visible. 60Hz is right at (arguably past) the point
  // where the pywebview/pythonnet IPC bridge's own per-call cost - not
  // measured as precisely as the poller-side numbers documented in
  // wreck_tracker.py - becomes the real unknown; drop this if it turns
  // out the bridge can't actually keep up smoothly at this rate.
  const POLL_MS = 17;
  // Visible bearing window on the strip - anything beyond this clamps to
  // the edge with an arrow rather than being hidden, so a target directly
  // behind you still shows SOME hint of which side to turn toward.
  const BEARING_RANGE_DEG = 100;
  // On-foot marker range cap (see render's own per-mode filtering
  // comment) - a round number in the same neighborhood as CLUSTER_DIST
  // below but serving a completely different purpose (which nodes are
  // shown at all, not which ones get merged into one marker).
  const ON_FOOT_MAX_DISTANCE = 1000;

  // Kept in sync with wreck_tracker.py's WRECK_HULL_IDS (spacecraft-memory-
  // research repo) - a wreck's hull isn't always a single ShipWreck_Lvl0/1/2
  // node, it can instead be built from BigPiece1/BigPiece2/SmallPiece1/
  // SmallPiece2 sibling pieces (same parentId, same data.cdb type=7
  // "Shipwreck" category). Missed here originally the same way it was
  // missed backend-side: a wreck using the BigPiece/SmallPiece variant had
  // its crates show on the strip but not its hull.
  const HULL_IDS = new Set([
    "ShipWreck_Lvl0", "ShipWreck_Lvl1", "ShipWreck_Lvl2",
    "ShipWreck_BigPiece1_lvl0", "ShipWreck_BigPiece1_lvl1", "ShipWreck_BigPiece1_lvl2",
    "ShipWreck_BigPiece2_lvl0", "ShipWreck_BigPiece2_lvl1", "ShipWreck_BigPiece2_lvl2",
    "ShipWreck_SmallPiece1", "ShipWreck_SmallPiece2",
  ]);
  const RESOURCE_DISPLAY = {
    ShipWreck_Lvl0: "Wreck",
    ShipWreck_Lvl1: "Wreck",
    ShipWreck_Lvl2: "Wreck",
    ShipWreck_BigPiece1_lvl0: "Wreck",
    ShipWreck_BigPiece1_lvl1: "Wreck",
    ShipWreck_BigPiece1_lvl2: "Wreck",
    ShipWreck_BigPiece2_lvl0: "Wreck",
    ShipWreck_BigPiece2_lvl1: "Wreck",
    ShipWreck_BigPiece2_lvl2: "Wreck",
    ShipWreck_SmallPiece1: "Wreck",
    ShipWreck_SmallPiece2: "Wreck",
    ShipWreck_LootChestRare_lvl0: "Crate",
    ShipWreck_LootChestRare_lvl1: "Crate",
    ShipWreck_LootChestRare_lvl2: "Crate",
    ShipWreck_BlackBox: "Black Box",
  };

  // A rare, untiered, walk-up-only pickup (data.cdb type=8, no _lvl
  // variants) - kept in wreck_tracker.py's WRECK_HULL_IDS-sibling
  // BLACKBOX_IDS set. Rendered as its own red marker (matching the game's
  // own data.cdb color for this resourceId, -65536 = ARGB red) rather than
  // folded into "crate" - see classifyNode/render's own on_foot filtering.
  const BLACKBOX_IDS = new Set(["ShipWreck_BlackBox"]);

  // Single source of truth for "what kind of marker is this node" - hull
  // pieces cluster/render distinctly from crates, and black boxes now
  // distinctly again from both (see classifyNode's callers). Anything not
  // explicitly hull or blackbox falls back to "crate" - matches the prior
  // implicit contract (wreck_tracker.py's TRACKED_IDS has only ever held
  // hull/crate/blackbox ids, so this fallback is safe, not just convenient).
  function classifyNode(resourceId) {
    if (HULL_IDS.has(resourceId)) return "hull";
    if (BLACKBOX_IDS.has(resourceId)) return "blackbox";
    return "crate";
  }

  function sub(a, b) {
    return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
  }
  function dot(a, b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
  }
  function cross(a, b) {
    return {
      x: a.y * b.z - a.z * b.y,
      y: a.z * b.x - a.x * b.z,
      z: a.x * b.y - a.y * b.x,
    };
  }
  function length(a) {
    return Math.sqrt(dot(a, a));
  }
  function normalize(a) {
    const l = length(a) || 1;
    return { x: a.x / l, y: a.y / l, z: a.z / l };
  }

  // Returns {bearingDeg, distance} - bearingDeg 0 = straight ahead,
  // positive = right, negative = left. No elevation - wreck/crate nodes
  // sit on the planet surface (per the user: "they're always on the
  // ground"), so an above/below indicator would be dead weight; `up` is
  // still a required input (needed to build the `right` basis vector via
  // cross(up, forward)), it just isn't used for a display axis anymore.
  function relativeDirection(shipPos, forward, up, targetPos) {
    const delta = sub(targetPos, shipPos);
    const distance = length(delta);
    if (distance < 1e-6) return { bearingDeg: 0, distance: 0 };
    const dirn = normalize(delta);
    const right = normalize(cross(up, forward));
    const forwardComp = dot(dirn, forward);
    const rightComp = dot(dirn, right);
    const bearingDeg = (Math.atan2(rightComp, forwardComp) * 180) / Math.PI;
    return { bearingDeg, distance };
  }

  function fmtDistance(d) {
    return d >= 1000 ? `${(d / 1000).toFixed(1)}k` : `${Math.round(d)}`;
  }

  // A wreck's hull is frequently reported as several sibling nodes (its
  // BigPiece1/BigPiece2/SmallPiece1/SmallPiece2 pieces - see HULL_IDS'
  // own comment), and its loot crates cluster at the same spot too -
  // confirmed live, one wreck showed as 5 separate "Wreck" nodes within
  // ~50 units of each other. Rendering each raw node as its own marker
  // stacks several translucent circles on the same screen position;
  // alpha-compositing N same-color layers inflates the visible opacity
  // toward fully solid (a wreck that's actually far away, with several
  // co-located pieces, ends up looking closer/more vivid than a genuinely
  // CLOSER single-piece wreck), while a hull+crate stack instead blends
  // the two hues into a muddy grey - both are artifacts of how many raw
  // nodes happen to share a spot, not real distance. Clustering by
  // position (separately per hull/crate, since those are meaningfully
  // different things to call out even when co-located) before computing
  // bearing/distance means a marker's opacity/size always reflects ONE
  // real-world position. Threshold is a heuristic: generous relative to
  // the ~50-unit sibling-piece spread actually observed, tiny relative to
  // the thousands-to-hundreds-of-thousands-unit range distinct wrecks/
  // crates are normally spaced at.
  const CLUSTER_DIST = 250;

  function positionDist(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    const dz = a.z - b.z;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  // Simple greedy clustering (compare against each cluster's first/
  // representative member, not a running centroid) - node counts per
  // planet are small and the threshold is generous, so this doesn't need
  // to be more precise than that.
  //
  // Crates and black boxes are deliberately never merged while onFoot is
  // true (see render's own use of snapshot.on_foot, sourced from
  // wreck_tracker.py's read_player_is_on_foot) - raised directly by the
  // user after this clustering shipped: walking up to collect them needs
  // each one's own precise bearing/distance, and a single merged marker
  // standing in for several real pickups made them harder to actually
  // find on foot. Hull markers stay merged regardless (a wreck's multiple
  // hull pieces are still one destination to walk to, on foot or not);
  // crates stay merged from a ship too, where the alpha-stacking problem
  // this function exists to fix (see CLUSTER_DIST's own comment) still
  // applies and individual precision doesn't matter at that range (black
  // boxes never reach this function while not on foot at all - see
  // render's own filter, so there's no "merge from a ship" case for them
  // to preserve).
  function clusterNodes(nodes, onFoot) {
    const clusters = [];
    for (const n of nodes) {
      const kind = classifyNode(n.resourceId);
      const mergeable = kind === "hull" || !onFoot;
      const target = mergeable
        ? clusters.find(
            (c) => c.kind === kind && positionDist(c.representative.position, n.position) <= CLUSTER_DIST
          )
        : null;
      if (target) {
        target.members.push(n);
      } else {
        clusters.push({ kind, representative: n, members: [n] });
      }
    }
    return clusters;
  }

  function buildTicks() {
    stripTicksEl.innerHTML = "";
    for (let deg = -90; deg <= 90; deg += 30) {
      const pct = ((deg + BEARING_RANGE_DEG) / (2 * BEARING_RANGE_DEG)) * 100;
      const tick = document.createElement("div");
      tick.className = "heading-strip-tick";
      tick.style.left = `${pct}%`;
      const label = document.createElement("span");
      label.textContent = deg === 0 ? "0" : `${deg > 0 ? "+" : ""}${deg}`;
      tick.appendChild(label);
      stripTicksEl.appendChild(tick);
    }
  }

  // Dot size (and opacity) scale inversely with distance - a fast,
  // read-nothing way to tell closest-from-farthest apart at a glance,
  // replacing the old text list (removed per user feedback: it ate a lot
  // of window space for what the strip's positions mostly already
  // conveyed). Range recalibrated from an initial guess (50-3000) that
  // was WAY too small - confirmed live, real observed distances while
  // in-planet run from ~1000 up to ~150000-200000 units (being
  // "in_planet" per wreck_tracker.py's own snapshot doesn't mean being
  // near the surface - the ship can be far out in orbit, see this
  // repo's own read_player_ship_position derivation), so every dot was
  // clamping to the minimum size regardless of its real relative
  // distance under the old range.
  const NEAR_DISTANCE = 500; // at or below this: full size/opacity
  const FAR_DISTANCE = 150000; // at or beyond this: minimum size/opacity
  const DOT_SIZE_MAX = 16;
  const DOT_SIZE_MIN = 6;

  function markerScale(distance) {
    const t = Math.max(0, Math.min(1, (distance - NEAR_DISTANCE) / (FAR_DISTANCE - NEAR_DISTANCE)));
    return {
      size: DOT_SIZE_MAX - t * (DOT_SIZE_MAX - DOT_SIZE_MIN),
      // Floor raised from 0.35 to 0.7 - the wreck-marker size/tier/edge
      // color encoding (see theme.css's --wreck-size-*/--wreck-tier-*/
      // --wreck-edge comment - a jointly-chosen 6-color set with real
      // margin, ΔE 11.9 CVD / 24.2 normal-vision at full brightness) was
      // re-validated at the actual ALPHA-COMPOSITED result at each
      // candidate floor, not just at full opacity: 0.65 is the minimum
      // where every pair still clears the CVD TARGET post-fade - 0.7 used
      // here for a small margin above that. Confirmed earlier, weaker
      // candidate palettes (smaller full-brightness margins) needed a much
      // higher floor (0.9) to survive the same fade, or failed outright at
      // the OLD 0.35 floor (ΔE 6-10 normal-vision once composited,
      // regardless of hue choice) - no hue pick fixes that on its own,
      // only fading less does; a stronger base palette just needs LESS
      // fade-floor compensation to begin with. `size` above still carries
      // the bulk of the near/far signal on its own (16px -> 6px,
      // independent of this).
      opacity: 1 - t * 0.3,
    };
  }

  // Marker DOM nodes are REUSED across renders rather than torn down and
  // recreated every call - at 60Hz that was measurably janky (confirmed
  // by the user), and it's wasted work anyway: the underlying node LIST
  // only changes every --interval seconds (3s default, see
  // wreck_tracker.py's own slower node-scan cadence), while renderMarkers
  // itself gets called on every fast ship-tick poll just to update
  // bearing/distance for the SAME set of entries. Full rebuild only
  // happens when the entry count actually changes (a wreck/crate
  // appeared or disappeared) - the overwhelming majority of calls just
  // update each existing element's style in place instead of touching
  // the DOM tree structure at all.
  let markerPool = []; // [{el, dotEl}, ...], parallel to the last-rendered entries array

  // stripWidthPx: read ONCE per renderMarkers call, before any style
  // writes in the loop below, never interleaved with them - reading a
  // layout property (clientWidth) after a pending style write is what
  // forces a *synchronous* layout flush ("layout thrashing"); reading it
  // first, then only writing afterward, keeps every write in this
  // function free to batch into the browser's normal next-frame layout
  // pass instead.
  function updateMarkerEl(pooled, e, stripWidthPx) {
    const clampedBearing = Math.max(-BEARING_RANGE_DEG, Math.min(BEARING_RANGE_DEG, e.bearingDeg));
    const atEdge = Math.abs(e.bearingDeg) > BEARING_RANGE_DEG;
    const xPct = ((clampedBearing + BEARING_RANGE_DEG) / (2 * BEARING_RANGE_DEG)) * 100;
    const xPx = (xPct / 100) * stripWidthPx;
    const { size, opacity } = markerScale(e.distance);

    // wreckSize/wreckTier (from the sibling spacecraft-memory-research
    // repo's wreck_tracker.py annotate_wreck_size_tier - Big/Small and
    // 0/1/2, resolved per-wreck via shared parentId) drive their own CSS
    // classes, independent of `size` above (that's the distance-based dot
    // SCALE, an unrelated thing that happens to share the name in the
    // source data - kept separate here as sizeClass/tierClass to avoid
    // colliding with it). Wreck (hull) markers only, per user request -
    // crates don't need this, so the classes are simply never attached for
    // any other kind rather than attached-but-unstyled (keeps the DOM
    // reflecting what's actually shown, not just what CSS happens to
    // ignore). Null for anything not yet resolvable - omitted rather than
    // defaulted, so an unclassified hull node just renders plain instead
    // of falsely claiming small/tier-0.
    const sizeClass = e.kind === "hull" && e.wreckSize ? ` size-${e.wreckSize}` : "";
    const tierClass = e.kind === "hull" && e.wreckTier != null ? ` tier-${e.wreckTier}` : "";
    pooled.el.className = `heading-strip-marker ${e.kind}${sizeClass}${tierClass}${atEdge ? " edge" : ""}`;
    // Horizontal position AND self-centering combined into one transform
    // (left/top stay fixed at 0/50% in CSS - see that rule's own
    // comment) - `calc(${xPx}px - 50%)`'s percentage is relative to the
    // MARKER'S OWN width (how CSS `translate` percentages work), which
    // is exactly the centering `translate(-50%, -50%)` used to do
    // separately when this was expressed via `left` instead.
    pooled.el.style.transform = `translate(calc(${xPx}px - 50%), -50%)`;
    pooled.el.style.opacity = opacity;
    const metaBits = [];
    if (e.kind === "hull" && e.wreckSize) metaBits.push(e.wreckSize === "big" ? "Big" : "Small");
    if (e.kind === "hull" && e.wreckTier != null) metaBits.push(`T${e.wreckTier}`);
    const meta = metaBits.length ? ` (${metaBits.join(" ")})` : "";
    pooled.el.title = `${e.label}${meta} - ${fmtDistance(e.distance)}u, bearing ${Math.round(e.bearingDeg)}°`;
    // Dot is fixed at DOT_SIZE_MAX in CSS - scaled down for distance
    // instead of resizing width/height directly.
    pooled.dotEl.style.transform = `scale(${size / DOT_SIZE_MAX})`;
    pooled.distEl.textContent = fmtDistance(e.distance);
  }

  function makeMarkerEl() {
    const marker = document.createElement("div");

    const dot = document.createElement("span");
    dot.className = "heading-strip-marker-dot";
    marker.appendChild(dot);

    const dist = document.createElement("span");
    dist.className = "heading-strip-marker-dist";
    marker.appendChild(dist);

    return { el: marker, dotEl: dot, distEl: dist };
  }

  function renderMarkers(entries) {
    if (entries.length !== markerPool.length) {
      // Count changed (rare) - full rebuild is simplest and correct;
      // cheap relative to how infrequently this branch actually runs.
      stripMarkersEl.innerHTML = "";
      markerPool = entries.map(() => makeMarkerEl());
      for (const pooled of markerPool) stripMarkersEl.appendChild(pooled.el);
    }
    if (!entries.length) return;
    const stripWidthPx = stripMarkersEl.clientWidth; // single read, see updateMarkerEl's own comment
    entries.forEach((e, i) => updateMarkerEl(markerPool[i], e, stripWidthPx));
  }

  // Mirrors render's own per-mode marker filtering exactly (in ship: hull
  // only; on foot: everything) - called from every branch of render,
  // including its early returns, so the legend never lags a cycle behind
  // or gets stuck showing the wrong group when snapshot/position data is
  // briefly missing. Defaults to the ship group (onFoot=false) when
  // on_foot itself isn't knowable yet, matching relevantNodes' own
  // `snapshot.on_foot` (falsy/undefined) fallback to the in-ship filter.
  function updateLegendMode(onFoot) {
    legendShipEl.classList.toggle("hidden", !!onFoot);
    legendOnFootEl.classList.toggle("hidden", !onFoot);
  }

  function render(snapshot) {
    updateLegendMode(snapshot && snapshot.on_foot);
    if (!snapshot || !snapshot.in_planet) {
      planetEl.textContent = snapshot ? "Not near/in a planet." : "";
      renderMarkers([]);
      return;
    }
    planetEl.textContent = `${snapshot.system_name || "?"} - ${snapshot.planet_name || "?"}`;
    const nodes = snapshot.nodes || [];
    if (!snapshot.ship_position || !snapshot.ship_forward || !snapshot.ship_up) {
      // Position/orientation can lag a cycle behind node data, or be
      // briefly unavailable (e.g. between ship states) - degrade to "no
      // bearing yet" rather than throwing on missing vectors.
      renderMarkers([]);
      return;
    }
    // Per-mode filtering, raised directly by the user:
    // - In ship: ONLY wreck hull markers, at any distance. Hull markers
    //   are the "where to land" signal, worth seeing from orbit; crates/
    //   black boxes aren't collectible without landing anyway, so showing
    //   them from a ship is just noise.
    // - On foot: ALL marker kinds (hull, crate, black box), but capped to
    //   ON_FOOT_MAX_DISTANCE - once you're standing at a site, anything
    //   farther than a short walk belongs to some other site and only
    //   clutters the strip.
    const relevantNodes = snapshot.on_foot
      ? nodes.filter(
          (n) => positionDist(snapshot.ship_position, n.position) <= ON_FOOT_MAX_DISTANCE
        )
      : nodes.filter((n) => classifyNode(n.resourceId) === "hull");
    const entries = clusterNodes(relevantNodes, snapshot.on_foot).map((c) => {
      const n = c.representative;
      const rel = relativeDirection(snapshot.ship_position, snapshot.ship_forward, snapshot.ship_up, n.position);
      return {
        label: RESOURCE_DISPLAY[n.resourceId] || n.resourceId,
        kind: c.kind,
        wreckSize: n.wreckSize || null,
        wreckTier: n.wreckTier != null ? n.wreckTier : null,
        ...rel,
      };
    });
    renderMarkers(entries);
  }

  // The live snapshot FILE persists on disk across poller restarts - if a
  // previous session already wrote one, a freshly (re)started poller's
  // get_live_wreck_snapshot immediately returns that old leftover the
  // instant it's called, well before the new poller has attached/written
  // anything of its own (attach alone can take 1-3 minutes on a cold
  // scan - see wreck_tracker.py's own module docstring). Without this
  // check, that leftover renders as if it were current ("Running -
  // updated <plausible-looking old time>"), which is actively misleading,
  // not just uninformative. Threshold is generous relative to normal
  // cycle time (--ship-interval defaults to 0.2s) but far shorter than
  // any realistic attach time, so it only ever flags genuinely stale
  // carry-over data, not ordinary poll jitter.
  const STALE_THRESHOLD_MS = 5000;

  function isFresh(snapshot) {
    if (!snapshot) return false;
    const age = Date.now() - new Date(snapshot.observed_at).getTime();
    return age < STALE_THRESHOLD_MS;
  }

  // get_wreck_tracking_status barely ever changes (only on Activate/Stop,
  // maybe once every several minutes) - polling it on every fast
  // POLL_MS tick alongside get_live_wreck_snapshot doubled the IPC
  // round-trips for no benefit and was a real contributor to the 60Hz
  // stutter the user reported (each pywebview/pythonnet Api call is a
  // genuine cross-process hop - see CraftMap's own CLAUDE.md on why
  // *call count*, not just payload size, matters over this bridge).
  // Split into its own much slower poll instead; pollSnapshot reads the
  // cached lastKnownRunning rather than awaiting a fresh status call
  // every tick.
  let lastKnownRunning = false;

  async function pollStatus() {
    const status = await CraftMapApi.call("get_wreck_tracking_status");
    lastKnownRunning = status.running;
  }

  // Holds the last snapshot that actually came back non-null, independent
  // of this tick's own result - see pollSnapshot's own comment on why.
  let lastGoodSnapshot = null;

  async function pollSnapshot() {
    let snapshot = null;
    try {
      snapshot = await CraftMapApi.call("get_live_wreck_snapshot");
    } catch (e) {
      // CraftMapApi.call already surfaces this via the error banner
    }
    if (snapshot) lastGoodSnapshot = snapshot;
    // A single tick coming back null/failed doesn't necessarily mean the
    // poller stopped writing - a 17ms poll rate (see POLL_MS's own
    // comment on why it's this fast) means a single transient hiccup
    // (one slow IPC round-trip, or reading current_planet_wrecks.json
    // the instant the poller's atomic rename lands) shows up as exactly
    // one empty tick - user-reported as a split-second flash to the
    // "Starting up..." message that then immediately clears again.
    // Falling back to the last snapshot that DID come back, and judging
    // freshness from THAT instead of this tick's own result, absorbs a
    // one-tick blip silently; the fallback only stops masking it, and
    // "starting"/stale correctly takes over, once no good read has come
    // in for a full STALE_THRESHOLD_MS.
    const effective = snapshot || lastGoodSnapshot;
    const fresh = isFresh(effective);
    if (lastKnownRunning) {
      statusEl.textContent = fresh
        ? `Running - updated ${new Date(effective.observed_at).toLocaleTimeString()}`
        : "Starting up, scanning game memory (can take 1-3 minutes the first time)...";
      statusEl.className = fresh ? "running" : "starting";
    } else {
      statusEl.textContent = "Not running (start it from the Wrecks tab).";
      statusEl.className = "";
    }
    render(fresh ? effective : null);
  }

  async function initPin() {
    const setPinVisual = (pinned) => pinBtn.classList.toggle("active", pinned);
    setPinVisual(await CraftMapApi.call("get_wreck_tracker_pinned"));
    pinBtn.addEventListener("click", async () => {
      const pinned = await CraftMapApi.call("toggle_wreck_tracker_pin");
      setPinVisual(pinned);
    });
  }

  function init() {
    buildTicks();
    initPin();
    pollStatus();
    pollSnapshot();
    setInterval(pollSnapshot, POLL_MS);
    setInterval(pollStatus, 1000);
  }

  init();
})();
