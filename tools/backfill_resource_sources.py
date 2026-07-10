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
Existing rows are left alone (INSERT OR IGNORE via db.set_resource_sources's
own dedup), so hand-added sources survive a re-run.

Each yield also gets a `concentration`: a node's same-kind items compete via
a relative `proba` weight (e.g. Siderite's primary group: IronOre proba 20,
Calcite proba 1, Carbon proba 7 - so roughly 7/28 = 25% of that node's
primary-yield rolls are Carbon). concentration is that proba normalized
against its same-kind siblings *at the same node*, as a percentage.

For secondary (rare-find) items, that per-kind share alone reads as far too
common - White Quartz's rare-find pool is just Beautiful Gemstone (proba 40)
vs Marvelous Gemstone (proba 1), so Beautiful Gemstone's *share of that
pool* is 97.6%, but a rare find itself only happens on
generation.secondaryProba (here 0.1 = 10%) of gathers in the first place -
so it's really more like 9.8% of gathers overall. Secondary concentrations
are scaled by secondaryProba to reflect that; primary yields have no
equivalent gate (some primary item always drops), so they're left as-is.

Deposit/Pool/Geyser nodes (see game_data_extract/README.md) have no `items`
list at all - they yield a single guaranteed item (`props.depositItem` or
`props.geyser.fluid`), auto-drilled/passively collected with no randomness,
so those get a flat 100% concentration and no "(rare find)" suffix (their
own name, e.g. "Coal Deposit"/"Mercury Geyser", already says what they are).

Shell/ShipWreck nodes are different again: `props.loot` is a list of
bundles (`{proba, items: [...]}`), and cracking/salvaging picks exactly ONE
bundle - every item in it drops together. A resource's concentration there
is the summed proba of every bundle that contains it, over the total proba
across all of that node's bundles (an item appearing in multiple bundles is
correspondingly more likely to show up).

Usage:
    python tools/backfill_resource_sources.py
"""
import json
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


def node_yields(node, items):
    """Yield (resource_name, label, concentration) for one resource node,
    covering all four shapes a node's yield can take - see this module's
    docstring."""
    node_name = node.get("name") or node["id"]

    deposit_item = node.get("props", {}).get("depositItem")
    geyser_fluid = node.get("props", {}).get("geyser", {}).get("fluid")
    single_item = deposit_item or geyser_fluid
    if single_item:
        yield item_name(items, single_item), node_name, 100.0
        return

    loot = node.get("props", {}).get("loot")
    if loot and node.get("type") == TYPE_SHELL:
        total_bundle_proba = sum(b.get("proba", 0) for b in loot)
        proba_by_item = defaultdict(float)
        for bundle in loot:
            for entry in bundle.get("items", []):
                item_id = entry.get("item")
                if item_id is not None:
                    proba_by_item[item_id] += bundle.get("proba", 0)
        for item_id, proba in proba_by_item.items():
            concentration = (
                (proba / total_bundle_proba * 100) if total_bundle_proba else None
            )
            yield item_name(items, item_id), node_name, concentration
        return

    secondary_proba = node.get("generation", {}).get("secondaryProba", 1.0)
    # A handful of "resource" rows are loot-chest tiers that reference
    # another loot table by name (`loot` key) instead of a concrete item
    # id - not a raw material node, excluded here.
    raw_yields = [y for y in node.get("items", []) if y.get("item") is not None]
    by_kind = defaultdict(list)
    for y in raw_yields:
        by_kind[y.get("kind", 0)].append(y)

    for kind, group in by_kind.items():
        total_proba = sum(y.get("proba", 0) for y in group)
        gate = secondary_proba if kind == 1 else 1.0
        label = node_name + KIND_LABELS.get(kind, f" (kind {kind})")
        for yielded in group:
            proba = yielded.get("proba", 0)
            concentration = (proba / total_proba * gate * 100) if total_proba else None
            yield item_name(items, yielded["item"]), label, concentration


def main():
    init_db()
    items, nodes = load_game_data()

    sources_by_resource = defaultdict(list)
    for node in nodes:
        for resource_name, label, concentration in node_yields(node, items):
            existing_names = {n for n, _ in sources_by_resource[resource_name]}
            if label not in existing_names:
                sources_by_resource[resource_name].append((label, concentration))

    for resource_name, sources in sources_by_resource.items():
        existing = db.get_resource_sources(resource_name)
        existing_names = {n for n, _ in existing}
        new_sources = [s for s in sources if s[0] not in existing_names]
        db.set_resource_sources(resource_name, existing + new_sources)

    print(
        f"Backfilled sources for {len(sources_by_resource)} resources"
        f" from {len(nodes)} game resource nodes."
    )


if __name__ == "__main__":
    main()
