/* Thin wrapper around window.pywebview.api.* - every call goes through
 * here so failures show as an inline banner (matching the dark theme)
 * instead of a modal dialog, which would risk re-introducing the exact
 * focus-stealing problem the tkinter app's _StepPopup was built to avoid
 * this session. See backend/api.py for the Python side.
 */
const CraftMapApi = {
  // window.pywebview.api is injected asynchronously after the page loads -
  // calling it from a page-load script before the bridge exists throws
  // (or, worse, can wedge the underlying COM bridge). Every call routes
  // through this same awaited promise so callers don't each need their own
  // pywebviewready listener.
  _ready: new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) {
      resolve();
    } else {
      window.addEventListener("pywebviewready", () => resolve(), { once: true });
    }
  }),

  async call(name, ...args) {
    await CraftMapApi._ready;
    try {
      const fn = window.pywebview.api[name];
      if (!fn) {
        throw new Error(`No such API method: ${name}`);
      }
      return await fn(...args);
    } catch (err) {
      CraftMapApi._showError(`${name}: ${err.message || err}`);
      throw err;
    }
  },

  _showError(message) {
    const banner = document.getElementById("error-banner");
    if (!banner) return;
    banner.textContent = message;
    banner.classList.add("show");
    clearTimeout(CraftMapApi._errorTimer);
    CraftMapApi._errorTimer = setTimeout(() => {
      banner.classList.remove("show");
    }, 6000);
  },
};
