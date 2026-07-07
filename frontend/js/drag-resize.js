/* Drag-bar move + resize-grip resize. Deliberately NOT pywebview's
 * built-in whole-window drag (there is no such single-call feature used
 * here anyway) - this binds only to #dragbar and #resize-grip, and
 * explicitly ignores clicks on buttons inside the drag bar, so the
 * close/settings buttons stay clickable.
 *
 * Native calls are serialized (never more than one in flight, always
 * sending the latest pending value once the previous call completes)
 * rather than fired on every requestAnimationFrame tick regardless of
 * completion - firing blindly let dozens of calls queue up per gesture,
 * and if pywebview/pythonnet's js_api dispatch doesn't process them in
 * strict order, a stale in-flight call can land *last* and silently
 * become the final window state right as the drag stops.
 */
(function () {
  let winX = 0;
  let winY = 0;
  let winW = 0;
  let winH = 0;

  async function syncGeometry() {
    const geo = await CraftMapApi.call("get_window_geometry");
    winX = geo.x;
    winY = geo.y;
    winW = geo.width;
    winH = geo.height;
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

  const sendMove = makeSerializedSender((x, y) => CraftMapApi.call("move_window", x, y));
  const sendResize = makeSerializedSender((x, y, w, h) =>
    CraftMapApi.call("resize_window", x, y, w, h)
  );

  const dragbar = document.getElementById("dragbar");
  let dragState = null;

  dragbar.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".icon-btn")) return;
    dragState = {
      startScreenX: e.screenX,
      startScreenY: e.screenY,
      startWinX: winX,
      startWinY: winY,
    };
    dragbar.setPointerCapture(e.pointerId);
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
      CraftMapApi.call("save_window_geometry", winX, winY, winW, winH);
    }
  });

  const grip = document.getElementById("resize-grip");
  let resizeState = null;
  // Kept comfortably above main.py's create_window(min_size=(320, 200)):
  // if our requested size ever gets close enough to WinForms' own enforced
  // minimum, a rounding difference between two independently-computed DPI
  // scale conversions (one at window creation, one per resize() call) can
  // push us a hair below it, triggering WinForms' internal size-rejection
  // path instead of a normal resize - that's what caused the blinking/
  // position-jump/stuck-drag-state glitch right at the boundary.
  const MIN_W = 360;
  const MIN_H = 240;

  grip.addEventListener("pointerdown", (e) => {
    resizeState = {
      startScreenX: e.screenX,
      startScreenY: e.screenY,
      startW: winW,
      startH: winH,
      // Anchor position, captured once - resent on every resize call below
      // instead of trusting pywebview's own "keep current position" resize
      // logic, which drifts: WinForms' AutoScaleMode.Dpi nudges the form's
      // Location asynchronously after each SetWindowPos, and since that
      // nudge lands *between* calls (not within one), each next resize call
      // reads the already-drifted position as "current" and re-preserves
      // it, compounding the drift every frame.
      anchorX: winX,
      anchorY: winY,
    };
    grip.setPointerCapture(e.pointerId);
    e.stopPropagation();
  });

  window.addEventListener("pointermove", (e) => {
    if (!resizeState) return;
    winW = Math.max(MIN_W, resizeState.startW + (e.screenX - resizeState.startScreenX));
    winH = Math.max(MIN_H, resizeState.startH + (e.screenY - resizeState.startScreenY));
    // Position never actually changes during this NORTH|WEST-anchored
    // resize, but keep the globals in sync so a drag started right after
    // this resize (before any move gesture updates them) uses the correct
    // baseline instead of a stale pre-resize value.
    winX = resizeState.anchorX;
    winY = resizeState.anchorY;
    sendResize(resizeState.anchorX, resizeState.anchorY, winW, winH);
  });

  window.addEventListener("pointerup", () => {
    if (resizeState) {
      resizeState = null;
      CraftMapApi.call("save_window_geometry", winX, winY, winW, winH);
    }
  });
})();
