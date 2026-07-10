/* Top-level screen switch between the deposit tracker and the recipe
 * panel - mirrors overlay.py's Overlay._apply_view_visibility, which
 * shows/hides whole frames based on a single view_mode ("resource" /
 * "location" / "recipe") rather than each screen owning a chunk of the
 * tab row independently. Resource/Location remain deposits.js's own
 * concern (its two sub-tabs); this just decides which top-level screen
 * is visible and keeps the Recipe tab's active state in sync.
 */
(function () {
  const depositsView = document.getElementById("deposits-view");
  const recipeView = document.getElementById("recipe-view");
  const tabResource = document.getElementById("tab-resource");
  const tabLocation = document.getElementById("tab-location");
  const tabRecipe = document.getElementById("tab-recipe");
  const tabQueue = document.getElementById("tab-queue");

  function showDeposits() {
    recipeView.style.display = "none";
    depositsView.style.display = "flex";
    tabRecipe.classList.remove("active");
  }

  function showRecipe() {
    depositsView.style.display = "none";
    recipeView.style.display = "flex";
    tabResource.classList.remove("active");
    tabLocation.classList.remove("active");
    tabRecipe.classList.add("active");
  }

  tabResource.addEventListener("click", showDeposits);
  tabLocation.addEventListener("click", showDeposits);
  tabRecipe.addEventListener("click", async () => {
    showRecipe();
    await CraftMapApi.call("set_view_mode", "recipe");
  });

  // The Queue tab isn't a screen switch like the other three - it toggles
  // the separate always-on-top Craft Queue window, mirroring
  // craftmap/overlay.py's Overlay._btn_queue_panel (also just a plain
  // toggle button living in the same tab row, not a real "tab"). Its
  // active/inactive state is pushed from Python via QueueTab.setActive
  // (see main.py) rather than tracked purely client-side, since the queue
  // window can also be shown/hidden from its own X button, Escape, or the
  // pin toggle - none of which this button's own click handler sees.
  tabQueue.addEventListener("click", () => {
    CraftMapApi.call("toggle_queue_window");
  });

  window.QueueTab = {
    setActive(active) {
      tabQueue.classList.toggle("active", active);
    },
  };

  // #recipe-view starts as display:none (deposits-view is the visible-by-
  // default screen in the base CSS) until this async IPC round-trip
  // resolves and picks the actually-saved view - drag-resize.js's launch-
  // time min-size measurement needs to wait for that, or it risks
  // measuring whichever screen happens to still be showing by default
  // (usually the smaller deposits screen) instead of the one the user was
  // really last on, undershooting the real minimum.
  let resolveViewReady;
  window.__viewModeReady = new Promise((resolve) => {
    resolveViewReady = resolve;
  });

  (async () => {
    const mode = await CraftMapApi.call("get_view_mode");
    if (mode === "recipe") {
      showRecipe();
    } else {
      showDeposits();
    }
    resolveViewReady();
  })();
})();
