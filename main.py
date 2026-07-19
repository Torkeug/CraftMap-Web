"""CraftMap entrypoint.

Creates the main overlay window (deposit tracker + recipe panel) and the
separate always-on-top Craft Queue window, wires frameless/topmost/
translucent, custom drag/resize, click-through-when-unfocused polling
(combined across both windows), global hotkey + tray icon, and the
single-instance mutex.
"""

import json
import os
import queue as pyqueue
import sys
import threading
import time

import webview

from backend import config, db
from backend.api import Api
from backend import win32util

try:
    import keyboard

    HOTKEY_AVAILABLE = True
except ImportError:
    HOTKEY_AVAILABLE = False

try:
    import pystray
    from PIL import Image, ImageDraw

    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

# A frozen PyInstaller --onefile build extracts its bundled data files
# (see build.bat's --add-data "frontend;frontend") to sys._MEIPASS, a
# throwaway temp directory - that's the documented, version-independent way
# to locate them (unlike __file__, whose behavior for the frozen entry
# script isn't something to rely on across PyInstaller versions). Running
# from source, sys._MEIPASS doesn't exist, so __file__'s own directory (the
# real source tree) is used instead. Either way this is a *different*
# concern from backend/paths.py's DB_PATH/CONFIG_PATH, which must NOT
# follow the frozen exe into its temp extraction dir - that data
# intentionally lives in the sibling craftmap/ folder regardless of
# packaging (see paths.py's own frozen handling, anchored on
# sys.executable instead).
_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
_FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")
_INDEX_HTML = os.path.join(_FRONTEND_DIR, "index.html")
_QUEUE_HTML = os.path.join(_FRONTEND_DIR, "queue.html")
_WRECK_TRACKER_HTML = os.path.join(_FRONTEND_DIR, "wreck-tracker.html")

WINDOW_ALPHA = 240  # ~0.94, matches the tkinter app's self.attributes("-alpha", 0.94)


def _make_tray_image():
    """Identical drawing to craftmap/overlay.py's _make_tray_image."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [2, 2, 61, 61], fill=(13, 17, 23, 255), outline=(31, 111, 235, 255), width=3
    )
    draw.ellipse([20, 20, 43, 43], fill=(31, 111, 235, 255))
    draw.arc([8, 30, 55, 46], start=0, end=180, fill=(201, 209, 217, 220), width=2)
    draw.arc([8, 30, 55, 46], start=180, end=360, fill=(201, 209, 217, 90), width=2)
    return img


class _AlreadyRunningApi:
    """Minimal js_api for the "already running" notice window - just enough
    to let its OK button close itself. _window is underscore-prefixed per
    backend/api.py's own rule: a plain attribute holding a pywebview Window
    would make pywebview's dir()-walking function discovery recurse into
    the native WinForms object graph and crash (see that module's
    docstring)."""

    def __init__(self):
        self._window = None

    def close(self):
        # Best-effort: hand focus back to the already-running instance's
        # main window (a separate process - see find_window_by_title's own
        # docstring for why FindWindowW is the only way to reach it) before
        # this dialog goes away, so dismissing it doesn't just drop the user
        # back to the desktop.
        hwnd = win32util.find_window_by_title("CraftMap Resources")
        if hwnd:
            win32util.force_foreground_window(hwnd)
        if self._window is not None:
            self._window.destroy()


_ALREADY_RUNNING_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {
    margin: 0; padding: 0; width: 100%; height: 100%;
    background: #0d1117; color: #c9d1d9;
    font-family: "Segoe UI", "Segoe UI Variable", system-ui, sans-serif;
    font-size: 13px; user-select: none; -webkit-user-select: none;
    overflow: hidden;
  }
  #box {
    box-sizing: border-box;
    width: 100%; height: 100%;
    display: flex; flex-direction: column;
  }
  #header {
    padding: 8px 10px;
    background: #161b22;
    border-bottom: 1px solid #30363d;
    font-size: 12px; font-weight: 600;
  }
  #body {
    flex: 1;
    display: flex; align-items: center;
    padding: 14px 16px;
    line-height: 1.4;
  }
  #buttons {
    display: flex; justify-content: flex-end;
    padding: 0 12px 20px;
  }
  button {
    border: none; border-radius: 4px;
    padding: 5px 14px;
    font-family: inherit; font-size: 11px;
    cursor: pointer; color: white;
    background: #1f6feb;
    outline: none;
  }
  button:hover { filter: brightness(1.1); }
  button:focus { outline: none; box-shadow: none; }
</style>
</head>
<body>
  <div id="box">
    <div id="header">CraftMap</div>
    <div id="body">CraftMap is already running.</div>
    <div id="buttons"><button autofocus onclick="pywebview.api.close()">OK</button></div>
  </div>
</body>
</html>
"""


def _show_already_running_dialog():
    """A second launch while an instance already holds the single-instance
    mutex (see win32util.check_single_instance) needs to tell the user
    something - the build is --noconsole, so a bare print() here is
    silently swallowed. A themed pywebview window (matching theme.css's
    palette) rather than a native MessageBoxW, since the latter can't be
    restyled to match the rest of the app, and pywebview is already how
    every other bit of UI here gets built."""
    dlg_w, dlg_h = 300, 150

    # This process never creates the already-running instance's window (it
    # exits before getting that far), so there's no live geometry to center
    # against here - config.json's window_x/y/w/h (kept current by every
    # drag/resize via Api.save_window_geometry) is the closest available
    # stand-in for "where the main window currently is".
    cfg = config.load_config()
    win_x = cfg.get("window_x", 60)
    win_y = cfg.get("window_y", 60)
    win_w = cfg.get("window_w", 640)
    win_h = cfg.get("window_h", 300)
    dlg_x = int(win_x + (win_w - dlg_w) / 2)
    dlg_y = int(win_y + (win_h - dlg_h) / 2)

    api = _AlreadyRunningApi()
    window = webview.create_window(
        "CraftMap",
        html=_ALREADY_RUNNING_HTML,
        js_api=api,
        width=dlg_w,
        height=dlg_h,
        x=dlg_x,
        y=dlg_y,
        resizable=False,
        frameless=True,
        on_top=True,
        background_color="#0d1117",
    )
    api._window = window  # pylint: disable=protected-access
    webview.start(debug=False)


class App:
    """Owns the two-window visibility/focus/click-through state machine
    that used to live as Overlay + CraftQueuePanel instance attributes in
    craftmap/overlay.py - see toggle()/hide()/sync_input_passthrough()
    (ports of Overlay's same-named methods) and toggle_queue_window()/
    show_queue_window()/hide_queue_window()/on_queue_pin_changed() (ports
    of CraftQueuePanel's show/hide/pin methods, called here instead of on a
    separate panel object since pywebview's Window is much thinner than a
    Tk Toplevel - no reason to wrap it in its own class)."""

    def __init__(self, window, queue_window, api):
        self.window = window
        # None until the queue window is actually needed - see
        # _ensure_queue_window. Starting the app with it already created
        # (even hidden) meant pywebview's hidden=True creation trick
        # (Opacity=0 -> Show() -> Hide() -> Opacity=1, see winforms.py's
        # create_window) ran on every launch where the queue wasn't open,
        # which could paint one real visible frame before the Hide() landed.
        # Not creating the window at all until the user asks for it (or it
        # was open at last quit - see main()) sidesteps that race entirely
        # instead of chasing it after the fact.
        self.queue_window = queue_window
        self.api = api
        self.passthrough = False
        self.queue_passthrough = False
        self.tray_icon = None
        self.hotkey_handle = None
        self.toggle_key = None
        # Guards against a hotkey firing immediately after change_hotkey()
        # re-registers it, while the keys that make up the new combo are
        # still physically held from capturing it - see change_hotkey.
        self.hotkey_suppressed = False
        # Bumped by start_hotkey_capture/cancel_hotkey_capture so an
        # in-flight _capture_hotkey_worker thread can tell it's been
        # superseded/cancelled and should quietly stop instead of applying
        # a stale capture.
        self.hotkey_capture_id = 0
        self.hotkey_capture_lock = threading.Lock()
        self._poll_stop = False
        # pywebview's Window exposes no visibility getter - track it
        # ourselves since we're the only code path calling show()/hide().
        self.visible = True
        # Overwritten right after construction (see main()) to match
        # queue_window's own hidden=/queue_open startup state - starts
        # False here only as the pre-launch default.
        self.queue_visible = False
        self.queue_pinned = bool(config.load_config().get("queue_pinned", False))
        # Mirrors CraftQueuePanel-integration's _queue_panel_was_visible:
        # if the queue was up (unpinned) when the main window last hid,
        # bring it back with the main window rather than leaving it down
        # until the user explicitly reopens it.
        self.queue_was_visible = False
        # Wreck Tracker window (frontend/wreck-tracker.html) - a live
        # flight-HUD-style overlay for the sibling spacecraft-memory-
        # research repo's wreck_tracker.py poller, opened on demand from
        # the Wrecks tab's "Activate Live Tracking" button (see backend/
        # api.py's start_wreck_tracking). Participates in the same hotkey
        # show/hide cascade as the queue window (toggle()/hide() below) -
        # same pin semantics too: hiding the main window hides this one
        # unless pinned, and un-hiding brings it back if it was up and
        # unpinned when the main window last hid.
        self.wreck_tracker_window = None
        self.wreck_tracker_visible = False
        self.wreck_tracker_passthrough = False
        self.wreck_tracker_pinned = bool(config.load_config().get("wreck_tracker_pinned", False))
        self.wreck_tracker_was_visible = False

    # ----- main window -----

    def toggle(self):
        hwnd = win32util.pywebview_hwnd(self.window)
        if not self.visible:
            if (
                self.queue_pinned
                and self.queue_visible
                and not win32util.hwnd_is_foreground(
                    win32util.pywebview_hwnd(self.queue_window)
                )
            ):
                # The pinned queue window is still up on its own with the
                # main window hidden - the first hotkey press should hand
                # it focus, not also unhide the main overlay. A second
                # press (queue now focused, main still hidden) falls
                # through to the deiconify branch below.
                win32util.force_foreground_window(
                    win32util.pywebview_hwnd(self.queue_window)
                )
                self.sync_input_passthrough()
                return
            if (
                self.wreck_tracker_pinned
                and self.wreck_tracker_visible
                and not win32util.hwnd_is_foreground(
                    win32util.pywebview_hwnd(self.wreck_tracker_window)
                )
            ):
                # Same idea as the queue-pinned check above, for the
                # wreck tracker window.
                win32util.force_foreground_window(
                    win32util.pywebview_hwnd(self.wreck_tracker_window)
                )
                self.sync_input_passthrough()
                return
            self.window.show()
            self.visible = True
            win32util.force_foreground_window(hwnd)
            self.sync_input_passthrough()
            if not self.queue_pinned and self.queue_was_visible:
                self._set_queue_visible(True)
                self.queue_window.show()
            if not self.wreck_tracker_pinned and self.wreck_tracker_was_visible:
                self.wreck_tracker_visible = True
                self.wreck_tracker_window.show()
            return

        focused = win32util.hwnd_is_foreground(hwnd)
        if not focused and self.queue_visible:
            focused = win32util.hwnd_is_foreground(
                win32util.pywebview_hwnd(self.queue_window)
            )
        if not focused and self.wreck_tracker_visible:
            focused = win32util.hwnd_is_foreground(
                win32util.pywebview_hwnd(self.wreck_tracker_window)
            )
        if not focused:
            # Visible but click-through (unfocused) - the hotkey's job here
            # is to hand focus back, not hide a window the user can still see.
            win32util.force_foreground_window(hwnd)
            self.sync_input_passthrough()
            return

        self.hide()

    def hide(self):
        self.window.hide()
        self.visible = False
        if self.queue_visible:
            self.queue_was_visible = True
            if not self.queue_pinned:
                self.queue_window.hide()
                self._set_queue_visible(False)
        if self.wreck_tracker_visible:
            self.wreck_tracker_was_visible = True
            if not self.wreck_tracker_pinned:
                self.wreck_tracker_window.hide()
                self.wreck_tracker_visible = False
        self.sync_input_passthrough()

    def sync_input_passthrough(self):
        # Focusing any tracked window counts as the whole app being
        # focused, so all of them toggle click-through together - matches
        # craftmap/overlay.py's Overlay._sync_all_input_passthrough.
        hwnd = win32util.pywebview_hwnd(self.window)
        focused = win32util.hwnd_is_foreground(hwnd)
        if not focused and self.queue_visible:
            focused = win32util.hwnd_is_foreground(
                win32util.pywebview_hwnd(self.queue_window)
            )
        if not focused and self.wreck_tracker_visible:
            focused = win32util.hwnd_is_foreground(
                win32util.pywebview_hwnd(self.wreck_tracker_window)
            )

        if self.visible and self.passthrough != (not focused):
            self.passthrough = not focused
            win32util.set_click_through(hwnd, self.passthrough)

        if self.queue_visible and self.queue_passthrough != (not focused):
            self.queue_passthrough = not focused
            win32util.set_click_through(
                win32util.pywebview_hwnd(self.queue_window), self.queue_passthrough
            )

        if self.wreck_tracker_visible and self.wreck_tracker_passthrough != (not focused):
            self.wreck_tracker_passthrough = not focused
            win32util.set_click_through(
                win32util.pywebview_hwnd(self.wreck_tracker_window), self.wreck_tracker_passthrough
            )

    def poll_input_passthrough(self):
        while not self._poll_stop:
            try:
                self.sync_input_passthrough()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            time.sleep(0.25)

    # ----- craft queue window (see backend/api.py's toggle_queue_window/
    # show_queue_window/hide_queue_window/toggle_queue_pin, which delegate
    # here via Api._app_ctrl) -----

    def _set_queue_visible(self, value):
        self.queue_visible = value
        try:
            # Keeps the main window's Queue tab button in sync - it can't
            # see these transitions on its own, since the queue window can
            # also be shown/hidden from its own X button, the pin toggle,
            # or the global hotkey cascading both windows together.
            state = "true" if value else "false"
            self.window.evaluate_js(f"window.QueueTab && window.QueueTab.setActive({state})")
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _ensure_queue_window(self):
        """Creates the Craft Queue window on first use. Safe to call from
        any background thread - which every caller here already is (js_api
        calls each run on their own throwaway thread, see pywebview's
        util.js_bridge_call; the tray icon menu callback runs on pystray's
        own icon thread) - webview.create_window() only creates immediately
        when called off the main thread with the GUI already started
        (see webview/__init__.py's create_window), and winforms.py's own
        create_window Invokes the actual Form creation onto the real UI
        thread regardless of which thread called it."""
        if self.queue_window is not None:
            return
        _create_queue_window(self)

    def toggle_queue_window(self):
        if not self.queue_visible:
            self._ensure_queue_window()
            self.queue_window.show()
            self._set_queue_visible(True)
        else:
            self.queue_window.hide()
            self._set_queue_visible(False)
        self.sync_input_passthrough()

    def show_queue_window(self):
        if not self.queue_visible:
            self._ensure_queue_window()
            self.queue_window.show()
            self._set_queue_visible(True)
            self.sync_input_passthrough()

    def hide_queue_window(self):
        """X-button hide."""
        if self.queue_visible:
            self.queue_window.hide()
            self._set_queue_visible(False)
            self.sync_input_passthrough()

    def on_queue_pin_changed(self, pinned):
        self.queue_pinned = pinned
        if not pinned and not self.visible:
            self.hide_queue_window()

    # ----- wreck tracker window (see backend/api.py's
    # show_wreck_tracker_window/hide_wreck_tracker_window/
    # toggle_wreck_tracker_pin, which delegate here via Api._app_ctrl) -----

    def _ensure_wreck_tracker_window(self):
        """Creates the Wreck Tracker window on first use - same lazy-
        creation rationale as _ensure_queue_window (thread-safety notes
        there apply here unchanged: this can be called from a js_api
        call's own throwaway thread)."""
        if self.wreck_tracker_window is not None:
            return
        _create_wreck_tracker_window(self)

    def show_wreck_tracker_window(self):
        if not self.wreck_tracker_visible:
            self._ensure_wreck_tracker_window()
            self.wreck_tracker_window.show()
            self.wreck_tracker_visible = True
            self.sync_input_passthrough()

    def hide_wreck_tracker_window(self):
        """X-button hide."""
        if self.wreck_tracker_visible:
            self.wreck_tracker_window.hide()
            self.wreck_tracker_visible = False
            self.sync_input_passthrough()

    def on_wreck_tracker_pin_changed(self, pinned):
        self.wreck_tracker_pinned = pinned
        if not pinned and not self.visible:
            self.hide_wreck_tracker_window()

    # ----- global hotkey / settings dialog (see backend/api.py's
    # start_hotkey_capture/cancel_hotkey_capture/get_toggle_key, which
    # delegate here via Api._app_ctrl) -----

    def _on_hotkey(self):
        if self.hotkey_suppressed:
            return
        # Never call self.toggle() directly from here: it runs
        # win32util.force_foreground_window's AttachThreadInput dance, and
        # doing that *inside* keyboard's own low-level hook thread (the
        # thread actively processing this very hotkey's key events) can
        # corrupt modifier-key state system-wide - this was the actual
        # cause of Alt getting reported as stuck down elsewhere after using
        # the toggle hotkey. The tkinter app avoided this the same way,
        # marshalling onto its own main thread via self.after(0, self.toggle)
        # instead of running toggle() on the hook thread - here that means
        # handing off to a plain throwaway thread instead.
        threading.Thread(target=self.toggle, daemon=True).start()

    def register_hotkey(self):
        if HOTKEY_AVAILABLE and self.toggle_key:
            self.hotkey_handle = keyboard.add_hotkey(self.toggle_key, self._on_hotkey)

    def unregister_hotkey(self):
        if HOTKEY_AVAILABLE and self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            self.hotkey_handle = None

    def change_hotkey(self, new_key):
        """Re-register the global hotkey and persist to config. Returns
        (ok, message) - message is the new key on success, an error
        description on failure. Mirrors craftmap/overlay.py's Overlay.
        change_hotkey."""
        self.unregister_hotkey()
        if HOTKEY_AVAILABLE:
            try:
                self.hotkey_handle = keyboard.add_hotkey(new_key, self._on_hotkey)
            except (ValueError, ImportError) as exc:
                # Malformed/unsupported combo - restore the previous
                # binding rather than leaving the app with none at all.
                self.register_hotkey()
                return False, str(exc)
            # The keys making up new_key are still physically held right
            # now (the user just pressed them to capture this combo) - the
            # keyboard library can treat that as an immediate trigger the
            # instant it's registered, firing toggle() and stealing OS
            # focus right back out from under the settings dialog that's
            # still open. Ignore hotkey fires for a short guard window
            # after every rebind - mirrors the tkinter app's identical
            # _hotkey_suppressed guard.
            self.hotkey_suppressed = True

            def _clear_suppress():
                time.sleep(0.5)
                self.hotkey_suppressed = False

            threading.Thread(target=_clear_suppress, daemon=True).start()
        self.toggle_key = new_key
        cfg = config.load_config()
        cfg["toggle_key"] = new_key
        config.save_config(cfg)
        return True, new_key

    def start_hotkey_capture(self):
        """Begin listening for the next key combo on a background thread;
        the settings dialog is told the result via evaluate_js (see
        _push_hotkey_result) once the user releases the final (non-
        modifier) key. Reuses the keyboard library's own event capture and
        get_hotkey_name formatting instead of reimplementing a browser-
        keyevent-to-hotkey-name mapping table client-side, which would need
        its own translation table with no guarantee of matching quirky key
        names already in real use (config.json's "alt+twosuperior")."""
        if not HOTKEY_AVAILABLE:
            return False
        with self.hotkey_capture_lock:
            self.hotkey_capture_id += 1
            capture_id = self.hotkey_capture_id
        # Don't let the CURRENT hotkey fire mid-capture - an easy edge case
        # (rebinding onto the same combo, or just habit) would otherwise
        # show/focus the main window and bury the settings dialog under it,
        # mirroring the tkinter dialog's _start_listening.
        self.unregister_hotkey()
        threading.Thread(
            target=self._capture_hotkey_worker, args=(capture_id,), daemon=True
        ).start()
        return True

    def cancel_hotkey_capture(self):
        with self.hotkey_capture_lock:
            self.hotkey_capture_id += 1  # stale-marks any in-flight worker
        self.register_hotkey()  # restore the (unchanged) hotkey removed above

    def _capture_hotkey_worker(self, capture_id):
        result_q = pyqueue.Queue()
        hooked = keyboard.hook(result_q.put, suppress=True)
        pressed_names = []
        try:
            while True:
                with self.hotkey_capture_lock:
                    if self.hotkey_capture_id != capture_id:
                        return  # cancelled, or superseded by a newer capture
                try:
                    event = result_q.get(timeout=0.1)
                except pyqueue.Empty:
                    continue
                if event.event_type == keyboard.KEY_DOWN:
                    if event.name not in pressed_names:
                        pressed_names.append(event.name)
                elif event.event_type == keyboard.KEY_UP:
                    if keyboard.is_modifier(event.name):
                        # Releasing a held modifier without committing to a
                        # final key shouldn't finalize the combo - just stop
                        # tracking it and keep listening, mirroring the
                        # tkinter dialog's _on_key_release.
                        if event.name in pressed_names:
                            pressed_names.remove(event.name)
                        continue
                    combo = (
                        keyboard.get_hotkey_name(pressed_names)
                        if pressed_names
                        else event.name
                    )
                    with self.hotkey_capture_lock:
                        if self.hotkey_capture_id != capture_id:
                            return  # cancelled while finishing up
                    ok, message = self.change_hotkey(combo)
                    self._push_hotkey_result(ok, message)
                    return
        finally:
            keyboard.unhook(hooked)

    def _push_hotkey_result(self, ok, message):
        try:
            payload = json.dumps({"ok": ok, "message": message})
            self.window.evaluate_js(
                f"window.HotkeySettings && window.HotkeySettings.onCaptureResult({payload})"
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # ----- lifecycle -----

    def quit_app(self):
        self._poll_stop = True
        self.unregister_hotkey()
        if self.tray_icon is not None:
            self.tray_icon.stop()
        # Persist whether the queue window was open so the next launch can
        # recreate and show it up front (see main()'s queue_open) instead of
        # leaving the user to reopen it - the common case, not having it
        # open, now skips creating the window at all (see
        # _ensure_queue_window) rather than creating it hidden.
        cfg = config.load_config()
        cfg["queue_open"] = self.queue_visible
        config.save_config(cfg)


def _create_queue_window(app):
    """Creates the Craft Queue window - either up front in main() when
    queue_open was persisted True by the last quit_app, or lazily via
    App._ensure_queue_window the first time the user actually opens it in
    this session. Always created plainly visible (no hidden=True) since by
    construction it's only ever called right before the window is wanted:
    at startup, queue_open being True means it should show immediately, and
    on demand it's about to be .show()n anyway."""
    cfg = config.load_config()
    qx, qy = cfg.get("queue_x", 400), cfg.get("queue_y", 60)
    qw, qh = cfg.get("queue_w", 320), cfg.get("queue_h", 500)
    queue_window = webview.create_window(
        "Craft Queue",
        url=_QUEUE_HTML,
        js_api=app.api,
        x=qx,
        y=qy,
        width=qw,
        height=qh,
        min_size=(320, 380),
        frameless=True,
        on_top=True,
        resizable=True,
        background_color="#0d1117",
        easy_drag=False,
    )
    app.queue_window = queue_window
    # Underscore-prefixed: see backend/api.py's module docstring.
    app.api._queue_window = queue_window  # pylint: disable=protected-access

    def on_queue_loaded():
        win32util.set_window_alpha(win32util.pywebview_hwnd(queue_window), WINDOW_ALPHA)

    queue_window.events.loaded += on_queue_loaded
    return queue_window


def _create_wreck_tracker_window(app):
    """Creates the Wreck Tracker window - always on first actual use (see
    App._ensure_wreck_tracker_window), never restored at startup the way
    a persisted queue_open can (this window's open state isn't currently
    persisted across app restarts - see App.quit_app, which only
    persists queue_open)."""
    cfg = config.load_config()
    wx, wy = cfg.get("wreck_tracker_x", 460), cfg.get("wreck_tracker_y", 60)
    ww, wh = cfg.get("wreck_tracker_w", 340), cfg.get("wreck_tracker_h", 86)
    wreck_tracker_window = webview.create_window(
        "Wreck Tracker",
        url=_WRECK_TRACKER_HTML,
        js_api=app.api,
        x=wx,
        y=wy,
        width=ww,
        height=wh,
        min_size=(260, 70),
        frameless=True,
        on_top=True,
        resizable=True,
        background_color="#0d1117",
        easy_drag=False,
    )
    app.wreck_tracker_window = wreck_tracker_window
    # Underscore-prefixed: see backend/api.py's module docstring.
    app.api._wreck_tracker_window = wreck_tracker_window  # pylint: disable=protected-access

    def on_wreck_tracker_loaded():
        win32util.set_window_alpha(win32util.pywebview_hwnd(wreck_tracker_window), WINDOW_ALPHA)

    wreck_tracker_window.events.loaded += on_wreck_tracker_loaded
    return wreck_tracker_window


def main():
    if not win32util.check_single_instance():
        _show_already_running_dialog()
        return

    db.init_db()
    cfg = config.load_config()
    toggle_key = cfg.get("toggle_key", "F1")
    x, y = cfg.get("window_x", 60), cfg.get("window_y", 60)
    w, h = cfg.get("window_w", 640), cfg.get("window_h", 300)
    queue_open = cfg.get("queue_open", False)

    api = Api()
    window = webview.create_window(
        "CraftMap Resources",
        url=_INDEX_HTML,
        js_api=api,
        x=x,
        y=y,
        width=w,
        height=h,
        min_size=(320, 200),
        frameless=True,
        on_top=True,
        resizable=True,
        # Matches theme.css's --bg (#0d1117): the newly-exposed area during
        # a grow-resize briefly shows this color before WebView2's
        # compositor catches up and paints the real page, so the default
        # white flashes at the border unless it's overridden here.
        background_color="#0d1117",
        # pywebview's own built-in drag-anywhere behavior for frameless
        # windows (defaults to True!) - runs independently of and on top
        # of frontend/js/drag-resize.js's own #dragbar-scoped dragging,
        # so leaving it enabled meant clicking ANYWHERE in the window
        # dragged it, and dragging from the title bar specifically had
        # two separate drag mechanisms fighting each other at once.
        easy_drag=False,
    )
    # Underscore-prefixed: pywebview builds its JS-exposed function list by
    # walking dir(api) and recursing into every non-underscore, non-callable
    # attribute (see backend/api.py's module docstring) - a plain attribute
    # here would make it recurse into the Window/.native object graph and
    # crash on a pythonnet reflection cycle.
    api._overlay_window = window  # pylint: disable=protected-access

    app = App(window, None, api)
    app.queue_visible = queue_open
    api._on_quit = app.quit_app  # pylint: disable=protected-access
    api._app_ctrl = app  # pylint: disable=protected-access

    if queue_open:
        # Restoring last session's open queue window - still runs before
        # webview.start(), so this just registers it into pywebview's own
        # windows list; it's actually created once the main window's
        # `shown` event fires (see webview/__init__.py's start()/
        # _create_children), same as it always was pre-start().
        _create_queue_window(app)

    def on_loaded():
        hwnd = win32util.pywebview_hwnd(window)
        win32util.set_window_alpha(hwnd, WINDOW_ALPHA)
        threading.Thread(target=app.poll_input_passthrough, daemon=True).start()

        if queue_open:
            # Restoring queue_open (see above) sets app.queue_visible
            # directly rather than through _set_queue_visible, since that
            # happens before this window has loaded and could evaluate_js
            # into a page that isn't there yet - push the Queue tab's
            # button state now that it safely can.
            app._set_queue_visible(True)  # pylint: disable=protected-access

        if HOTKEY_AVAILABLE:
            app.toggle_key = toggle_key
            app.register_hotkey()
        else:
            print("NOTE: 'keyboard' module not found, global hotkey disabled.")

        if PYSTRAY_AVAILABLE:
            menu = pystray.Menu(
                pystray.MenuItem("Show / Hide", lambda: app.toggle(), default=True),
                pystray.MenuItem(
                    "Craft Queue", lambda: app.toggle_queue_window()
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", lambda: api.quit_app()),
            )
            icon = pystray.Icon("CraftMap", _make_tray_image(), "CraftMap", menu)
            app.tray_icon = icon
            threading.Thread(target=icon.run, daemon=True).start()

    window.events.loaded += on_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    main()
