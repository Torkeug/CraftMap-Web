/* Drag-bar move + resize-grip resize, factored into DragResize.attach() so
 * both the main window (index.html) and the Craft Queue window (queue.html)
 * can reuse it against their own dragbar/resize-grip elements and their own
 * Api geometry methods (move_window/resize_window/... vs. move_queue_window/
 * resize_queue_window/...) - see each HTML file's own init call at the
 * bottom of its <script> block.
 *
 * Deliberately NOT pywebview's built-in whole-window drag (there is no such
 * single-call feature used here anyway) - this binds only to the given
 * dragbar/grip elements, and explicitly ignores clicks on buttons inside
 * the drag bar, so the close/settings/pin buttons stay clickable.
 *
 * Native calls are serialized (never more than one in flight, always
 * sending the latest pending value once the previous call completes)
 * rather than fired on every requestAnimationFrame tick regardless of
 * completion - firing blindly let dozens of calls queue up per gesture,
 * and if pywebview/pythonnet's js_api dispatch doesn't process them in
 * strict order, a stale in-flight call can land *last* and silently
 * become the final window state right as the drag stops.
 */
const DragResize = (function () {
  // The true minimum a window can shrink to without squashing its current
  // screen's layout depends on which screen is showing (deposits vs.
  // recipe vs. queue) and isn't a single number that's safe to hardcode -
  // a fixed-width control like the recipe combobox, or a form section
  // that grows with however many station/output rows exist, can each
  // shift it. Rather than guess a constant (and risk being wrong the way
  // a hardcoded one was), measure the CURRENT screen's actual natural
  // size: css/theme.css's #app.measuring-min-size and css/components.css's
  // matching overrides free every normally space-filling flex:1 pane from
  // stretching to fill the window's current (possibly generous) size for
  // one synchronous reflow, so #app.scrollWidth/scrollHeight reports what
  // the layout genuinely needs instead of just echoing back whatever size
  // the window already happens to be.
  // Extra headroom added on top of the raw measured height - the measured
  // number is the layout's exact natural height with no slack at all, so
  // anything not perfectly captured by the measuring-min-size overrides
  // (rounding, a row that's marginally taller than expected, etc.) could
  // still leave things feeling one row too tight right at the boundary.
  const MEASURED_HEIGHT_MARGIN = 100;

  function measureMinSize(fallbackW, fallbackH) {
    const app = document.getElementById("app");
    if (!app) return { width: fallbackW, height: fallbackH };
    app.classList.add("measuring-min-size");
    // Reading offsetHeight forces the browser to actually apply the class
    // above and recompute layout before scrollWidth/scrollHeight below is
    // read, instead of possibly reusing a stale cached layout.
    void app.offsetHeight;
    const width = Math.ceil(Math.max(fallbackW, app.scrollWidth));
    const height = Math.ceil(
      Math.max(fallbackH, app.scrollHeight + MEASURED_HEIGHT_MARGIN)
    );
    app.classList.remove("measuring-min-size");
    return { width, height };
  }

  function attach({
    dragbarEl,
    gripEl,
    getGeometry,
    moveWindow,
    resizeWindow,
    saveGeometry,
    // Kept comfortably above main.py's create_window(min_size=(320, 200)):
    // if our requested size ever gets close enough to WinForms' own
    // enforced minimum, a rounding difference between two independently-
    // computed DPI scale conversions (one at window creation, one per
    // resize() call) can push us a hair below it, triggering WinForms'
    // internal size-rejection path instead of a normal resize - that's
    // what caused the blinking/position-jump/stuck-drag-state glitch right
    // at the boundary.
    minW = 360,
    minH = 240,
  }) {
    let winX = 0;
    let winY = 0;
    let winW = 0;
    let winH = 0;

    async function syncGeometry() {
      // See frontend/js/screens.js's __viewModeReady - only index.html
      // defines it (queue.html has no equivalent multi-screen race, since
      // its Queue/Totals toggle never changes which top-level container is
      // display:none). Without this wait, the measurement below could run
      // while the wrong screen still has its default visibility, before
      // the saved view mode has actually been applied.
      if (window.__viewModeReady) await window.__viewModeReady;

      const geo = await getGeometry();
      winX = geo.x;
      winY = geo.y;
      winW = geo.width;
      winH = geo.height;

      // The on-launch size comes straight from config.json (or main.py's
      // hardcoded default) - neither is validated against this screen's
      // actual minimum the way a resize-grip drag is (see the grip's own
      // pointerdown handler below). A size saved before this screen's
      // layout existed/changed, or just the plain hardcoded default, can
      // easily undershoot it - so clamp once here too, and persist the
      // correction so next launch already starts right.
      const measured = measureMinSize(minW, minH);
      if (winW < measured.width || winH < measured.height) {
        winW = Math.max(winW, measured.width);
        winH = Math.max(winH, measured.height);
        await resizeWindow(winX, winY, winW, winH);
        await saveGeometry(winX, winY, winW, winH);
      }
    }
    syncGeometry();

    function makeSerializedSender(callFn) {
      let inFlight = false;
      let pending = null;

      function send() {
        if (inFlight || pending === null) return;
        const args = pending;
        pending = null;
        inFlight = true;
        callFn(...args).finally(() => {
          inFlight = false;
          send();
        });
      }

      return (...args) => {
        pending = args;
        send();
      };
    }

    const sendMove = makeSerializedSender((x, y) => moveWindow(x, y));
    const sendResize = makeSerializedSender((x, y, w, h) => resizeWindow(x, y, w, h));

    let dragState = null;

    dragbarEl.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".icon-btn")) return;
      dragState = {
        startScreenX: e.screenX,
        startScreenY: e.screenY,
        startWinX: winX,
        startWinY: winY,
      };
      dragbarEl.setPointerCapture(e.pointerId);
    });

    window.addEventListener("pointermove", (e) => {
      if (!dragState) return;
      winX = dragState.startWinX + (e.screenX - dragState.startScreenX);
      winY = dragState.startWinY + (e.screenY - dragState.startScreenY);
      sendMove(winX, winY);
    });

    window.addEventListener("pointerup", () => {
      if (dragState) {
        dragState = null;
        saveGeometry(winX, winY, winW, winH);
      }
    });

    let resizeState = null;

    gripEl.addEventListener("pointerdown", (e) => {
      const measured = measureMinSize(minW, minH);
      resizeState = {
        startScreenX: e.screenX,
        startScreenY: e.screenY,
        startW: winW,
        startH: winH,
        // Recomputed fresh on every grip-press (cheap - just a DOM
        // reflow, no IPC) rather than once at page load, since which
        // screen is currently showing (and so what the true minimum is)
        // can change between drags.
        minW: measured.width,
        minH: measured.height,
        // Anchor position, captured once - resent on every resize call
        // below instead of trusting pywebview's own "keep current
        // position" resize logic, which drifts: WinForms' AutoScaleMode.
        // Dpi nudges the form's Location asynchronously after each
        // SetWindowPos, and since that nudge lands *between* calls (not
        // within one), each next resize call reads the already-drifted
        // position as "current" and re-preserves it, compounding the
        // drift every frame.
        anchorX: winX,
        anchorY: winY,
      };
      gripEl.setPointerCapture(e.pointerId);
      e.stopPropagation();
    });

    window.addEventListener("pointermove", (e) => {
      if (!resizeState) return;
      winW = Math.max(
        resizeState.minW,
        resizeState.startW + (e.screenX - resizeState.startScreenX)
      );
      winH = Math.max(
        resizeState.minH,
        resizeState.startH + (e.screenY - resizeState.startScreenY)
      );
      // Position never actually changes during this NORTH|WEST-anchored
      // resize, but keep the globals in sync so a drag started right after
      // this resize (before any move gesture updates them) uses the
      // correct baseline instead of a stale pre-resize value.
      winX = resizeState.anchorX;
      winY = resizeState.anchorY;
      sendResize(resizeState.anchorX, resizeState.anchorY, winW, winH);
    });

    window.addEventListener("pointerup", () => {
      if (resizeState) {
        resizeState = null;
        saveGeometry(winX, winY, winW, winH);
      }
    });

    return {
      // Exposed so a caller can re-sync after an external geometry change
      // (none currently needed, but cheap to offer).
      syncGeometry,
    };
  }

  return { attach };
})();
