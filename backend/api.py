"""pywebview JS-API bridge. Thin wrappers over backend.config/db/resolver,
plus the small bits of cross-window session state that used to live as
attributes on the tkinter Overlay/CraftQueuePanel objects.

Exposed to the frontend as window.pywebview.api.* - see frontend/js/api.js
for the JS-side wrapper (try/catch + inline error banner instead of a
modal dialog, so a failed call can't re-introduce the exact focus-stealing
problem the tkinter app's _StepPopup was built to avoid).

All internal state lives in underscore-prefixed attributes. pywebview
builds the JS-exposed function list by walking dir(api_instance) and
recursing into every non-underscore, non-callable attribute (see
webview/util.py's get_functions) - a plain `self.overlay_window = window`
attribute made it recurse straight into the pywebview Window object, into
its .NET-backed .native Form, and into .AccessibilityObject.Bounds.Empty
(a static Rectangle.Empty property that pythonnet keeps re-wrapping),
which is an infinite structural recursion that crashed the app on load/
navigation. The underscore prefix is pywebview's own documented opt-out
of that walk.

Geometry goes through pywebview's own window.x/.y/.width/.height/.move()/
.resize() rather than raw ctypes SetWindowPos - pywebview's WinForms
backend converts logical (CSS) pixels to physical pixels via
GetDpiForWindow before touching Win32, which a raw ctypes call would skip
entirely, causing the window to drift away from the cursor on any
display scaled above 100%.

resize_window also re-asserts an explicit anchor x/y after every resize()
call (see frontend/js/drag-resize.js) rather than trusting resize()'s own
"keep the current position" fix_point logic: pywebview's WinForms window
has AutoScaleMode.Dpi set, which nudges the form's Location asynchronously
(after SetWindowPos returns, not within the call) as a side effect of the
WM_SIZE it triggers. Each next resize() call then reads that already-
nudged Location as "the position to preserve," compounding the drift a
little further every frame - confirmed by logging window.x/.y immediately
before and after resize() (identical every time) versus across
consecutive calls (drifting by almost exactly the accumulated size delta).
"""

import datetime
import os

from . import config, db


class Api:
    def __init__(self):
        # Set by main.py right after webview.create_window() - lets any
        # method push a refresh into the other window once it exists
        # (e.g. Milestone 5's "add to queue" pushing into the queue window).
        self._overlay_window = None
        self._queue_window = None
        # Called by main.py's quit_app to stop the hotkey thread / tray
        # icon / click-through poll loop before the process exits.
        self._on_quit = None

    # ---- config ----

    def get_config(self):
        return config.load_config()

    def save_config(self, cfg):
        config.save_config(cfg)
        return True

    def get_collapsed_nodes(self):
        return config.load_config().get("collapsed_nodes", [])

    def set_collapsed_nodes(self, collapsed_nodes):
        cfg = config.load_config()
        cfg["collapsed_nodes"] = collapsed_nodes
        config.save_config(cfg)
        return True

    def get_view_mode(self):
        return config.load_config().get("view_mode", "resource")

    def set_view_mode(self, mode):
        cfg = config.load_config()
        cfg["view_mode"] = mode
        config.save_config(cfg)
        return True

    # ---- deposits (frontend/js/deposits.js) ----

    def get_deposits(self, search_text="", allowed_types=None, view_mode="resource"):
        order = "location" if view_mode == "location" else "resource"
        rows = db.fetch_all(
            search_text.lower() if search_text else "", allowed_types, order_by=order
        )
        return [
            {
                "id": r[0],
                "res_type": r[1],
                "resource": r[2],
                "sector": r[3],
                "system_name": r[4],
                "planet": r[5],
                "status": r[6],
                "notes": r[7],
            }
            for r in rows
        ]

    def get_deposit(self, row_id):
        row = db.get_deposit(row_id)
        if row is None:
            return None
        res_type, resource, sector, system_name, planet, status, notes = row
        return {
            "res_type": res_type,
            "resource": resource,
            "sector": sector,
            "system_name": system_name,
            "planet": planet,
            "status": status,
            "notes": notes,
        }

    def get_distinct_values(self, column):
        return db.distinct_values(column)

    def get_dropdown_values(self, column, constraints):
        return db.distinct_values_where(column, constraints)

    def add_deposit(
        self, res_type, resource, sector, system_name, planet, status, notes
    ):
        if not planet:
            raise ValueError("Planet is required.")
        if db.find_duplicate_deposit(res_type, resource, sector, system_name, planet):
            raise ValueError(
                "An entry with the same type, resource, sector, system and"
                " planet already exists."
            )
        logged_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        db.insert_row(
            res_type, resource, sector, system_name, planet, status, notes, logged_at
        )
        return True

    def update_deposit(
        self, row_id, res_type, resource, sector, system_name, planet, status, notes
    ):
        if not planet:
            raise ValueError("Planet is required.")
        if db.find_duplicate_deposit(
            res_type, resource, sector, system_name, planet, exclude_id=row_id
        ):
            raise ValueError("Another entry with the same combination already exists.")
        logged_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        db.update_row(
            row_id,
            res_type,
            resource,
            sector,
            system_name,
            planet,
            status,
            notes,
            logged_at,
        )
        return True

    def delete_deposit(self, row_id):
        db.delete_row(row_id)
        return True

    # ---- window geometry (drag/resize - see frontend/js/drag-resize.js) ----

    def get_window_geometry(self):
        w = self._overlay_window
        return {"x": w.x, "y": w.y, "width": w.width, "height": w.height}

    def move_window(self, x, y):
        self._overlay_window.move(int(x), int(y))

    def resize_window(self, x, y, width, height):
        # Move first, then resize: correct any drift accumulated from the
        # previous call's asynchronous AutoScaleMode.Dpi nudge (see module
        # docstring) *before* resize() reads "current position" as its
        # fix_point baseline, so it preserves the corrected position rather
        # than the drifted one. Doing it in the other order raced our own
        # move() against resize()'s own freshly-issued WM_SIZE and dropped
        # the size change entirely.
        self._overlay_window.move(int(x), int(y))
        self._overlay_window.resize(int(width), int(height))

    def save_window_geometry(self, x, y, width, height):
        cfg = config.load_config()
        cfg["window_x"], cfg["window_y"] = int(x), int(y)
        cfg["window_w"], cfg["window_h"] = int(width), int(height)
        config.save_config(cfg)
        return True

    # ---- lifecycle ----

    def quit_app(self):
        if self._on_quit is not None:
            self._on_quit()
        # Close the WinForms window first so WebView2/WinForms run their
        # normal teardown (disposing the CoreWebView2 controller, releasing
        # the DWM-composited surface) before the process disappears.
        # Skipping straight to os._exit() on a layered/topmost/GPU-
        # composited window leaves DWM showing a stale frame for a few
        # seconds until it notices the owning process is gone - .destroy()
        # blocks (via WinForms Invoke) until Close() actually completes, so
        # by the time we reach os._exit() there's nothing left to redraw.
        if self._overlay_window is not None:
            self._overlay_window.destroy()
        # os._exit, not sys.exit: forcibly terminates the daemon hotkey
        # thread/tray icon thread too, same rationale as the tkinter app's
        # quit_app (a plain exit would otherwise hang on those threads).
        os._exit(0)  # pylint: disable=protected-access
