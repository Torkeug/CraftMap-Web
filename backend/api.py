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

from . import config, db, resolver, shipwreck_loot


class Api:
    def __init__(self):
        # Set by main.py right after webview.create_window() - lets any
        # method push a refresh into the other window once it exists
        # (e.g. "add to queue" pushing into the queue window).
        self._overlay_window = None
        self._queue_window = None
        # Called by main.py's quit_app to stop the hotkey thread / tray
        # icon / click-through poll loop before the process exits.
        self._on_quit = None
        # main.py's App instance - both the queue window's show/hide/focus
        # state machine (toggle_queue_window/hide_queue_window/dismiss_
        # queue_window/on_queue_pin_changed) and the global hotkey/settings
        # dialog (start_hotkey_capture/cancel_hotkey_capture/change_hotkey)
        # have to live there, not here: App is the only place that also
        # knows the *main* window's current visibility (needed for
        # "unpinning while the main window is hidden hides the queue too",
        # mirroring craftmap/overlay.py's CraftQueuePanel._toggle_pin) and
        # already owns the hotkey thread/handle.
        self._app_ctrl = None
        # Per-job cache of build_occurrence_specs's flattened, checked-
        # state-independent structural walk, for the Totals view - see
        # _get_totals_job_specs.
        # {queue_id: ((recipe_id, qty, station, mode), specs)}.
        self._totals_specs_cache = {}

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

    # A breakdown tree's expand/collapse state (frontend/js/breakdown-
    # tree.js's rootOpen/openNodeKeys) is otherwise pure in-memory JS state
    # that resets on every app restart, unlike the deposit tree's
    # collapsed_nodes above - `tree_key` namespaces this the same way
    # across the recipe panel's tree and the Craft Queue's tree (each its
    # own BreakdownTree.createRenderer instance, see their own `persistKey`
    # constants) so their keys - which can otherwise collide, e.g. both
    # trees using a bare ingredient name as a path_key - never mix.
    def get_tree_expand_state(self, tree_key):
        return config.load_config().get("tree_expand_state", {}).get(
            tree_key, {"root_open": True, "open_keys": []}
        )

    def set_tree_expand_state(self, tree_key, state):
        cfg = config.load_config()
        cfg.setdefault("tree_expand_state", {})[tree_key] = state
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
                "notes": r[6],
            }
            for r in rows
        ]

    def get_deposit(self, row_id):
        row = db.get_deposit(row_id)
        if row is None:
            return None
        res_type, resource, sector, system_name, planet, notes = row
        return {
            "res_type": res_type,
            "resource": resource,
            "sector": sector,
            "system_name": system_name,
            "planet": planet,
            "notes": notes,
        }

    def get_distinct_values(self, column):
        return db.distinct_values(column)

    def get_dropdown_values(self, column, constraints):
        return db.distinct_values_where(column, constraints)

    def add_deposit(self, res_type, resource, sector, system_name, planet, notes):
        if not planet:
            raise ValueError("Planet is required.")
        if db.find_duplicate_deposit(res_type, resource, sector, system_name, planet):
            raise ValueError(
                "An entry with the same type, resource, sector, system and"
                " planet already exists."
            )
        logged_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        db.insert_row(res_type, resource, sector, system_name, planet, notes, logged_at)
        return True

    def update_deposit(
        self, row_id, res_type, resource, sector, system_name, planet, notes
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

    def get_basic_resources(self):
        return db.get_basic_resources()

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

    def get_raw_material_names(self):
        return sorted(db.get_raw_material_names())

    def add_raw_material(self, ingredient_name):
        db.add_raw_material(ingredient_name)
        return True

    def remove_raw_material(self, ingredient_name):
        db.remove_raw_material(ingredient_name)
        return True

    # ---- resource sources (frontend/js/sources.js) ----

    def get_resource_sources(self, resource_name):
        return [
            {"name": n, "concentration": c}
            for n, c in db.get_resource_sources(resource_name)
        ]

    def set_resource_sources(self, resource_name, sources):
        """sources: [{name, concentration}] - concentration may be None."""
        db.set_resource_sources(
            resource_name, [(s["name"], s.get("concentration")) for s in sources]
        )
        return True

    def get_all_resource_source_names(self):
        return db.get_all_resource_source_names()

    def get_resources_with_sources(self):
        return db.get_resources_with_sources()

    def get_deposits_for_ingredient(self, resource_name):
        return [
            {"id": rid, "sector": sec, "system_name": sysn, "planet": pla, "notes": notes}
            for rid, sec, sysn, pla, notes in db.get_deposits_for_ingredient(resource_name)
        ]

    def add_galaxy_note(self, resource_name, sector, system_name, planet, notes):
        """Logs a deposit purely to attach a note to a galaxy-sourced planet
        row (frontend/js/galaxy.js) that isn't logged yet - the same
        deposits-row-exists check that drives that row's LOGGED pin
        (get_deposits_for_ingredient) is what picks this note up afterwards,
        so this is "log this planet" rather than a separate notes-only
        mechanism. res_type is inferred from whatever other deposits of
        this exact resource already use (db.get_res_type_for_resource) -
        every resource name observed so far uses exactly one res_type
        consistently. That precedent lookup only has something to go on
        once this resource has been logged before, though - for a resource
        logged here for the very first time, every "Deposit"-typed name in
        the data (Coal Deposit, Dense Iron Deposit, Coal/Iron/Sandstone (4
        deposits), ...) literally has "deposit" in its own name, and no
        "Resources"-typed one does, so that's the fallback signal; anything
        else falls back further to "Resources" itself (what virtually every
        other Galaxy-tab-tracked resource uses, as opposed to "Plant"/
        "Shipwreck", which are different tracking concepts entirely).
        Leaving it blank would show the row as "(Uncategorized)" in the
        deposit tracker instead of grouping with this resource's other
        entries."""
        if not planet:
            raise ValueError("Planet is required.")
        notes = (notes or "").strip()
        if not notes:
            # Unlike add_deposit (a real logged deposit, note optional),
            # a note is this method's whole reason to exist - an empty one
            # would just silently consume the "+ note" control without
            # leaving anything behind for the LOGGED pin to show.
            raise ValueError("Note is required.")
        res_type = db.get_res_type_for_resource(resource_name)
        if not res_type:
            res_type = "Deposit" if "deposit" in resource_name.lower() else "Resources"
        if db.find_duplicate_deposit(res_type, resource_name, sector, system_name, planet):
            raise ValueError("This planet is already logged for this resource.")
        logged_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        db.insert_row(res_type, resource_name, sector, system_name, planet, notes, logged_at)
        return True

    # ---- galaxy data (frontend/js/galaxy.js) ----

    def get_galaxy_resource_names(self):
        return db.get_galaxy_resource_names()

    def get_galaxy_sources(self, node_name, exclude_asteroids=True):
        """node_name is a node-type name (e.g. "Clay Shell"), same
        namespace as resource_sources' own source_name column - NOT a raw
        material name, since galaxy_resources only ever holds live per-node
        placement data (see tools/backfill_galaxy_resources.py)."""
        return [
            {
                "system_name": system_name,
                "planet": planet,
                "sector": sector,
                "node_count": node_count,
                "density": density,
                "poi_tags": poi_tags,
                "pure_poi": pure_poi,
                "poi_area_density": poi_area_density,
                "is_asteroid": is_asteroid,
                "temperature": temperature,
                "temperature_name": temperature_name,
                "attributes": attributes,
                "attribute_names": attribute_names,
            }
            for (
                system_name, planet, sector, node_count, density, poi_tags,
                pure_poi, poi_area_density, is_asteroid, temperature,
                temperature_name, attributes, attribute_names,
            ) in db.get_galaxy_sources_for_resource(
                node_name, include_asteroids=not exclude_asteroids
            )
        ]

    def get_galaxy_system_names(self):
        """Every system with known position/jump-neighbor data - broader
        than get_galaxy_resource_names' own systems (scoped to whatever
        resource is selected), for the Galaxy sub-tab's "current system"
        autocomplete."""
        return db.get_galaxy_system_names()

    def get_galaxy_hop_distances(self, from_system):
        """{system_name: hop_count} for every system reachable from
        from_system via known jump lanes (see db.get_galaxy_hop_distances'
        own docstring for why hop count, not straight-line distance, is
        the meaningful "closest" metric) - fetched once per "current
        system" pick, not per node-type browsed, since it doesn't depend
        on which resource is currently shown."""
        return db.get_galaxy_hop_distances(from_system)

    def get_recipe_breakdown(self, name, qty_needed=1.0, root_recipe_id=None):
        alt_prefs = db.get_alt_prefs()
        station_prefs = db.get_station_prefs()
        raw_material_names = db.get_raw_material_names()
        return resolver.resolve_recipe_tree(
            name,
            qty_needed=qty_needed,
            _root_recipe_id=root_recipe_id,
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            _raw_material_names=raw_material_names,
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
        raw_material_names = db.get_raw_material_names()
        tree = resolver.resolve_recipe_tree(
            output_name,
            qty_needed=qty_needed,
            _root_recipe_id=recipe_id,
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            _raw_material_names=raw_material_names,
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
        raw_material_names = db.get_raw_material_names()
        return resolver.resolve_recipe_tree(
            name,
            qty_needed=qty_needed,
            _visited=frozenset(ancestor_names),
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            _raw_material_names=raw_material_names,
            max_depth=self._INITIAL_RESOLVE_DEPTH,
        )

    # ---- shipwreck loot (frontend/js/wrecks.js) ----

    def get_wreck_sectors(self):
        return shipwreck_loot.get_all_sectors()

    def get_wreck_items(self):
        return shipwreck_loot.get_all_items()

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

    # ---- craft queue window geometry (frontend/queue.html's own drag bar/
    # resize grip - see frontend/js/drag-resize.js's DragResize.attach) ----

    def get_queue_window_geometry(self):
        w = self._queue_window
        return {"x": w.x, "y": w.y, "width": w.width, "height": w.height}

    def move_queue_window(self, x, y):
        self._queue_window.move(int(x), int(y))

    def resize_queue_window(self, x, y, width, height):
        self._queue_window.move(int(x), int(y))
        self._queue_window.resize(int(width), int(height))

    def save_queue_window_geometry(self, x, y, width, height):
        cfg = config.load_config()
        cfg["queue_x"], cfg["queue_y"] = int(x), int(y)
        cfg["queue_w"], cfg["queue_h"] = int(width), int(height)
        config.save_config(cfg)
        return True

    def get_queue_split(self):
        return config.load_config().get("queue_split", 160)

    def save_queue_split(self, split_px):
        cfg = config.load_config()
        cfg["queue_split"] = int(split_px)
        config.save_config(cfg)
        return True

    # ---- craft queue show/hide/pin (state machine lives on main.py's App -
    # see self._app_ctrl above) ----

    def get_queue_pinned(self):
        return config.load_config().get("queue_pinned", False)

    def toggle_queue_pin(self):
        cfg = config.load_config()
        pinned = not cfg.get("queue_pinned", False)
        cfg["queue_pinned"] = pinned
        config.save_config(cfg)
        if self._app_ctrl is not None:
            self._app_ctrl.on_queue_pin_changed(pinned)
        return pinned

    def toggle_queue_window(self):
        if self._app_ctrl is not None:
            self._app_ctrl.toggle_queue_window()
        return True

    def show_queue_window(self):
        """Always shows (never hides) - used by the recipe panel's
        '+ Queue' button, mirroring craftmap/overlay.py's
        Overlay._add_recipe_to_queue calling .show() rather than toggling."""
        if self._app_ctrl is not None:
            self._app_ctrl.show_queue_window()
        return True

    def hide_queue_window(self):
        """X-button hide."""
        if self._app_ctrl is not None:
            self._app_ctrl.hide_queue_window()
        return True

    # ---- global hotkey / settings dialog (state lives on main.py's App -
    # see self._app_ctrl above) ----

    def get_toggle_key(self):
        if self._app_ctrl is not None and self._app_ctrl.toggle_key:
            return self._app_ctrl.toggle_key
        return config.load_config().get("toggle_key", "F1")

    def start_hotkey_capture(self):
        """Begin listening for the next hotkey combo; the settings dialog
        (frontend/js/settings.js) is told the result asynchronously via
        window.HotkeySettings.onCaptureResult, since the actual keypress
        capture runs on a background thread in main.py's App (blocking a
        js_api call on a real OS-level key-hook wait would be unsafe - see
        App._capture_hotkey_worker)."""
        if self._app_ctrl is not None:
            return self._app_ctrl.start_hotkey_capture()
        return False

    def cancel_hotkey_capture(self):
        if self._app_ctrl is not None:
            self._app_ctrl.cancel_hotkey_capture()
        return True

    # ---- craft queue data (frontend/js/queue-panel.js) ----

    def get_craft_queue(self):
        return [
            {
                "queue_id": qid,
                "recipe_id": rid,
                "recipe_name": rname,
                "output_name": oname,
                "qty": qty,
                "station": station,
                "combine": bool(combine),
                "station_mode": mode,
            }
            for qid, rid, rname, oname, qty, station, combine, mode in db.get_craft_queue()
        ]

    def add_to_queue(self, recipe_id, qty=1.0, station=None):
        queue_id = db.add_to_queue(recipe_id, qty, station or None)
        # frontend/js/recipe-panel.js's '+ Queue' button calls this from
        # index.html, a different window/document than queue.html - unlike
        # every other queue-mutating method here (which queue-panel.js only
        # ever calls on itself and already re-fetches locally afterward),
        # this is the one path where the queue window's own job-list DOM
        # has no way to know a job was just added unless told.
        self._notify_queue_window_changed()
        return queue_id

    def update_queue_qty(self, queue_id, qty):
        db.update_queue_qty(queue_id, qty)
        return True

    def update_queue_station(self, queue_id, station, mode="auto"):
        db.update_queue_station(queue_id, station or None, mode)
        return True

    def update_queue_combine(self, queue_id, combine):
        db.update_queue_combine(queue_id, combine)
        return True

    def remove_from_queue(self, queue_id):
        db.remove_from_queue(queue_id)
        return True

    def get_queue_checked_paths(self, queue_id):
        return list(db.get_queue_checked(queue_id))

    def set_queue_checked_many(self, queue_id, path_keys, checked):
        db.set_queue_checked_many(queue_id, path_keys, checked)
        return True

    def clear_all_queue_checked(self):
        """'Clear done' button - clears every job's checked state."""
        for row in db.get_craft_queue():
            db.clear_queue_checked(row[0])
        return True

    def _notify_queue_window_changed(self):
        """Push a job-list (+ breakdown, if in Totals mode) refresh into
        the queue window's own JS - see frontend/js/queue-panel.js's
        window.QueuePanel.refresh. evaluate_js works even while the queue
        window is hidden (pywebview keeps its page alive, just OS-hidden),
        so the job list is already current by the time the user opens it."""
        if self._queue_window is not None:
            try:
                self._queue_window.evaluate_js(
                    "window.QueuePanel && window.QueuePanel.refresh()"
                )
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def get_queue_breakdown_view(self, queue_id):
        """Everything frontend/js/queue-panel.js needs for one Queue-mode
        breakdown render, in a single round-trip - same rationale and same
        depth-limited/on-demand-subtree scheme as get_breakdown_view (reuses
        get_recipe_subtree, which is queue-agnostic). Reads the job's
        recipe/qty/station straight from craft_queue rather than taking them
        as parameters, since update_queue_qty/update_queue_station already
        persist immediately on commit - there's no ephemeral client-side
        value to thread through the way recipe-panel.js's qty multiplier
        is (that one is deliberately never persisted)."""
        job = next((r for r in db.get_craft_queue() if r[0] == queue_id), None)
        if job is None:
            return {"output_name": "", "checked": [], "tree": None}
        _qid, recipe_id, _rname, output_name, qty, station, _combine, mode = job
        alt_prefs = db.get_alt_prefs()
        station_prefs = db.get_station_prefs()
        raw_material_names = db.get_raw_material_names()
        tree = resolver.resolve_recipe_tree(
            output_name,
            qty_needed=qty,
            _root_recipe_id=recipe_id,
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            _raw_material_names=raw_material_names,
            max_depth=self._INITIAL_RESOLVE_DEPTH,
        )
        self._apply_job_station_override(tree, recipe_id, station, mode)
        checked = list(db.get_queue_checked(queue_id))
        return {"output_name": output_name, "checked": checked, "tree": tree}

    @staticmethod
    def _apply_job_station_override(node, recipe_id, station, mode):
        """A queued job may pin a specific station (distinct from the
        recipe's own default/primary station or any ingredient-level
        _station_prefs) - apply it to the already-resolved root node in
        place, exactly like craftmap/overlay.py's CraftQueuePanel._render_
        breakdown/_render_totals do inline before reading the node's
        timing fields."""
        if not station:
            return
        times = db.get_recipe_station_times(recipe_id, station)
        if not times:
            return
        auto_s, manual_s = times
        node["station"] = station
        node["auto_craft_seconds"], node["manual_craft_seconds"] = auto_s, manual_s
        if mode == "manual" and manual_s:
            node["craft_mode"] = "manual"
        elif mode == "auto" and auto_s:
            node["craft_mode"] = "auto"
        else:
            node["craft_mode"] = "auto" if auto_s else "manual"

    def _get_totals_job_specs(self, job, force_full=False):
        """Resolve one queued job's FULL (non-depth-limited) tree and
        flatten it into resolver.build_occurrence_specs's structural,
        checked-state-INDEPENDENT list, for Totals-view purposes -
        reusing frontend/js/recipe-panel.js's own cached-tree principle
        (see its refreshBreakdown comment): the expensive part is
        resolve_recipe_tree's DB queries + recursive tree construction
        PLUS building every node's path_key/display metadata, none of
        which depend on checked-state - and unlike a plain checkbox
        toggle (which only changes checked-state), none of that needs to
        happen again unless something that actually changes the tree's
        SHAPE occurred. Caching just the resolved tree (an earlier version
        of this method) wasn't enough on its own - the per-render
        aggregation walk over that tree was still the dominant cost even
        with the resolve itself cached; caching the already-flattened
        specs instead means a plain re-render only pays for
        filter_unchecked_occurrences's single cheap linear pass.

        Cache-key is (recipe_id, qty, station, mode) - exactly the
        columns of `job` that feed resolve_recipe_tree/_apply_job_station_
        override - checked against the CURRENT queue row on every call,
        so a job whose qty/station/recipe changed is detected and re-
        resolved automatically, with no invalidation call sites needed
        anywhere else. The one thing this key can't see is a GLOBAL alt-
        recipe/station preference change (recipe_alt_prefs/recipe_
        station_prefs are keyed by ingredient name, not by job) - such a
        change could alter a job's tree without changing its own row at
        all, which is why callers of the Totals view thread through an
        explicit `force_full` the same way recipe-panel.js's own
        refreshBreakdown({forceFull: true}) does after an alt/station
        pick, bypassing the cache for that one call."""
        qid, recipe_id, _rname, output_name, qty, station, _combine, mode = job
        cache_key = (recipe_id, qty, station, mode)
        cached = None if force_full else self._totals_specs_cache.get(qid)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        alt_prefs = db.get_alt_prefs()
        station_prefs = db.get_station_prefs()
        raw_material_names = db.get_raw_material_names()
        node = resolver.resolve_recipe_tree(
            output_name,
            qty_needed=qty,
            _root_recipe_id=recipe_id,
            _alt_prefs=alt_prefs,
            _station_prefs=station_prefs,
            _raw_material_names=raw_material_names,
        )
        self._apply_job_station_override(node, recipe_id, station, mode)
        specs = resolver.build_occurrence_specs(node)
        self._totals_specs_cache[qid] = (cache_key, specs)
        return specs

    def get_queue_totals_view(self, force_full=False):
        """Aggregate every unique item - raw material OR crafted, at ANY
        tier ("Option D": the same ingredient needed by two different
        recipes/branches collapses into one merged row) - across every
        combine-flagged queued job's FULL (non-depth-limited) tree. Each
        item's quantity counts only its still-unchecked occurrences across
        every job/path that needs it - see resolver.build_occurrence_specs/
        filter_unchecked_occurrences/aggregate_item_occurrences for the
        checked-aware aggregation this relies on. Deliberately does this
        aggregation server-side rather than sending N full trees across
        the pywebview bridge for the frontend to flatten (as recipe-
        panel.js's single-recipe Totals mode does with its one already-
        fetched tree) - a queue can easily have several sizeable trees,
        and payload *size* is what's expensive over this bridge, not call
        count (see this module's docstring). The expensive structural walk
        is cached per job - see _get_totals_job_specs - so a plain
        checkbox toggle only pays for the cheap checked-state filter pass,
        not another resolve or tree walk.

        `per_job` here only carries identity (queue_id/recipe_name/qty),
        NOT each job's own aggregated items - unlike the always-visible
        "All Jobs" total above, a job's own "Per Recipe" breakdown is
        genuinely optional detail nobody may ever look at, so computing
        and shipping it eagerly for every job on every call (including
        non-combined jobs, which never even feed the merge above) was pure
        waste. Fetched on demand, only for a job whose own section is
        actually expanded, via get_queue_totals_job_view - same on-demand
        principle as Api.get_recipe_subtree for a truncated node."""
        jobs = db.get_craft_queue()
        live_qids = {row[0] for row in jobs}
        for stale_qid in set(self._totals_specs_cache) - live_qids:
            del self._totals_specs_cache[stale_qid]

        all_occurrences = []
        per_job = []
        combined_count = 0
        for job in jobs:
            qid, _recipe_id, rname, _output_name, qty, _station, combine, _mode = job
            per_job.append({"queue_id": qid, "recipe_name": rname, "qty": qty})
            if not combine:
                continue
            combined_count += 1
            specs = self._get_totals_job_specs(job, force_full=force_full)
            job_checked = db.get_queue_checked(qid)
            job_occurrences = resolver.filter_unchecked_occurrences(specs, job_checked)
            for occ in job_occurrences:
                occ["queue_id"] = qid
            all_occurrences.extend(job_occurrences)

        return {
            "jobs_count": len(jobs),
            "combined_count": combined_count,
            "all_items": resolver.aggregate_item_occurrences(all_occurrences),
            "per_job": per_job,
        }

    def get_queue_totals_job_view(self, queue_id):
        """On-demand per-job Totals breakdown for one queued job - the
        counterpart get_queue_totals_view's own `per_job` entries no longer
        carry eagerly (see its docstring). Reuses _get_totals_job_specs's
        cache, so this is free if get_queue_totals_view already resolved
        this job as part of the combined merge, and only pays for a fresh
        resolve if it didn't (e.g. a non-combined job, never touched by
        the main view)."""
        jobs_by_id = {row[0]: row for row in db.get_craft_queue()}
        job = jobs_by_id.get(queue_id)
        if job is None:
            return {"items": {}}
        specs = self._get_totals_job_specs(job)
        job_checked = db.get_queue_checked(queue_id)
        job_occurrences = resolver.filter_unchecked_occurrences(specs, job_checked)
        for occ in job_occurrences:
            occ["queue_id"] = queue_id
        return {"items": resolver.aggregate_item_occurrences(job_occurrences)}

    def set_totals_item_checked(self, occurrences, checked):
        """Cascade a Totals-mode merged-item row's checkbox click onto
        every real per-job occurrence it represents (`occurrences`: the
        small [{'queue_id', 'path_key'}, ...] list already carried by that
        row's aggregate entry from get_queue_totals_view, round-tripped
        back unmodified) - writes into each affected job's own REAL
        queue_checked rows, the same self+descendants cascade Queue mode's
        own checkbox already does per occurrence, just fanned out across
        every occurrence at once instead of one. Reuses
        _get_totals_job_specs's cache (rather than an unconditional fresh
        resolve+walk) to get each touched job's full path_key list - since
        the frontend always calls get_queue_totals_view again right after
        this to redraw, sharing the cache means each touched job's tree
        gets resolved/walked at most once across the whole click+redraw
        round trip, not twice."""
        by_queue = {}
        for occ in occurrences:
            by_queue.setdefault(occ["queue_id"], []).append(occ["path_key"])
        jobs_by_id = {row[0]: row for row in db.get_craft_queue()}
        for qid, path_keys in by_queue.items():
            job = jobs_by_id.get(qid)
            if job is None:
                continue
            specs = self._get_totals_job_specs(job)
            cascade_keys = [
                s["path_key"]
                for s in specs
                if any(s["path_key"] == p or s["path_key"].startswith(p + "|") for p in path_keys)
            ]
            db.set_queue_checked_many(qid, cascade_keys, checked)
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
        if self._queue_window is not None:
            self._queue_window.destroy()
        if self._overlay_window is not None:
            self._overlay_window.destroy()
        # os._exit, not sys.exit: forcibly terminates the daemon hotkey
        # thread/tray icon thread too, same rationale as the tkinter app's
        # quit_app (a plain exit would otherwise hang on those threads).
        os._exit(0)  # pylint: disable=protected-access
