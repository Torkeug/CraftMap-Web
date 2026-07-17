/* Generic themed confirm modal - a DOM modal instead of the browser's
 * native window.confirm(), same rationale frontend/js/settings.js's hotkey
 * dialog and breakdown-tree.js's step popup already follow for this app's
 * frameless/topmost/translucent WebView2 windows: a native dialog doesn't
 * match the dark theme and can behave oddly (focus/z-order) layered over a
 * topmost window. Promise-based - `await ConfirmDialog.confirm(...)`
 * resolves true (confirmed) or false (cancelled, Escape, or backdrop
 * click), mirroring window.confirm()'s own return convention so call
 * sites read the same way.
 */
(function () {
  const dialog = document.getElementById("confirm-dialog");
  const titleEl = document.getElementById("confirm-dialog-title");
  const messageEl = document.getElementById("confirm-dialog-message");
  const closeBtn = document.getElementById("confirm-dialog-close-btn");
  const cancelBtn = document.getElementById("confirm-dialog-cancel-btn");
  const okBtn = document.getElementById("confirm-dialog-ok-btn");

  // Only one confirm can be open at a time (it's a modal) - resolves
  // whichever confirm() call is currently pending.
  let resolvePending = null;

  function onEscape(e) {
    if (e.key === "Escape") settle(false);
  }

  function settle(result) {
    if (!resolvePending) return;
    const resolve = resolvePending;
    resolvePending = null;
    dialog.classList.add("hidden");
    document.removeEventListener("keydown", onEscape, true);
    resolve(result);
  }

  function confirm({ title = "Confirm", message = "", confirmText = "Delete" } = {}) {
    titleEl.textContent = title;
    messageEl.textContent = message;
    okBtn.textContent = confirmText;
    dialog.classList.remove("hidden");
    document.addEventListener("keydown", onEscape, true);
    return new Promise((resolve) => {
      resolvePending = resolve;
    });
  }

  closeBtn.addEventListener("click", () => settle(false));
  cancelBtn.addEventListener("click", () => settle(false));
  okBtn.addEventListener("click", () => settle(true));
  dialog.addEventListener("mousedown", (e) => {
    if (e.target === dialog) settle(false); // backdrop click
  });

  window.ConfirmDialog = { confirm };
})();
