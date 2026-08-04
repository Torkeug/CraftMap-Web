# Game-extracted crafting data

Extracted directly from the game's own `data.cdb` (`shipbuilder/pak_out/data.cdb`,
Heaps/Haxe CDB sheet format) by
[`shipbuilder/tools/extract_craft_data.py`](../../shipbuilder/tools/extract_craft_data.py).
This is the game's authoritative recipe data — not the hand-entered data currently
in `resources.db`. Nothing here touches `resources.db`; these are plain JSON files
for review before you decide how to merge.

## Files

- **`craft_recipes.json`** — 479 recipes, raw `craft` sheet rows. Fields:
  - `id` — recipe id (not always the same as the output item id)
  - `guid` — stable game-internal id
  - `inputs`: `[{item, qty}, ...]` — ingredient item ids + quantities
  - `outputs`: `[{item, qty}, ...]` — output item ids + quantities. **`qty` is
    omitted (defaults to 1) on 309 of 479 recipes.** 47 recipes have more than
    one output (e.g. smelting a crystal can yield two different ingots).
  - `where` — crafting station id (`Workshop_Smelter`, `Workshop_Atelier`,
    `Workshop_Chemical`, `Workshop_Crystalizer`, `Workshop_Seed`,
    `Workshop_Bottle`, `Workshop_Factory`/`Factory2`, `Workshop_Building`,
    `Workshop_Recycle`, `Workshop_Science`, `Workshop_Uncraftable`, or absent)
  - `category` — one of 26 values (`Craft_RawResource`, `Craft_Modules`,
    `Craft_Parts`, `Craft_Dismantle`, `BaseBuilding`, etc.)
  - `unlockType` — how the recipe is learned; the `craft` sheet's own enum
    column (`typeStr: "5:Permit,Unique_Blueprint,Random_Blueprint,
    Cannot_Unlock,Study,Dismantle,Custo"`): `0`=Permit, `1`=Unique_Blueprint
    (a fixed, non-random source — quest/vendor/location), `2`=Random_Blueprint
    (the only value the shipwreck rare-crate system ever draws from — see
    `shipwreck_loot.json`'s notes and `shipbuilder/tools/game_logic_notes.md`
    Finding 15), `3`=Cannot_Unlock, `4`=Study, `5`=Dismantle, `6`=Custom. A
    recipe can have a `lootLevel` set while still being `unlockType != 2` —
    it will never actually drop from a crate in that case.
    **`unlockType == 0` ("Permit") is commonly summarized as "always known",
    but that's not literally true** — it just means this recipe's unlock
    mechanism *is* a permit, not that any permit actually grants it.
    Confirmed live against `hlboot.dat` (`st.PlayerProgress.isKnownCraft`,
    decompiled): a `Permit`-type recipe only ever shows as known if some
    `permit` sheet row's `unlocks.craft` list references its id — the
    `permit` sheet isn't part of this extract (only `data.cdb` directly has
    it). A handful of recipes have `unlockType: 0` but **no** permit
    anywhere grants them (e.g. `AluminiumIngot_Emerald` — every sibling
    crystal-smelting recipe like `IronIngot_Hematite` has a matching
    `P_HematiteCrystal1`-style permit gated on "have the raw item"; Emerald's
    has none) — these are permanently unreachable in normal play, not
    progression-gated. `tools/backfill_recipe_metadata.py`'s
    `load_unreachable_permit_crafts()` computes this set directly from
    `data.cdb` and excludes them from both recipe enrichment and the missing-
    recipes report.
  - `lootLevel` — progression gating (crate-drop tier; see above for the
    additional `unlockType` gate specific to blueprints)
  - `props` — free-form dict, e.g. `autoPowerCost`, `craftTimeFactor`,
    `manualTime`, `autoTime`
  - `note` — occasional dev comments (e.g. `"replace silicium by chromium at
    some point"`) — these are **known TODOs/inconsistencies from the
    developers themselves**, worth keeping visible rather than "fixing" silently.

- **`items.json`** — `{item_id: {name, type, guid, price, desc}}` for all 585
  items, to resolve the ids used in `inputs`/`outputs` to display names.

- **`item_types.json`** — `{type_id: {name, parent}}`, the item category tree.

- **`item_tags.json`** — `{tag_id: props}`, includes craft-station display
  metadata (`craftAction`, `craftIndex`, `manualCraftTime`, `autoCraftTime`,
  `label`, `color`, `flags`) for tags like `Station`.

- **`craft_values.json`** — per-station economy constants (power cost, price
  decay, etc), keyed by `craftKind` (matches `where` in recipes).

- **`resource_nodes.json`** — 121 raw `resource` sheet rows (asteroid
  clusters, planetary deposits, geysers, crackable shells, shipwrecks, etc -
  this sheet backs `resGen`/`asteroidResGen`/`wreckResGen` generation, so it
  covers every kind of gatherable node), filtered to only those that
  actually encode a material yield. A node's `type` (enum: `Default`,
  `Gravite`, `Node`, `Deposit`, `Shell`, `Geyser`, `Pool`, `ShipWreck`,
  `ShipWreckPart`, `Biological`, `BiologicalRoot`, `Deco`, `Decal`)
  determines which of four shapes that takes:
  - `Node`/`ShipWreckPart`/`BiologicalRoot`: `items`:
    `[{item, kind, proba, qtyMin, qtyMax}, ...]` — item ids yielded when
    gathering this node. `kind` is `0` for the node's primary material
    (its yield is guaranteed each gather, split across kind-0 siblings by
    `proba` weight), `1` for a rarer "rare find" bonus roll gated by the
    node's own `generation.secondaryProba`/`secondaryMax` (e.g.
    `CarbonCluster_Coal`'s primary yield is `Carbon`, but it can also
    rarely turn up a `Diamond`).
  - `Deposit`/`Pool`: `props.depositItem` — a single guaranteed item id,
    auto-drilled by the Extractor building (e.g. `CoalDeposit` →
    `Carbon`, `VitriolDeposit` → `Vitriol`). No randomness, no `items` list.
  - `Geyser`: `props.geyser.fluid` — same idea, passively collected (e.g.
    `MercuryGeyser` → `Mercury`).
  - `Shell`/`ShipWreck`: `props.loot`:
    `[{proba, items: [{item, qtyMin, qtyMax}, ...]}, ...]` — a list of
    bundles; cracking the shell/salvaging the wreck picks ONE bundle
    (weighted by that bundle's own `proba`) and every item in it drops
    together, e.g. `BasaltShell` has a Sandstone+IronNugget bundle and a
    separate Sandstone+TitaniumOre bundle among others.

  Exploration-only markers (`Gravite`/`Default` - scannable points with no
  material yield) and other resource types without a concrete item encoded
  here (`Biological`, `Deco`, `Decal`) are excluded.

- **`shipwreck_loot.json`** — derived (not a raw sheet dump) analysis of
  shipwreck rare-loot crates, regenerated by
  [`shipbuilder/tools/extract_shipwreck_loot.py`](../../shipbuilder/tools/extract_shipwreck_loot.py):
  - `sectors`: which loot levels each sector can reach (capped by
    `sector.props.maxLootLevel`, weighted by that sector's wreck-tier mix in
    `generation.wreckResGen`), plus its secondary-material pool and
    `crateSpawn` (P(a wreck here has a rare loot crate at all) — a full
    crate-*count* distribution, since a single wreck can hold more than
    one).
  - `sectors[*].secondaryItemPool`: a DIFFERENT loot channel from
    `itemDropOdds`/`wreckSiteItemOdds` below (Patch/Blueprint only) — every
    rare crate also always attempts to fill a separate value budget with a
    Material/Manufactured/Luxury-category item, a second generation pass
    independent of the primary Patch/Blueprint roll
    (`secondaryItemTypes==14` on every `ShipWreck_Loot_4..9` row — see
    `game_logic_notes.md` Finding 25 Part B for the full trace, including
    the confirmed flag→`itemType` mapping). Each entry is *eligible*, not a
    drop probability: an item's own `lootLevel` must be within this
    sector's own reach, and (if it has any) every one of its own
    `item.props.lootMaterial` requirements must be present in this
    sector's `secondaryMaterialPool` (Finding 25 Part A — confirmed both
    via raw opcodes and via `item@props.lootMaterial`'s own `data.cdb`
    column documentation). The real per-crate pick is a repeated random-
    draw budget-fill loop (`Loot.generate`'s secondary-slot loop, tuned by
    the `constant` sheet's `Loot_Secondary_Overflow`/
    `Loot_Secondary_SmallestStack`) that isn't simulated here, so there's
    no per-item pct/expected-per-wreck for this channel yet, unlike the
    primary items below.
  - `itemDropOdds.patches` / `itemDropOdds.blueprints`: per-item drop
    probability by sector, sectors pre-grouped wherever the odds land on the
    same number. The concrete Patch pool is `item.type=Patch` rows with their
    own `lootLevel`; the Blueprint pool is `craft.lootLevel` rows that ALSO
    have `craft.unlockType == 2` (Random_Blueprint) — a recipe with a
    `lootLevel` but a different `unlockType` (e.g. `Unique_Blueprint`, a
    fixed quest/vendor/location source) is never actually reachable from
    this crate system, confirmed via the dedicated Blueprint-candidate
    closure in `src/logic/Loot.hx` (see `shipbuilder/tools/
    game_logic_notes.md` Finding 15) — named `"Blueprint: <output item
    name>"` per the game's own convention. This is conditional on a crate
    already being open — it does not account for how many crates a wreck
    actually has.
  - `wreckSiteItemOdds.patches` / `wreckSiteItemOdds.blueprints`: same
    per-item/per-sector shape as `itemDropOdds`, but composed against
    `crateSpawn`'s own crate-count distribution too — `expectedPerWreck`
    (mean count of this item per wreck) and `atLeastOnePct` (P(this item
    drops at least once across the whole wreck site)), the more honest
    numbers for "how many of item X do I expect visiting one wreck site."
  - `patchPoolByLevel` / `blueprintPoolByLevel`: the raw pools each of the
    above is built from.

  The probability model: P(a crate rolls a Patch/Blueprint primary item at
  all) = `clamp((level-2)/5, 0, 1)`, and — corrected after an initial pass
  wrongly required an exact level match — the eligible item pool for a crate
  targeting level `L` is every item with `lootLevel` in the 2-level window
  `{L-1, L}`, not just `L` (confirmed against raw HashLink opcodes in
  `src/logic/Loot.hx`, both cross-checked against an actual reported drop).
  Which category (Patch vs Blueprint) wins when both have an eligible
  candidate is a real weighted pick (not a flat 50/50, an earlier
  approximation) — `weight = max(0, 10 - |L - itl| - 2*(L - candidate's own
  lootLevel))`, where `itl` is a per-category constant from `data.cdb`'s
  `constant` sheet (Patch=5, Blueprint=7). This is the complete model for
  `ShipWreck_LootChestRare_lvl{0,1,2}` — the Tool/Module/ShipDecorative
  categories are real, separate branches in the underlying code, but the
  `loot` sheet rows these crates actually reference have
  `primaryItemTypes==12` (Patch|Blueprint bits only), so those other
  categories never compete for this crate type's primary-item slot at all —
  see `game_logic_notes.md` Finding 15 for the full derivation. See the file's
  own `_meta` block for the full derivation notes, and
  [`shipwreck_loot_integration.md`](shipwreck_loot_integration.md) for how
  this is surfaced in CraftMap's "Wrecks" tab and
  [`shipwreck_loot.html`](shipwreck_loot.html) for a standalone browsable view
  of the same data. Not merged into `resources.db` — reference data pending a
  decision on where shipwreck loot should live in the schema.

- **`farming.json`** — Xenic Farm crop/variant reference data (the "Farming"
  tab, `backend/farming.py` + `frontend/js/farming.js`). Unlike the files
  above it is **hand-transcribed, not script-regenerated** — sourced from
  `shipbuilder/tools/game_logic_notes.md` Findings 13/14/16/17/18/19/20/21
  (decompiled `ent.b.Farm`/`ent.b.PlotZone` logic plus `data.cdb`'s `farm`/
  `attribute`/`constant` sheets), so a new/corrected finding there means
  updating this file by hand to match. Per grown variant: grow-gate
  (temperature/light dial positions, fertilizer, neighbor bio-tag rules),
  growth/per-item durations, and toggleable enrichment/adjacency modifiers
  using the game's real attribute semantics (`all_speed` /
  `growth_speed_mult` / `fruit_qty` / `byproduct_qty`). Its own `_meta`
  block is the authoritative doc for the data model — notably
  `harvest_mechanism` (fruit/byproduct accrue during growth and pay out
  once at gather; `*_cycle_hours` means "hours of growth per item", not a
  repeating timer), `effects` (the modifier math the frontend computes
  with), `dial_mechanics` (instant dial switching, per-planet energy
  costs, the no-Natural-light-in-dark-sites rule), and `adjacency_timing`
  (Finding 21, corrected 2026-07-28: a neighbor's adjacency effects are
  live ONLY while it is actively, currently growing — the instant a plant
  finishes growing its plot swaps to a `_Gather` row with an EMPTY
  adjacency array and no bio_tag, so a mature, unharvested plant gives its
  neighbors nothing. This retracts Finding 19's opposite claim and the
  "parked battery" technique built on it — a companion must be genuinely
  live, continuously replanted, to contribute anything). A top-level
  `layouts` object plus each variant's own `goal_presets` (see `_meta.
  goal_presets_and_layouts`) back the Farming tab's Layouts sub-mode - 5x3
  plot grids for the Xenic Farm's real neighbor mechanics, picked per
  variant and per (items/hour vs items/harvest, overall vs fruit-only vs
  byproduct-only) goal. Deliberately not precomputed numbers: a preset
  just names which of that variant's own toggle ids to check, so the
  Layouts view drives the same live calculator the Reference cards use
  rather than a second calculation that could drift from it. Every layout/
  preset here is derived by an exact, exhaustive grid search rather than
  hand geometry (`_meta.exact_grid_search`) — a companion cell only
  counts as usable if it's LIVE and passes four checks: dial
  compatibility, fertilizer compatibility (shared per 3x5 group, `_meta.
  fertilizer_scope`), restriction compatibility in both directions, and
  germination cleanliness on both sides (`_meta.germination_ambiguity`).
  An `overall` goal is always resolved to one genuine combined-optimal
  answer (each product normalized against its own achievable max, summed,
  then the whole search re-run against that) rather than a side-by-side
  menu of the fruit-only/byproduct-only extremes - the `{no_dominant,
  options: [...]}` shape stays in the schema but is unused. A
  goal_preset's farm-total math sums each matching cell's OWN real
  grid-neighbor adjacency (`frontend/js/farming.js`'s
  `collectEffectsForCell`) rather than multiplying one blanket per-plant
  number by a cell count, so any future non-uniform-coverage layout would
  still read correctly.

## How this differs from `resources.db`'s recipe tables

| | `resources.db` (`recipes`/`recipe_ingredients`) | game data (`craft_recipes.json`) |
|---|---|---|
| Recipe count | 254 | 479 |
| Source | hand-entered while playing | authoritative game files |
| Output quantity | `recipes.output_qty` (single) | `outputs[].qty`, and **can have multiple outputs per recipe** |
| Output name override | `recipes.output_name` (nullable) | `outputs[].item` vs `craft.id` can already differ; no 1:1 assumption needed |
| Ingredient id | free-text `ingredient_name` | canonical `item_id`, resolvable via `items.json` for a display name |
| Station / category / power cost / dev notes | not tracked | `where`, `category`, `props`, `note` |
| Alternate recipes for one output | inferred at runtime by matching `output_name` across rows | same idea works, but grouping should be done by `outputs[].item`, not by `craft.id` |

Two things worth deciding before merging into `backend/db.py`'s schema:

1. **Multiple outputs per recipe** isn't representable in the current
   `recipes` table (`output_qty` + one `output_name`). Recipes like
   `AluminiumIngot_Aquamarine` (outputs `SiliciumIngot` qty 2 *and*
   `AluminiumIngot` qty 1) would need either a new `recipe_outputs` table
   mirroring `recipe_ingredients`, or splitting into synthetic per-output rows.
2. **Ids vs. display names** — `craft_recipes.json` uses internal ids
   (`IronOre`, `AluminiumIngot_Aquamarine`), while `resources.db` currently
   stores human-readable names typed in by hand. `items.json` gives you the
   `name` to resolve ids, but existing manually-entered names may not match
   the game's naming exactly (worth a diff pass before assuming a 1:1 rename).
