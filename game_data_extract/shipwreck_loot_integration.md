# Adding a "Wrecks" tab to CraftMap (not yet done)

`shipwreck_loot.json` (this directory) has everything needed to add a
read-only "Wrecks" tab to the app, mirroring the existing **Sources** tab
(`frontend/js/sources.js`) exactly - both are "derived from the game's own
files, not hand-maintained" reference data, not user-editable state like
deposits/recipes. This doc is the plan; nothing below is implemented yet.

## Data already in place

- `shipwreck_loot.json` - regenerate any time with
  `python ../shipbuilder/tools/extract_shipwreck_loot.py` (reads
  `shipbuilder/pak_out/data.cdb`, writes here). See its own `_meta` block for
  the full derivation/mechanism notes.
- Key top-level fields:
  - `sectors`: `{sector_id: {name, exploLevel, maxLootLevel, wreckTierCounts,
    lootLevelProbability, secondaryMaterialPool}}` - per-sector wreck-tier mix
    and reachable loot levels (already capped by that sector's own ceiling).
  - `itemDropOdds.patches` / `itemDropOdds.blueprints`: flat, per-item rows
    already shaped for direct rendering - `{name, level, bestPct, groups:
    [{pct, sectors: [...]}], obtainable}`. `groups` is sectors pre-grouped by
    matching odds (2 significant figures) - this is the more "browse by item"
    shape.
  - `patchPoolByLevel` / `blueprintPoolByLevel`: the raw pools, if a
    per-sector (rather than per-item) view ends up preferred instead.

## Suggested approach: mirror the Sources tab exactly

**Static data, no SQLite table needed** (unlike `resource_sources`, which
exists because `tools/backfill_resource_sources.py` writes into it) -
`shipwreck_loot.json` is small enough (~40 KB) to load directly at app
startup and hold in memory, no DB round-trip required. This avoids a
migration and an extra maintenance script entirely.

1. **Backend** (`backend/db.py` or a new `backend/shipwreck_loot.py`):
   - `load_shipwreck_loot()` - reads and caches
     `game_data_extract/shipwreck_loot.json` once (path resolution needs the
     same frozen-vs-script split `backend/paths.py` already handles for
     `DB_PATH`/`CONFIG_PATH` - `game_data_extract/` would need to ship as
     PyInstaller data alongside `frontend/`, similar to how `frontend/` itself
     is bundled in `build.bat`).
   - Expose two thin getters analogous to `db.get_resource_sources`:
     `get_sector_names()` (for the dropdown) and
     `get_sector_wreck_loot(sector_name)` (returns that sector's slice).

2. **`backend/api.py`**: two `Api` methods, close to 1:1 wrappers, same
   pattern as `get_resource_sources`/`get_resources_with_sources`:
   ```python
   def get_wreck_sectors(self):
       return shipwreck_loot.get_sector_names()

   def get_sector_wreck_loot(self, sector_name):
       return shipwreck_loot.get_sector_wreck_loot(sector_name)
   ```

3. **Frontend**:
   - `index.html`: add `<button class="tab-btn" id="tab-wrecks" data-mode="wrecks">Wrecks</button>`
     next to `tab-sources`, and a `#wrecks-view` div (sector combo + a rows
     area), same structural shape as `#sources-view`. Add
     `<script src="js/wrecks.js"></script>` next to `sources.js`'s script tag.
   - `js/wrecks.js`: copy `sources.js`'s structure - `LiveDropdown` over
     `get_wreck_sectors()`, `loadSector(name)` calling
     `get_sector_wreck_loot(name)` and rendering rows. Given a sector's
     patch/blueprint lists can run to 40-60 entries at the higher-level
     sectors (see `itemDropOdds` - e.g. Jester reaches level 9), consider
     grouping rows by loot level (matching `lootLevelProbability`'s bands)
     with a small header per level showing that level's own odds, rather than
     one flat list - keeps it scannable in CraftMap's small overlay window.
   - `js/screens.js`: add the `wrecks` branch alongside the existing
     `resource`/`location`/`recipe`/`sources` mode handling (show/hide
     `#wrecks-view`, `set_view_mode` call, tab highlight) - follow the
     `sources` branch as the direct template throughout.
   - CSS: reuse `.source-row`/`.recipe-subsection-label`/`.scroll-rows`
     classes from `components.css` rather than introducing a new visual
     language - this data doesn't need its own styling.

## Open questions for whoever picks this up

- **Sector-first vs item-first browsing.** The Sources tab is
  resource-first (you already know what you're looking for). A "Wrecks" tab
  could go either way: sector-first (pick your current sector, see what's
  reachable - matches "I'm here right now, what can I get") or item-first
  (pick a target item, see which sectors/odds - matches "I want X, where do
  I farm it"). `itemDropOdds` is already shaped for the latter;
  `sectors` + `patchPoolByLevel`/`blueprintPoolByLevel` for the former. Could
  offer both via a small toggle, same screen.
- **Precision caveat worth surfacing in the UI**, not just this doc: the
  Patch-vs-Blueprint 50/50 split is an approximation (see `_meta` in the
  JSON) - if this ever gets contradicted by another observed drop the way
  the original 2-level-window bug did, that's the next thing to re-derive
  from `src/logic/Loot.hx:295-317`.
