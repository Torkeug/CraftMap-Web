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

  (async () => {
    const mode = await CraftMapApi.call("get_view_mode");
    if (mode === "recipe") {
      showRecipe();
    } else {
      showDeposits();
    }
  })();
})();
