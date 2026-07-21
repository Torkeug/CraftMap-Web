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
    Cannot_Unlock,Study,Dismantle,Custo"`): `0`=Permit (always known),
    `1`=Unique_Blueprint (a fixed, non-random source — quest/vendor/
    location), `2`=Random_Blueprint (the only value the shipwreck rare-crate
    system ever draws from — see `shipwreck_loot.json`'s notes and
    `shipbuilder/tools/game_logic_notes.md` Finding 15), `3`=Cannot_Unlock,
    `4`=Study, `5`=Dismantle, `6`=Custom. A recipe can have a `lootLevel` set
    while still being `unlockType != 2` — it will never actually drop from a
    crate in that case.
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
