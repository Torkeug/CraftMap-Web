"""CraftMap-Web entrypoint.

Creates the main overlay window (deposit tracker + recipe panel) and the
separate always-on-top Craft Queue window, wires frameless/topmost/
translucent, custom drag/resize, click-through-when-unfocused polling
(combined across both windows), global hotkey + tray icon, and the
single-instance mutex.
"""

import os
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

_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
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
        self._poll_stop = False
        # pywebview's Window exposes no visibility getter - track it
        # ourselves since we're the only code path calling show()/hide().
        self.visible = True
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

    def poll_input_passthrough(self):
        while not self._poll_stop:
            try:
                self.sync_input_passthrough()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            time.sleep(0.25)

    # ----- craft queue window (see backend/api.py's toggle_queue_window/
    # show_queue_window/hide_queue_window/dismiss_queue_window/
    # toggle_queue_pin, which delegate here via Api._queue_ctrl) -----

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

    # ----- lifecycle -----

    def quit_app(self):
        self._poll_stop = True
        if HOTKEY_AVAILABLE and self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        if self.tray_icon is not None:
            self.tray_icon.stop()


def main():
    if not win32util.check_single_instance():
        print("CraftMap-Web is already running.")
        return

    db.init_db()
    cfg = config.load_config()
    toggle_key = cfg.get("toggle_key", "F1")
    x, y = cfg.get("window_x", 60), cfg.get("window_y", 60)
    w, h = cfg.get("window_w", 640), cfg.get("window_h", 300)
    qx, qy = cfg.get("queue_x", 400), cfg.get("queue_y", 60)
    qw, qh = cfg.get("queue_w", 320), cfg.get("queue_h", 500)

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
        # Starts hidden regardless of last session's pin/visibility state -
        # CraftQueuePanel in the tkinter app is lazily created on first use
        # too (never auto-restored on startup), so this keeps the same
        # "opt in each session" behavior rather than adding a new one.
        hidden=True,
    )
    # Underscore-prefixed: pywebview builds its JS-exposed function list by
    # walking dir(api) and recursing into every non-underscore, non-callable
    # attribute (see backend/api.py's module docstring) - a plain attribute
    # here would make it recurse into the Window/.native object graph and
    # crash on a pythonnet reflection cycle.
    api._overlay_window = window  # pylint: disable=protected-access
    api._queue_window = queue_window  # pylint: disable=protected-access

    app = App(window, queue_window, api)
    api._on_quit = app.quit_app  # pylint: disable=protected-access
    api._queue_ctrl = app  # pylint: disable=protected-access

    def on_loaded():
        hwnd = win32util.pywebview_hwnd(window)
        win32util.set_window_alpha(hwnd, WINDOW_ALPHA)
        threading.Thread(target=app.poll_input_passthrough, daemon=True).start()

        if HOTKEY_AVAILABLE:
            # Never call app.toggle() directly from this callback: it runs
            # win32util.force_foreground_window's AttachThreadInput dance,
            # and doing that *inside* keyboard's own low-level hook thread
            # (the thread actively processing this very hotkey's key
            # events) can corrupt modifier-key state system-wide - this
            # was the actual cause of Alt getting reported as stuck down
            # elsewhere after using the toggle hotkey. The tkinter app
            # avoided this the same way, marshalling onto its own main
            # thread via self.after(0, self.toggle) instead of running
            # toggle() on the hook thread - here that means handing off
            # to a plain throwaway thread instead.
            app.hotkey_handle = keyboard.add_hotkey(
                toggle_key,
                lambda: threading.Thread(target=app.toggle, daemon=True).start(),
            )
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
            icon = pystray.Icon("CraftMapWeb", _make_tray_image(), "CraftMap-Web", menu)
            app.tray_icon = icon
            threading.Thread(target=icon.run, daemon=True).start()

    def on_queue_loaded():
        win32util.set_window_alpha(win32util.pywebview_hwnd(queue_window), WINDOW_ALPHA)

    window.events.loaded += on_loaded
    queue_window.events.loaded += on_queue_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    main()
