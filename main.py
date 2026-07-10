"""CraftMap-Web entrypoint.

Milestone 2 scope: single frameless/topmost/translucent window, custom
drag/resize, click-through-when-unfocused polling, global hotkey + tray
icon toggling visibility, single-instance mutex. Real screens (deposit
tracker, recipe panel, Craft Queue) land in later milestones.
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
    """Owns the window-visibility/focus/click-through state machine that
    used to live as Overlay instance attributes - see toggle()/_sync_
    input_passthrough(), direct ports of the tkinter app's same-named
    methods, minus the (not yet built) queue-panel-aware branches."""

    def __init__(self, window, api):
        self.window = window
        self.api = api
        self.passthrough = False
        self.tray_icon = None
        self.hotkey_handle = None
        self._poll_stop = False
        # pywebview's Window exposes no visibility getter (no `.hidden`,
        # and events.shown has no matching "hidden" counterpart for
        # .hide()) - track it ourselves since we're the only code path
        # calling show()/hide() in the first place.
        self.visible = True

    def toggle(self):
        hwnd = win32util.pywebview_hwnd(self.window)
        if not self.visible:
            self.window.show()
            self.visible = True
            win32util.force_foreground_window(hwnd)
            self.sync_input_passthrough()
            return
        if not win32util.hwnd_is_foreground(hwnd):
            win32util.force_foreground_window(hwnd)
            self.sync_input_passthrough()
            return
        self.window.hide()
        self.visible = False

    def sync_input_passthrough(self):
        hwnd = win32util.pywebview_hwnd(self.window)
        focused = win32util.hwnd_is_foreground(hwnd)
        if self.visible:
            if self.passthrough != (not focused):
                self.passthrough = not focused
                win32util.set_click_through(hwnd, self.passthrough)

    def poll_input_passthrough(self):
        while not self._poll_stop:
            try:
                self.sync_input_passthrough()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            time.sleep(0.25)

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

    app = App(window, api)
    api._on_quit = app.quit_app  # pylint: disable=protected-access

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
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", lambda: api.quit_app()),
            )
            icon = pystray.Icon("CraftMapWeb", _make_tray_image(), "CraftMap-Web", menu)
            app.tray_icon = icon
            threading.Thread(target=icon.run, daemon=True).start()

    window.events.loaded += on_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    main()
