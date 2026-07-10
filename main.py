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


class App:
    """Owns the two-window visibility/focus/click-through state machine
    that used to live as Overlay + CraftQueuePanel instance attributes in
    craftmap/overlay.py - see toggle()/hide()/sync_input_passthrough()
    (ports of Overlay's same-named methods) and toggle_queue_window()/
    show_queue_window()/hide_queue_window()/dismiss_queue_window()/
    on_queue_pin_changed() (ports of CraftQueuePanel's show/hide/pin
    methods, called here instead of on a separate panel object since
    pywebview's Window is much thinner than a Tk Toplevel - no reason to
    wrap it in its own class)."""

    def __init__(self, window, queue_window, api):
        self.window = window
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
            self.window.show()
            self.visible = True
            win32util.force_foreground_window(hwnd)
            self.sync_input_passthrough()
            if not self.queue_pinned and self.queue_was_visible:
                self._set_queue_visible(True)
                self.queue_window.show()
            return

        focused = win32util.hwnd_is_foreground(hwnd)
        if not focused and self.queue_visible:
            focused = win32util.hwnd_is_foreground(
                win32util.pywebview_hwnd(self.queue_window)
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
        self.sync_input_passthrough()

    def sync_input_passthrough(self):
        # Focusing either window counts as the whole app being focused, so
        # both toggle click-through together - matches craftmap/overlay.py's
        # Overlay._sync_all_input_passthrough.
        hwnd = win32util.pywebview_hwnd(self.window)
        focused = win32util.hwnd_is_foreground(hwnd)
        if not focused and self.queue_visible:
            focused = win32util.hwnd_is_foreground(
                win32util.pywebview_hwnd(self.queue_window)
            )

        if self.visible and self.passthrough != (not focused):
            self.passthrough = not focused
            win32util.set_click_through(hwnd, self.passthrough)

        if self.queue_visible and self.queue_passthrough != (not focused):
            self.queue_passthrough = not focused
            win32util.set_click_through(
                win32util.pywebview_hwnd(self.queue_window), self.queue_passthrough
            )

    def reconcile_queue_visibility(self):
        """Self-healing correction for a pywebview/WinForms quirk where the
        queue window's hidden=True startup trick (Opacity=0 -> Show() ->
        Hide() -> Opacity=1 - see main()'s on_queue_shown/on_queue_loaded)
        can leave the native window genuinely visible (accepting clicks,
        eventually painting real content once interacted with) despite
        self.queue_visible being False - observed in practice to survive
        those two reactive hide() calls, likely because Invoke-ing hide()
        that early races the window/WebView2 control's own initialization.
        Rather than chase that race precisely, this compares the real OS
        visibility state against self.queue_visible on every poll tick
        (already running every 0.25s for click-through sync) and corrects
        any drift directly - self-healing regardless of what caused it."""
        hwnd = win32util.pywebview_hwnd(self.queue_window)
        actually_visible = win32util.is_window_visible(hwnd)
        if actually_visible and not self.queue_visible:
            self.queue_window.hide()
        elif self.queue_visible and not actually_visible:
            self.queue_window.show()

    def poll_input_passthrough(self):
        while not self._poll_stop:
            try:
                self.sync_input_passthrough()
                self.reconcile_queue_visibility()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            time.sleep(0.25)

    # ----- craft queue window (see backend/api.py's toggle_queue_window/
    # show_queue_window/hide_queue_window/dismiss_queue_window/
    # toggle_queue_pin, which delegate here via Api._app_ctrl) -----

    def _set_queue_visible(self, value):
        self.queue_visible = value
        try:
            # Keeps the main window's Queue tab button in sync - it can't
            # see these transitions on its own, since the queue window can
            # also be shown/hidden from its own X button, Escape, the pin
            # toggle, or the global hotkey cascading both windows together.
            state = "true" if value else "false"
            self.window.evaluate_js(f"window.QueueTab && window.QueueTab.setActive({state})")
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def toggle_queue_window(self):
        if not self.queue_visible:
            self.queue_window.show()
            self._set_queue_visible(True)
        else:
            self.queue_window.hide()
            self._set_queue_visible(False)
        self.sync_input_passthrough()

    def show_queue_window(self):
        if not self.queue_visible:
            self.queue_window.show()
            self._set_queue_visible(True)
            self.sync_input_passthrough()

    def hide_queue_window(self):
        """Explicit X-button hide - always wins over the pin, unlike
        dismiss_queue_window (Escape)."""
        if self.queue_visible:
            self.queue_window.hide()
            self._set_queue_visible(False)
            self.sync_input_passthrough()

    def dismiss_queue_window(self):
        """Ambient dismiss (Escape) - only hides if not pinned, mirroring
        craftmap/overlay.py's CraftQueuePanel.dismiss."""
        if not self.queue_pinned:
            self.hide_queue_window()

    def on_queue_pin_changed(self, pinned):
        self.queue_pinned = pinned
        if not pinned and not self.visible:
            self.hide_queue_window()

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
        # start it already-shown (see main()'s queue_open) instead of
        # always going through the hidden=True creation trick, which is
        # only needed when the window should actually start hidden.
        cfg = config.load_config()
        cfg["queue_open"] = self.queue_visible
        config.save_config(cfg)


def main():
    if not win32util.check_single_instance():
        print("CraftMap is already running.")
        return

    db.init_db()
    cfg = config.load_config()
    toggle_key = cfg.get("toggle_key", "F1")
    x, y = cfg.get("window_x", 60), cfg.get("window_y", 60)
    w, h = cfg.get("window_w", 640), cfg.get("window_h", 300)
    qx, qy = cfg.get("queue_x", 400), cfg.get("queue_y", 60)
    qw, qh = cfg.get("queue_w", 320), cfg.get("queue_h", 500)
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
    queue_window = webview.create_window(
        "Craft Queue",
        url=_QUEUE_HTML,
        js_api=api,
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
        # Restores last session's open/closed state (queue_open, saved by
        # App.quit_app) rather than always starting hidden. This also
        # sidesteps pywebview's hidden=True creation trick (Opacity=0 ->
        # Show() -> Hide() -> Opacity=1, done to get WebView2 to initialize
        # while staying invisible) for the common case where the window
        # should start visible anyway - that trick raced against Windows'
        # own topmost-window Show() processing (Z-order insertion, DWM
        # composition) closely enough that the window could occasionally
        # end up stuck genuinely visible despite the code's intent, same as
        # the main window above never needs this trick because it's never
        # asked to start hidden. See App.reconcile_queue_visibility for the
        # remaining self-healing safety net on the hidden=True path.
        hidden=not queue_open,
    )
    # Underscore-prefixed: pywebview builds its JS-exposed function list by
    # walking dir(api) and recursing into every non-underscore, non-callable
    # attribute (see backend/api.py's module docstring) - a plain attribute
    # here would make it recurse into the Window/.native object graph and
    # crash on a pythonnet reflection cycle.
    api._overlay_window = window  # pylint: disable=protected-access
    api._queue_window = queue_window  # pylint: disable=protected-access

    app = App(window, queue_window, api)
    app.queue_visible = queue_open
    api._on_quit = app.quit_app  # pylint: disable=protected-access
    api._app_ctrl = app  # pylint: disable=protected-access

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

    def on_queue_shown():
        # Defensive: pywebview's own hidden=True handling (winforms.py's
        # create_window) does Opacity=0 -> Show() -> Hide() -> Opacity=1 to
        # get the window/WebView2 control properly initialized while still
        # nominally hidden - if that Show() ever paints a visible frame
        # before Hide() lands, this re-asserts the hidden state as soon as
        # the native window exists (the `shown` event), rather than waiting
        # on on_queue_loaded below - `loaded` depends on WebView2 finishing
        # page navigation, which can lag well behind window creation, and a
        # visible-but-unloaded queue window (just its background color) sat
        # on screen for that whole gap until this was added.
        if not app.queue_visible:
            queue_window.hide()

    def on_queue_loaded():
        win32util.set_window_alpha(win32util.pywebview_hwnd(queue_window), WINDOW_ALPHA)
        # Same re-assertion as on_queue_shown above, in case anything
        # between `shown` and `loaded` (e.g. WebView2's own navigation-time
        # compositing) made it visible again.
        if not app.queue_visible:
            queue_window.hide()

    window.events.loaded += on_loaded
    queue_window.events.shown += on_queue_shown
    queue_window.events.loaded += on_queue_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    main()
