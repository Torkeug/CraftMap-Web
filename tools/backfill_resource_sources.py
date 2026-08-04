"""
One-off maintenance script: populate resources.db's resource_sources table
(raw material -> the node types that yield it, e.g. "a-Carbon" <- "Coal
Clump") from game_data_extract/resource_nodes.json, itself extracted from
the game's data.cdb by the sibling shipbuilder/tools/extract_craft_data.py.
Does not touch anything besides resource_sources.

Every yield is backfilled, both kinds the game's `resource@items` sheet
defines (`kind`: 0 = Primary, 1 = Secondary - a rarer "rare find" bonus
roll alongside a node's primary material, per the game's own terminology,
e.g. Coal Clump's primary yield is Carbon but it can also rarely turn up a
Diamond). Secondary sources are suffixed "(rare find)" so they read as the
long-shot they are rather than looking like an equally reliable source.
Re-running refreshes every row whose source name still matches a currently
computed game node (so a game-data or formula update propagates), but never
touches a row whose name has no current game-data match - that's how a
hand-added source survives a re-run.

Each yield gets two independent numbers - both shown in the Sources tab
side by side, since neither alone is enough to rank same-node siblings:

- `concentration`: a node's same-kind items compete via a relative `proba`
  weight (e.g. Siderite's primary group: IronOre proba 20, Calcite proba 1,
  Carbon proba 7 - so roughly 7/28 = 25% of that node's primary-yield rolls
  are Carbon). concentration is that proba normalized against its same-kind
  siblings *at the same node*, as a percentage. It's a *relative* share, so
  two different items at two different nodes can land on the exact same %
  by coincidence, giving no way to tell which is the better source.
- `expected_qty`: the average quantity of this item actually obtained per
  harvest of that node - an *absolute* figure, breaking exactly those ties.
  This is the same number the game's own Encyclopedia shows next to each
  contained item (e.g. "Aluminum Nugget 20.02" under Aluminum Reduction's
  CONTAINS list) - reverse engineered from the game's compiled Haxe bytecode
  (`src/lib/utils/ResourceUtils.hx:getItemsExpectations`, via hlbc against
  the sibling shipbuilder repo's decompile toolchain) and cross-checked
  against that exact 20.02 value. In short: a node's `generation.amounts`
  array gives a probability distribution over how many yield-rolls a single
  harvest produces (its own array index *is* the roll count, weighted by
  that index's `proba`); some of those rolls are drawn from the "secondary"
  (rare-find) pool instead of the primary one, at `generation.secondaryProba`
  per roll, capped at `generation.secondaryMax` rare-find rolls per harvest -
  `_expected_roll_counts` splits the overall expected roll count into
  expected-primary-rolls and expected-secondary-rolls accordingly (the
  secondary side needs the standard "expectation of a binomial capped at a
  max" trick: sum the per-count contributions below the cap, then fold
  everything at-or-above the cap into one `cap * P(X >= cap)` tail term,
  computed as `cap * (1 - sum of the pmf below the cap)` rather than an
  actually-unbounded tail sum). Each item then gets its share of its own
  kind's expected roll count (proba-weighted against its same-kind
  siblings, same as `concentration`), times its own average qty
  (`(qtyMin + qtyMax) / 2`). A node with no `generation.amounts` at all
  skips all of the above and every item just gets its own flat average qty,
  unweighted - confirmed to be what the game itself does for that shape too
  (plant/seed nodes mostly, e.g. Spacekorn Root).

For secondary (rare-find) items, `concentration` alone reads as far too
common - White Quartz's rare-find pool is just Beautiful Gemstone (proba 40)
vs Marvelous Gemstone (proba 1), so Beautiful Gemstone's *share of that
pool* is 97.6%, but a rare find itself only happens on
generation.secondaryProba (here 0.1 = 10%) of gathers in the first place -
so it's really more like 9.8% of gathers overall. Secondary concentrations
are scaled by secondaryProba to reflect that; primary yields have no
equivalent gate (some primary item always drops), so they're left as-is.
This is a deliberate simplification specific to `concentration` (it doesn't
account for the roll-count distribution or the capped-binomial rare-find
math) - `expected_qty` doesn't need it, since it derives secondary items'
share from `_expected_roll_counts`'s own already-exact secondary-roll
expectation.

Deposit/Pool/Geyser nodes (see game_data_extract/README.md) have no `items`
list at all - they yield a single guaranteed item (`props.depositItem` or
`props.geyser.fluid`), auto-drilled/passively collected with no randomness,
so those get a flat 100% concentration and no "(rare find)" suffix (their
own name, e.g. "Coal Deposit"/"Mercury Geyser", already says what they are).
`expected_qty` is left None for depositItem nodes - the game displays a
per-hour mining rate for those instead (a different unit entirely, computed
from `$Const.DepositMiningBaseTime`, not a per-harvest quantity), which
isn't a fair comparison against every other node's per-harvest number. A
geyser's `expected_qty` is just its flat `props.geyser.quantity` (also not
random - the game shows it as-is).

Shell/ShipWreck nodes are different again: `props.loot` is a list of
bundles (`{proba, items: [...]}`), and cracking/salvaging picks exactly ONE
bundle - every item in it drops together. A resource's concentration there
is the summed proba of every bundle that contains it, over the total proba
across all of that node's bundles (an item appearing in multiple bundles is
correspondingly more likely to show up); `expected_qty` sums each
containing bundle's own (proba-share * that bundle's own avg qty for the
item), since the same item can carry a different qtyMin/qtyMax per bundle.

Usage:
    python tools/backfill_resource_sources.py
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend import db  # noqa: E402
from backend.db import init_db  # noqa: E402

GAME_DATA_DIR = REPO_ROOT / "game_data_extract"

KIND_LABELS = {0: "", 1: " (rare find)"}

# resource@type enum index for "Shell" - see game_data_extract/README.md.
# ShipWreck (type 7) also uses props.loot, but with tiered "loot chest"
# entries that reference OTHER named loot tables we haven't extracted
# (bundle items with a `loot` key instead of a concrete `item` id) - needs
# its own handling later, so it's deliberately excluded here for now even
# though resource_nodes.json already carries its raw data.
TYPE_SHELL = 4


def load_game_data():
    items = json.loads((GAME_DATA_DIR / "items.json").read_text(encoding="utf-8"))
    nodes = json.loads(
        (GAME_DATA_DIR / "resource_nodes.json").read_text(encoding="utf-8")
    )
    return items, nodes


def item_name(items, item_id):
    return items.get(item_id, {}).get("name") or item_id


def _avg_qty(entry):
    qty_min, qty_max = entry.get("qtyMin"), entry.get("qtyMax")
    if qty_min is None or qty_max is None:
        return None
    return (qty_min + qty_max) / 2


def _binom_proba(n, k, p):
    """P(exactly k successes in n independent p-probability trials) -
    matches the game's own binomProba@ResourceUtils.hx exactly (standard
    binomial pmf)."""
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p**k) * ((1 - p) ** (n - k))


def _expected_roll_counts(amounts, secondary_proba, secondary_max):
    """(expected_primary_rolls, expected_secondary_rolls) for one harvest of
    a node whose `generation.amounts` gives a probability distribution over
    total roll count (array index = roll count, `proba` = its weight). Of
    that total, each individual roll independently has a `secondary_proba`
    chance of being a secondary (rare-find) roll instead of primary, capped
    at `secondary_max` secondary rolls per harvest - see this module's
    docstring for the capped-binomial-expectation derivation."""
    sum_amt_proba = sum(a.get("proba", 0) for a in amounts)
    if not sum_amt_proba:
        return 0.0, 0.0
    total_expectation = (
        sum(idx * a.get("proba", 0) for idx, a in enumerate(amounts)) / sum_amt_proba
    )

    secondary_expectation = 0.0
    if secondary_max and secondary_proba is not None:
        for n, a in enumerate(amounts):
            proba = a.get("proba", 0)
            if not proba:
                continue
            weight = proba / sum_amt_proba
            binom_probas = [_binom_proba(n, 0, secondary_proba)]
            for k in range(1, secondary_max + 1):
                binom_probas.append(_binom_proba(n, k, secondary_proba))
                if k < secondary_max:
                    secondary_expectation += weight * binom_probas[k] * k
                else:
                    tail = 1 - sum(binom_probas[:k])
                    secondary_expectation += weight * tail * k

    return total_expectation - secondary_expectation, secondary_expectation


def node_yields(node, items):
    """Yield (resource_name, label, concentration, expected_qty) for one
    resource node, covering all four shapes a node's yield can take - see
    this module's docstring."""
    node_name = node.get("name") or node["id"]

    deposit_item = node.get("props", {}).get("depositItem")
    geyser = node.get("props", {}).get("geyser")
    if deposit_item:
        yield item_name(items, deposit_item), node_name, 100.0, None
        return
    if geyser:
        yield item_name(items, geyser["fluid"]), node_name, 100.0, geyser.get(
            "quantity"
        )
        return

    loot = node.get("props", {}).get("loot")
    if loot and node.get("type") == TYPE_SHELL:
        total_bundle_proba = sum(b.get("proba", 0) for b in loot)
        proba_by_item = defaultdict(float)
        expected_qty_by_item = defaultdict(float)
        for bundle in loot:
            bundle_proba = bundle.get("proba", 0)
            for entry in bundle.get("items", []):
                item_id = entry.get("item")
                if item_id is None:
                    continue
                proba_by_item[item_id] += bundle_proba
                avg_qty = _avg_qty(entry)
                if avg_qty is not None and total_bundle_proba:
                    expected_qty_by_item[item_id] += (
                        bundle_proba / total_bundle_proba * avg_qty
                    )
        for item_id, proba in proba_by_item.items():
            concentration = (
                (proba / total_bundle_proba * 100) if total_bundle_proba else None
            )
            expected_qty = expected_qty_by_item.get(item_id) if total_bundle_proba else None
            yield item_name(items, item_id), node_name, concentration, expected_qty
        return

    if not node.get("items"):
        return

    generation = node.get("generation", {})
    amounts = generation.get("amounts")
    if amounts:
        primary_rolls, secondary_rolls = _expected_roll_counts(
            amounts, generation.get("secondaryProba"), generation.get("secondaryMax")
        )
    else:
        primary_rolls = secondary_rolls = None

    # A handful of "resource" rows are loot-chest tiers that reference
    # another loot table by name (`loot` key) instead of a concrete item
    # id - not a raw material node, excluded here.
    raw_yields = [y for y in node.get("items", []) if y.get("item") is not None]
    by_kind = defaultdict(list)
    for y in raw_yields:
        by_kind[y.get("kind", 0)].append(y)

    secondary_proba = generation.get("secondaryProba", 1.0)
    for kind, group in by_kind.items():
        total_proba = sum(y.get("proba", 0) for y in group)
        gate = secondary_proba if kind == 1 else 1.0
        label = node_name + KIND_LABELS.get(kind, f" (kind {kind})")
        expected_rolls = secondary_rolls if kind == 1 else primary_rolls
        for yielded in group:
            proba = yielded.get("proba", 0)
            concentration = (proba / total_proba * gate * 100) if total_proba else None
            avg_qty = _avg_qty(yielded)
            if amounts:
                expected_qty = (
                    (proba / total_proba) * expected_rolls * avg_qty
                    if total_proba and avg_qty is not None
                    else None
                )
            else:
                # No roll-count distribution at all - the game just shows
                # each item's own flat average qty, unweighted by proba.
                expected_qty = avg_qty
            yield item_name(items, yielded["item"]), label, concentration, expected_qty


def main():
    init_db()
    items, nodes = load_game_data()

    sources_by_resource = defaultdict(list)
    for node in nodes:
        for resource_name, label, concentration, expected_qty in node_yields(
            node, items
        ):
            existing_names = {n for n, _, _ in sources_by_resource[resource_name]}
            if label not in existing_names:
                sources_by_resource[resource_name].append(
                    (label, concentration, expected_qty)
                )

    for resource_name, sources in sources_by_resource.items():
        existing = db.get_resource_sources(resource_name)
        computed_names = {n for n, _, _ in sources}
        # Rows with no current game-data match are hand-added (or stale) -
        # preserve them untouched; everything else gets the freshly
        # computed values, overwriting whatever was there before.
        hand_added = [row for row in existing if row[0] not in computed_names]
        db.set_resource_sources(resource_name, hand_added + sources)

    print(
        f"Backfilled sources for {len(sources_by_resource)} resources"
        f" from {len(nodes)} game resource nodes."
    )


if __name__ == "__main__":
    main()
