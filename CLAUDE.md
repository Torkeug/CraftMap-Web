# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Keep this file current, not just appended-to.** If a change here (an
architecture decision, a data-model field, a pattern described above)
gets superseded or reversed later, correct/update that section in place
rather than leaving it stale and just adding a new note elsewhere - this
file is trusted as current state, not read as a changelog. The same goes
for any future numbered-finding-style investigation doc under
`game_data_extract/` (matching the convention in the sibling `shipbuilder`
repo's `tools/game_logic_notes.md`/`hmd_format_notes.md`) if one gets
started here - a later finding that invalidates an earlier one should
correct it in place, not just get appended after it. This does NOT apply
to `game_data_extract/shipwreck_loot_integration.md`, which is explicitly
a frozen design record by intent (see its own header), or to
`missing_recipes_review.md`, which is a regenerated snapshot, not a
hand-maintained log.

## What this is

**CraftMap** is a Windows desktop overlay that tracks in-game resource deposits and crafting recipes. It sits always-on-top over a game window (borderless mode) and can be toggled visible/hidden via a global hotkey (default: F1, rebindable from the in-app Settings dialog). A separate, independently pinnable Craft Queue window tracks multiple recipes' crafting progress at once.

It is a [pywebview](https://pywebview.flowrl.com/) app: a Python backend (SQLite access, recipe-tree resolution, win32 interop) paired with an HTML/CSS/JS frontend rendered via an embedded WebView2 control (pywebview's `edgechromium` backend, via `pythonnet`/WinForms). This project replaced an earlier tkinter/ttk implementation of the same app - that version is retired; nothing here is tkinter.

## Commands

**Run from source:**
```
python main.py
```
Run as administrator if the global hotkey fails to register.

**Install dependencies:**
```
pip install -r requirements.txt
```

**Build the standalone executable:**
```
build.bat
```
Runs PyInstaller (`--onefile --noconsole`), bundling `frontend/` as data, and produces `CraftMap.exe` in the project root. No manual `--hidden-import` flags are needed - both `pywebview` and `pythonnet` ship their own PyInstaller hooks.

**Run tests:**
```
pip install pytest
python -m pytest tests/
```
`tests/test_recipes.py` covers `backend/resolver.py`'s `resolve_recipe_tree` (ceil-based craft counts, cycle detection, alternate-recipe selection, multi-station/craft-time resolution) - the same test suite the tkinter predecessor had, just importing from `backend/` instead of a single `overlay.py`. `tests/test_api*.py` cover `backend/api.py`'s methods directly (no pywebview/browser involved - instantiate `Api()` against an isolated temp DB/config) and assert every return value survives `json.dumps`, since that's the actual boundary crossed to reach the browser. There is no UI test coverage - manual only (see "Testing this app" below).

## Architecture

```
backend/
  paths.py     # DB_PATH/CONFIG_PATH - resolves relative to this app's own install dir (frozen-vs-script split, see below)
  config.py    # load_config/save_config (config.json)
  db.py        # all deposit/recipe/craft-queue/galaxy/wreck-events SQLite CRUD + init_db()'s schema/migrations
  resolver.py  # resolve_recipe_tree + collect_totals/collect_basic_crafted (pure logic + one DB read)
  api.py       # Api class - the pywebview js_api bridge, thin wrappers over the above
  win32util.py # ctypes Win32 interop: hwnd resolution, click-through, focus-forcing, single-instance mutex
  shipwreck_loot.py  # static shipwreck rare-loot-crate odds (Wrecks tab) - loads game_data_extract/shipwreck_loot.json
  wreck_tracking.py  # subprocess launch/live-snapshot-read helpers for the sibling repo's wreck_tracker.py poller
  wreck_import.py    # imports wreck_tracker.py's JSONL event log into db.wreck_events (see tools/import_wreck_events.py)
frontend/
  index.html          # main window: deposit tracker + recipe panel
  queue.html          # Craft Queue window
  css/theme.css, components.css
  js/
    api.js            # CraftMapApi.call() - wraps pywebview.api.* with try/catch + inline error banner
    drag-resize.js     # DragResize.attach() - dragbar/resize-grip handling + dynamic min-size guard
    dropdown.js         # LiveDropdown - no-grab autocomplete popover
    breakdown-tree.js   # BreakdownTree - shared recipe/queue breakdown-tree renderer + step popup
    deposits.js          # deposit tracker screen
    recipe-panel.js       # recipe panel screen
    queue-panel.js          # Craft Queue window logic
    screens.js                # top-level Resource/Location/Recipe/Queue-tab switch
    settings.js                # hotkey settings dialog (DOM modal)
main.py        # entrypoint: single-instance check, init_db, create both windows, App state machine, hotkey/tray
tools/
  backfill_recipe_metadata.py  # one-off maintenance script enriching resources.db from game_data_extract/
  backfill_galaxy_resources.py # repeatable import of the sibling repo's galaxy-wide dump into galaxy_resources/galaxy_systems/galaxy_poi_landmarks
  import_wreck_events.py       # repeatable import of the sibling repo's wreck_tracker.py event log into wreck_events (also runnable from Api - see backend/wreck_import.py)
game_data_extract/  # game-authoritative recipe/item data snapshots (see its own README.md)
```

### Runtime paths (`backend/paths.py`)

`DB_PATH`/`CONFIG_PATH` resolve to `resources.db`/`config.json` alongside this app's own install directory - anchored on `sys.executable` when frozen (`getattr(sys, "frozen", False)`), or two levels up from `paths.py` itself when running from source. Neither is tracked in git (see `.gitignore`/`NOTICE.md`) - `resources.db` is populated entirely from your own manual entries.

`main.py`'s `frontend/` asset path uses `sys._MEIPASS` when frozen (the documented, version-independent way to locate PyInstaller `--onefile` bundled data - `__file__`'s behavior for a frozen entry script isn't something to rely on) or `__file__`'s own directory otherwise.

### The `Api` bridge (`backend/api.py`)

One `Api` instance, shared by both windows (`js_api=api` passed to both `webview.create_window()` calls in `main.py`), exposed to JS as `window.pywebview.api.*`. Methods are close to 1:1 wrappers around `backend/db.py`/`backend/resolver.py` functions, converting tuples to dicts for JSON-friendliness.

**Critical, easy to regress**: every piece of `Api`'s own internal state must be an underscore-prefixed attribute (`self._overlay_window`, `self._queue_window`, `self._on_quit`, `self._app_ctrl`, etc.), never a plain name. pywebview builds its JS-exposed function list by walking `dir(api_instance)` and recursing into every non-underscore, non-callable attribute (`webview/util.py`'s `get_functions()`). A plain `self.overlay_window = window` attribute makes it recurse into the pywebview `Window` object → its `.native` WinForms `Form` → `.AccessibilityObject.Bounds.Empty` (a static property pythonnet keeps re-wrapping), causing infinite recursion that crashes the app on load. The underscore prefix is pywebview's own documented opt-out.

`Api._app_ctrl` is `main.py`'s `App` instance (set right after both windows are created) - both windows' show/hide/focus/pin state machine *and* the global hotkey/settings-dialog lifecycle live there, not in `Api` itself, since `App` is the only place that also knows the other window's current visibility and already owns the hotkey thread/handle. `Api` methods touching either concern just delegate (`if self._app_ctrl is not None: self._app_ctrl.some_method()`).

**Cross-window pushes**: since the main window and the Craft Queue window are separate documents, a mutation made from one has no way to make the other's DOM notice on its own. The established pattern is `some_window.evaluate_js("window.SomeGlobal && window.SomeGlobal.someMethod(...)")` - see `Api._notify_queue_window_changed` (pushes a queue-window refresh after `add_to_queue`, since that can be called from the recipe panel), `App._set_queue_visible` (pushes the main window's Queue-tab active state), and `App._push_hotkey_result` (pushes a captured hotkey's result into the settings dialog, since capture runs on a background thread, not synchronously inside the triggering `js_api` call).

### Recipe tree resolution (`backend/resolver.py`)

`resolve_recipe_tree` recursively expands a recipe into a tree of `{name, qty, is_recipe, output_qty, recipe_name, children, alts, byproducts, station, auto_craft_seconds, manual_craft_seconds, craft_mode, stations, truncated}` nodes. `math.ceil` for craft counts; cycle detection via `_visited`; `_alt_prefs`/`_station_prefs` override the default recipe/station choice per ingredient name.

`max_depth`/`_depth` cap how many levels get resolved (and sent across the pywebview bridge) up front - a node that would have had children past the cap comes back `truncated: true` with empty `children`, and the frontend fetches that one node's own subtree on demand via `Api.get_recipe_subtree(name, qty, ancestor_names)` when the user actually expands it. **This exists because payload *size*, not call count, is what's expensive over the pywebview/pythonnet bridge** - a handful of small round-trips is cheap; one round trip carrying a ~100-node tree can cost 200-500ms+. Any new feature resolving a whole tree for display should default to this depth-limited + on-demand pattern rather than fetching everything up front. The one deliberate exception is `Api.get_queue_totals_view`, which resolves every queued job's *full* tree server-side specifically so it can aggregate them into a small result *before* crossing the bridge - shipping N full trees across just to flatten them client-side would be exactly the cost this pattern avoids.

`build_occurrence_specs`/`filter_unchecked_occurrences`/`aggregate_item_occurrences` (also in `resolver.py`) flatten a resolved tree into one "occurrence" per descendant node at every tier (raw or crafted, excluding the tree's own root), then merge occurrences by item name - used server-side by the queue's Totals view to build its merged, checked-aware "Option D" view (the same ingredient needed via two different recipes/branches collapses into one row; an item's quantity counts only its still-unchecked occurrences, mirroring `_subtree_remaining_seconds`'s prune-at-checked-node rule). Split into a structural, checked-state-*independent* walk (`build_occurrence_specs` - the expensive part: path_keys and display metadata for every node) and a cheap, checked-state-*dependent* linear filter pass (`filter_unchecked_occurrences`) specifically so `Api._get_totals_job_specs` can cache the former per job (keyed by `(recipe_id, qty, station, mode)`) and only ever re-run the latter on a plain checkbox toggle - see that method's docstring for why caching just the resolved tree wasn't enough on its own. Each merged entry also carries `crafted_names` (its own direct crafted-ingredient names, unioned across every occurrence, mirroring `raw_names`), `is_root_demand` (whether it's ever a *direct* child of some job's own root), and `is_shared` (whether it has 2+ *distinct* `parent_name`s among its occurrences, even if none of those parents is a job root) - `queue-panel.js`'s `insertTotalsSections` uses these to render an actual nested BOM tree rather than a flat list. An item is "promoted" (gets its own guaranteed row) if `is_root_demand` OR `is_shared` - both give a cross-reference a real, findable destination to point at; an item with neither is used by exactly one thing and just nests there directly. `is_root_demand` items are the Crafted section's own top-level rows; `is_shared`-but-not-root-demand items get their own row too, nested one level inside Crafted under a "Shared Components" sub-header (not a third top-level peer next to Crafted/Raw Materials, which would make the reader learn an invisible category just to know where to look). Either way, each promoted item recursively nests its own `crafted_names` lookups beneath it, and a name that recurs under a second parent renders as a cross-reference row (click to jump to the one real row; its own checkbox is scoped to just that parent's `occurrences` - each occurrence also carries `parent_name`/`checked` for exactly this - so checking it off only cascades the slice attributable to that one parent, not the item's every occurrence everywhere) instead of duplicating its whole subtree. The recipe panel's own single-recipe Totals mode instead duplicates the older flatten-only logic in JS (`breakdown-tree.js`'s `collectTotals`/`collectBasicCrafted`), since there it only ever needs to flatten one already-fetched tree, not combine several or track cross-job checked state - both exist as different points on the same "payload size vs. call count" tradeoff.

### Frontend patterns worth knowing

- **DOM popovers, not extra windows**: autocomplete suggestions (`dropdown.js`), the alt-recipe/station picker (`breakdown-tree.js`'s step popup), and the hotkey settings dialog (`settings.js`) are all absolutely-positioned DOM content inside the same window, not separate `webview.create_window()` calls - this inherently satisfies "never grabs OS focus" and avoids any two-topmost-window z-order fight. Each owns its own Escape/outside-click dismiss wiring; there is deliberately no window-level "Escape hides the window" handler for either window (removed - it isn't how the original tkinter app behaved), so a popup's Escape handler only needs to stop itself, not also guard against a conflicting document-level listener. `dropdown.js`'s Escape branch still calls `e.stopPropagation()` since `breakdown-tree.js`'s step-popup Escape and `settings.js`'s dialog Escape are registered on `document` in the *capture* phase (so they'd otherwise fire on the same keypress a dropdown is trying to consume).
- **`DragResize.attach()`** (`drag-resize.js`) is shared by both windows' dragbar/resize-grip. Its resize-min-size guard is *measured*, not hardcoded, but only for HEIGHT: `#app.measuring-min-size` (theme.css) plus matching overrides in components.css temporarily force every normally space-filling `flex:1` pane to its real floor size for one synchronous reflow, so `scrollHeight` reports the current screen's actual minimum height. Applied fresh at the start of every resize-grip drag (screen-dependent - deposits/recipe/queue all need different minimum heights) *and* once at launch (`syncGeometry`, which also corrects and persists an undersized on-launch geometry, e.g. from a stale saved size or the plain hardcoded default). `screens.js` exposes `window.__viewModeReady` (a Promise) so this launch-time measurement can wait for the real saved screen to be applied before measuring - `#recipe-view` starts `display:none` until an async `get_view_mode()` round-trip resolves, and measuring during that window would silently undershoot. WIDTH is *not* derived from content the same way for the main "CraftMap Resources" window: `#type-filter` (js/deposits.js's dynamically-rebuilt resource-type checkboxes) is the one `flex-wrap: wrap` container in the app, and CSS's intrinsic-sizing keywords (`max-content`/`min-content`) get its contribution wrong in opposite, screen-dependent ways when the Resource/Location and Recipe screens share one `#app` - so `#app.resources-app.measuring-min-size` (main window's `#app` carries that extra class; the Craft Queue window's does not) pins width to a fixed 624px instead, matching the recipe view's own real single-line minimum, comfortably fitting the deposits-view content too. The Craft Queue window keeps the original content-derived `max-content` width measurement, since it has only one screen's worth of content.
- **`BreakdownTree.createRenderer()`** (`breakdown-tree.js`) is the shared checkbox-cascade tree renderer + step popup used by both the recipe panel and the Craft Queue window, each with their own instance (separate expand-state/busy-guard) and its own `persistKey` (`"recipe_breakdown"` / `"queue_breakdown"`) so its expand/collapse state (otherwise pure in-memory JS state) survives an app restart via `Api.get_tree_expand_state`/`set_tree_expand_state` (`config.json`-backed, namespaced by `tree_key` the same way `js/deposits.js`'s own `collapsed_nodes` persists its tree) - callers await the returned `ready` promise before their first render, same reasoning as `screens.js`'s `window.__viewModeReady`. `openStepPopup(anchorEl, node, isRoot, onAlt, onStation)` takes caller-supplied callbacks rather than baking in recipe-vs-queue-specific logic - a queued job's root deliberately gets no `onAlt` (a queue job is tied to the specific `recipe_id` it was queued with) and routes station picks to `update_queue_station` instead of a generic `set_station_pref`.
- **Global hotkey capture runs server-side** (`main.py`'s `App._capture_hotkey_worker`), not via browser `keydown`/`keyup` translated into a hotkey-library name - `keyboard.hook()` + `keyboard.get_hotkey_name()` directly, the same library that later re-registers it, guaranteeing round-trip compatibility (including layout-dependent names like `alt+twosuperior`, which a browser-`KeyboardEvent.code`-based capture couldn't reliably reproduce since `.code` is deliberately layout-*independent*). Cancelable via a `capture_id` counter + polling (not `keyboard.read_hotkey()`, whose internal blocking `queue.get()` has no way to be interrupted cleanly).

## Data model

Same shape as the retired tkinter app's, evolved with multi-output/multi-station support and the Craft Queue tables. See `backend/db.py`'s `init_db()` for the authoritative schema (with inline migration comments for every added column/table).

- **`deposits`**: `id, res_type, resource, sector, system_name, planet, status, notes, logged_at`. `status` is one of `Free`/`Claimed`/`Depleted`/`Unknown`. Duplicate detection on exact `(res_type, resource, sector, system_name, planet)`.
- **`recipes`**: `id, name, output_qty, output_name, station, auto_craft_seconds, manual_craft_seconds, game_craft_id`. `output_qty`/`output_name`/`station`/craft-times are the *primary* (first) output/station - `recipe_outputs`/`recipe_stations` hold the full lists.
- **`recipe_ingredients`**: `id, recipe_id, ingredient_name, quantity`.
- **`recipe_outputs`**: `id, recipe_id, item_name, quantity` - a recipe can have multiple outputs (byproducts); the first row is primary.
- **`recipe_stations`**: `id, recipe_id, station, auto_craft_seconds, manual_craft_seconds` - a recipe can be craftable at multiple stations/modes.
- **`recipe_checked`** / **`queue_checked`**: `(recipe_id | queue_id, path_key)` composite PK - persists per-ingredient checkbox state. `path_key` is a `|`-joined chain of ingredient names. `queue_id=0` is a sentinel for the queue Totals view's own aggregate checked-state (no FK enforcement, so this is safe).
- **`recipe_alt_prefs`**: `ingredient_name` (PK) → `recipe_id` - user's preferred alternate recipe per ingredient name.
- **`recipe_station_prefs`**: `ingredient_name` (PK) → `station, mode` - user's preferred station/craft-mode per ingredient name.
- **`craft_queue`**: `id, recipe_id, quantity, station, combine, station_mode` - `add_to_queue` merges into an existing same-recipe-and-station row rather than duplicating. `combine` gates whether a job counts toward the Totals view's combined aggregate.
- **`galaxy_resources`** / **`galaxy_systems`** / **`galaxy_poi_landmarks`**: automated, no-travel galaxy-wide resource/system/POI data from the sibling `spacecraft-memory-research` repo's `dump_galaxy_resources.py`, imported via `tools/backfill_galaxy_resources.py` (`INSERT OR IGNORE`/`INSERT OR REPLACE`, safely re-runnable). Personal/per-Quadrant data, never committed - see that script's own docstring for the full field-by-field derivation.
- **`wreck_events`**: an EVENT LOG (one row per sighting/loot/despawn, not a live-position table - see its own comment in `init_db()` for why), fed by the sibling repo's `wreck_tracker.py` poller via `tools/import_wreck_events.py`/`backend/wreck_import.py`. `id, system_name, planet, resource_id, event_type, x, y, z, observed_at`, `UNIQUE(system_name, planet, resource_id, event_type, observed_at, x, y, z)`. Only ever answers "what have I seen over time" (`db.get_wreck_stats`) - the actual live "what's on this planet right now" position comes from `wreck_tracker.py`'s own overwritten JSON snapshot file, read directly by `Api.get_live_wreck_snapshot` (see `backend/wreck_tracking.py`), never stored in this table.

## Testing this app

There's no automated UI test coverage. When verifying UI changes, actually launch it (`python main.py`) and drive the feature - don't rely on the test suite (which only covers backend logic) to catch UI regressions. Both windows are frameless/topmost/translucent - a manual check after any window-behavior change should cover: click-through-when-unfocused, hotkey toggle/focus-grab, hotkey rebind via Settings, single-instance block, tray show/hide, pin/unpin-survives-hide on the queue window, drag/resize on both windows (including the dynamic min-size guard), and the recipe/queue breakdown tree's checkbox cascade + on-demand subtree expansion.
