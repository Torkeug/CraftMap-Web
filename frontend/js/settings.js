/* Hotkey settings dialog - a DOM modal instead of a second pywebview
 * window (unlike craftmap/overlay.py's _open_hotkey_settings, a separate
 * Toplevel), so it inherently never grabs OS focus and there's no two-
 * topmost-window z-order fight to manage - same rationale as the step
 * popup (frontend/js/breakdown-tree.js) and dropdown (frontend/js/
 * dropdown.js) being DOM popovers rather than real windows.
 *
 * The actual key-combo capture runs server-side (backend/main.py's App.
 * _capture_hotkey_worker, via a background thread hooking the keyboard
 * library directly) rather than listening to browser keydown/keyup events
 * here and translating them to a hotkey-library name - that translation
 * would need its own mapping table with no guarantee of matching quirky
 * key names already in real use (config.json's "alt+twosuperior" on a
 * non-US layout). This dialog just triggers the capture and displays
 * whatever result comes back via window.HotkeySettings.onCaptureResult.
 */
(function () {
  const dialog = document.getElementById("settings-dialog");
  const settingsBtn = document.getElementById("settings-btn");
  const closeBtn = document.getElementById("settings-close-btn");
  const closeBtn2 = document.getElementById("hotkey-close-btn");
  const rebindBtn = document.getElementById("hotkey-rebind-btn");
  const display = document.getElementById("hotkey-display");
  const errorEl = document.getElementById("hotkey-error");

  let capturing = false;

  function setRebindIdle() {
    capturing = false;
    rebindBtn.textContent = "Rebind";
    rebindBtn.classList.remove("btn-accent");
    rebindBtn.classList.add("btn-neutral");
  }

  function onEscape(e) {
    if (e.key === "Escape") closeDialog();
  }

  function closeDialog() {
    if (capturing) {
      CraftMapApi.call("cancel_hotkey_capture");
      setRebindIdle();
    }
    dialog.classList.add("hidden");
    document.removeEventListener("keydown", onEscape, true);
  }

  async function openDialog() {
    errorEl.textContent = "";
    display.textContent = await CraftMapApi.call("get_toggle_key");
    dialog.classList.remove("hidden");
    document.addEventListener("keydown", onEscape, true);
  }

  async function startRebind() {
    if (capturing) return;
    capturing = true;
    errorEl.textContent = "";
    display.textContent = "Press a key...";
    rebindBtn.textContent = "Press a key... (Esc to cancel)";
    rebindBtn.classList.remove("btn-neutral");
    rebindBtn.classList.add("btn-accent");
    await CraftMapApi.call("start_hotkey_capture");
  }

  window.HotkeySettings = {
    async onCaptureResult({ ok, message }) {
      setRebindIdle();
      if (ok) {
        display.textContent = message;
        errorEl.textContent = "";
      } else {
        errorEl.textContent = `Invalid key: ${message}`;
        display.textContent = await CraftMapApi.call("get_toggle_key");
      }
    },
  };

  settingsBtn.addEventListener("click", openDialog);
  closeBtn.addEventListener("click", closeDialog);
  closeBtn2.addEventListener("click", closeDialog);
  rebindBtn.addEventListener("click", startRebind);
  dialog.addEventListener("mousedown", (e) => {
    if (e.target === dialog) closeDialog(); // backdrop click
  });
})();
