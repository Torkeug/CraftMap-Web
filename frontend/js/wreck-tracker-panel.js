/* Wreck Tracker window: a flat heading-strip HUD (like a flight-sim compass
 * ribbon) showing where currently-tracked wreck hulls/crates are relative to
 * the player ship's own facing - not just distance, since "how far" alone
 * doesn't tell you which way to turn. Polls backend/api.py's
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

  // Matches wreck_tracker.py's own --ship-interval default (0.2s, NOT
  // --interval - that one's just the slower wreck/crate node-scan
  // cadence, decoupled from ship position/heading freshness on purpose,
  // see that script's own module docstring) - polling much slower than
  // the poller's own write cadence here was the actual remaining
  // bottleneck after splitting the poller's two loops (this file kept
  // its old 2000ms value, which capped the HUD's real-world refresh
  // rate regardless of how fast the underlying file was updating).
  const POLL_MS = 200;
  // Visible bearing window on the strip - anything beyond this clamps to
  // the edge with an arrow rather than being hidden, so a target directly
  // behind you still shows SOME hint of which side to turn toward.
  const BEARING_RANGE_DEG = 100;

  const HULL_IDS = new Set(["ShipWreck_Lvl0", "ShipWreck_Lvl1", "ShipWreck_Lvl2"]);
  const RESOURCE_DISPLAY = {
    ShipWreck_Lvl0: "Wreck",
    ShipWreck_Lvl1: "Wreck",
    ShipWreck_Lvl2: "Wreck",
    ShipWreck_LootChestRare_lvl0: "Crate",
    ShipWreck_LootChestRare_lvl1: "Crate",
    ShipWreck_LootChestRare_lvl2: "Crate",
  };

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
      opacity: 1 - t * 0.65,
    };
  }

  function renderMarkers(entries) {
    stripMarkersEl.innerHTML = "";
    for (const e of entries) {
      const clampedBearing = Math.max(-BEARING_RANGE_DEG, Math.min(BEARING_RANGE_DEG, e.bearingDeg));
      const atEdge = Math.abs(e.bearingDeg) > BEARING_RANGE_DEG;
      const xPct = ((clampedBearing + BEARING_RANGE_DEG) / (2 * BEARING_RANGE_DEG)) * 100;
      const { size, opacity } = markerScale(e.distance);

      const marker = document.createElement("div");
      marker.className = `heading-strip-marker ${e.isHull ? "hull" : "crate"}`;
      marker.style.left = `${xPct}%`;
      marker.style.top = "50%";
      marker.style.opacity = opacity;
      marker.title = `${e.label} - ${fmtDistance(e.distance)}u, bearing ${Math.round(e.bearingDeg)}°`;
      if (atEdge) marker.classList.add("edge");

      const dot = document.createElement("span");
      dot.className = "heading-strip-marker-dot";
      dot.style.width = `${size}px`;
      dot.style.height = `${size}px`;
      marker.appendChild(dot);

      const dist = document.createElement("span");
      dist.className = "heading-strip-marker-dist";
      dist.textContent = fmtDistance(e.distance);
      marker.appendChild(dist);

      stripMarkersEl.appendChild(marker);
    }
  }

  function render(snapshot) {
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
    const entries = nodes.map((n) => {
      const rel = relativeDirection(snapshot.ship_position, snapshot.ship_forward, snapshot.ship_up, n.position);
      return {
        label: RESOURCE_DISPLAY[n.resourceId] || n.resourceId,
        isHull: HULL_IDS.has(n.resourceId),
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

  async function poll() {
    let snapshot = null;
    try {
      snapshot = await CraftMapApi.call("get_live_wreck_snapshot");
    } catch (e) {
      // CraftMapApi.call already surfaces this via the error banner
    }
    const fresh = isFresh(snapshot);
    const status = await CraftMapApi.call("get_wreck_tracking_status");
    if (status.running) {
      statusEl.textContent = fresh
        ? `Running - updated ${new Date(snapshot.observed_at).toLocaleTimeString()}`
        : "Starting up, scanning game memory (can take 1-3 minutes the first time)...";
      statusEl.className = fresh ? "running" : "starting";
    } else {
      statusEl.textContent = "Not running (start it from the Wrecks tab).";
      statusEl.className = "";
    }
    render(fresh ? snapshot : null);
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
    poll();
    setInterval(poll, POLL_MS);
  }

  init();
})();
