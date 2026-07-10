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

from . import config, db, resolver


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

    # ---- recipes (frontend/js/recipe-panel.js) ----

    def get_all_recipes(self):
        return [{"id": rid, "name": name} for rid, name in db.get_all_recipes()]

    def get_recipe_by_name(self, name):
        return db.get_recipe_by_name(name)

    def get_recipe_name(self, recipe_id):
        return db.get_recipe_name(recipe_id)

    def get_recipe_output_name(self, recipe_id):
        return db.get_recipe_output_name(recipe_id)

    def get_recipe_outputs(self, recipe_id):
        return [{"name": n, "qty": q} for n, q in db.get_recipe_outputs(recipe_id)]

    def get_recipe_ingredients(self, recipe_id):
        return [{"name": n, "qty": q} for n, q in db.get_recipe_ingredients(recipe_id)]

    def get_recipe_stations(self, recipe_id):
        return [
            {"station": s, "auto": a, "manual": m}
            for s, a, m in db.get_recipe_stations(recipe_id)
        ]

    def get_all_output_names(self):
        return db.get_all_output_names()

    def get_all_stations(self):
        return db.get_all_stations()

    def get_all_ingredient_options(self):
        """Union of produced items + logged resource names + already-used
        ingredient names, for the ingredient-row autocomplete - mirrors
        overlay.py's Overlay._all_ingredient_options."""
        produced = db.get_all_output_names()
        resource_names = db.distinct_values("resource")
        ingredient_names = db.distinct_ingredient_names()
        return sorted(set(produced + resource_names + ingredient_names), key=str.lower)

    def get_recipes_using_ingredient(self, ingredient_name):
        return [
            {
                "recipe_id": rid,
                "recipe_name": rname,
                "qty": qty,
                "output_name": oname,
                "output_qty": oqty,
            }
            for rid, rname, qty, oname, oqty in db.get_recipes_using_ingredient(
                ingredient_name
            )
        ]

    def save_recipe(self, recipe_id, name, outputs, ingredients, stations):
        """outputs/ingredients: [{name, qty}]; stations: [{station, auto, manual}].
        Returns the recipe id (existing or newly inserted)."""
        outputs_t = [(o["name"], o["qty"]) for o in outputs]
        ingredients_t = [(i["name"], i["qty"]) for i in ingredients]
        stations_t = [(s["station"], s.get("auto"), s.get("manual")) for s in stations]
        return db.save_recipe(recipe_id, name, outputs_t, ingredients_t, stations_t)

    def delete_recipe(self, recipe_id):
        db.delete_recipe(recipe_id)
        return True

    def get_checked_paths(self, recipe_id):
        return list(db.get_checked_paths(recipe_id))

    def set_checked_many(self, recipe_id, path_keys, checked):
        db.set_checked_many(recipe_id, path_keys, checked)
        return True

    def get_alt_prefs(self):
        return db.get_alt_prefs()

    def set_alt_pref(self, ingredient_name, recipe_id):
        db.set_alt_pref(ingredient_name, recipe_id)
        return True

    def get_station_prefs(self):
        return {
            name: {"station": station, "mode": mode}
            for name, (station, mode) in db.get_station_prefs().items()
        }

    def set_station_pref(self, ingredient_name, station, mode="auto"):
        db.set_station_pref(ingredient_name, station, mode)
        return True

    def get_deposits_for_ingredient(self, resource_name):
        return [
            {"sector": sec, "system_name": sysn, "planet": pla, "status": status}
            for sec, sysn, pla, status in db.get_deposits_for_ingredient(resource_name)
        ]

    def get_recipe_breakdown(self, name, qty_needed=1.0, root_recipe_id=None):
        alt_prefs = db.get_alt_prefs()
        station_prefs = db.get_station_prefs()
        return resolver.resolve_recipe_tree(
            name,
            qty_needed=qty_needed,
            _root_recipe_id=root_recipe_id,
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
        )

    # How many levels of the tree get resolved (and sent across the
    # pywebview bridge) up front. Depth 0 is the root itself, so this
    # covers the root plus 2 more levels - enough that expanding a couple
    # of levels feels instant before another fetch is needed, without
    # paying to resolve (and transmit) a potentially ~100-node tree when
    # almost all of it starts collapsed and may never be looked at.
    _INITIAL_RESOLVE_DEPTH = 2

    def get_breakdown_view(self, recipe_id, qty_needed=1.0):
        """Everything frontend/js/recipe-panel.js needs for one breakdown/
        totals render, in a single round-trip - each js_api call is a real
        cross-process IPC hop in this pywebview/pythonnet setup, and the
        three separate calls this replaces (get_recipe_output_name,
        get_checked_paths, get_recipe_breakdown) were adding up to a
        noticeably laggy re-render on every checkbox click. The tree
        itself is depth-limited (see get_recipe_subtree for the rest)."""
        output_name = db.get_recipe_output_name(recipe_id)
        if not output_name:
            return {"output_name": "", "checked": [], "tree": None}
        checked = list(db.get_checked_paths(recipe_id))
        alt_prefs = db.get_alt_prefs()
        station_prefs = db.get_station_prefs()
        tree = resolver.resolve_recipe_tree(
            output_name,
            qty_needed=qty_needed,
            _root_recipe_id=recipe_id,
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            max_depth=self._INITIAL_RESOLVE_DEPTH,
        )
        return {"output_name": output_name, "checked": checked, "tree": tree}

    def get_recipe_subtree(self, name, qty_needed, ancestor_names):
        """Resolve one node's own subtree on demand, for a node that came
        back with truncated: True from get_breakdown_view/get_recipe_subtree
        (see resolve_recipe_tree's max_depth). ancestor_names is this node's
        path_parts (the chain of names above it) - re-seeding _visited from
        it is what keeps cycle detection correct across this otherwise-fresh
        top-level call, exactly as if the whole tree had been resolved in
        one go."""
        alt_prefs = db.get_alt_prefs()
        station_prefs = db.get_station_prefs()
        return resolver.resolve_recipe_tree(
            name,
            qty_needed=qty_needed,
            _visited=frozenset(ancestor_names),
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            max_depth=self._INITIAL_RESOLVE_DEPTH,
        )

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
