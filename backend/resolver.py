"""Recipe tree resolution - copied verbatim from craftmap/overlay.py's
Recipe tree resolution section. Pure logic plus one direct DB read
(_load_recipe_data); shares resources.db with the existing tkinter app,
see paths.py.
"""

import math
import sqlite3

from .paths import DB_PATH


# ---------- Recipe tree resolution ----------


def _load_recipe_data():
    """Load all recipes, outputs, and ingredients in a few queries."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name FROM recipes")
    recipe_name_by_id = {rid: rname for rid, rname in c.fetchall()}
    c.execute(
        "SELECT id, station, auto_craft_seconds, manual_craft_seconds FROM recipes"
    )
    recipe_meta_by_id = {
        rid: {
            "station": station,
            "auto_craft_seconds": auto_s,
            "manual_craft_seconds": manual_s,
        }
        for rid, station, auto_s, manual_s in c.fetchall()
    }
    # Order by recipe id ASC so the first (oldest) recipe for each output item
    # is the default.
    c.execute(
        "SELECT ro.recipe_id, ro.item_name, ro.quantity"
        " FROM recipe_outputs ro JOIN recipes r ON r.id = ro.recipe_id"
        " ORDER BY r.id ASC, ro.id ASC"
    )
    recipe_map = {}  # item_name / recipe_name → first recipe_id producing it
    outputs_by_recipe = {}  # recipe_id → [(item_name, qty), ...], index 0 = primary
    alts_by_output = {}  # item_name → [(rid, recipe_name, qty_for_that_item), ...]
    for rid, item_name, qty in c.fetchall():
        outputs_by_recipe.setdefault(rid, []).append((item_name, float(qty)))
        rname = recipe_name_by_id.get(rid, item_name)
        alts_by_output.setdefault(item_name, []).append((rid, rname, float(qty)))
        if item_name not in recipe_map:  # first by id wins as default
            recipe_map[item_name] = rid
    # Also index by recipe name so ingredients can reference alternates by name
    for rid, rname in recipe_name_by_id.items():
        if rname not in recipe_map:
            recipe_map[rname] = rid
    c.execute(
        "SELECT recipe_id, ingredient_name, quantity FROM recipe_ingredients ORDER BY id"
    )
    ing_map: dict = {}
    for rid, ing_name, qty in c.fetchall():
        ing_map.setdefault(rid, []).append((ing_name, qty))
    c.execute(
        "SELECT recipe_id, station, auto_craft_seconds, manual_craft_seconds"
        " FROM recipe_stations ORDER BY id"
    )
    stations_by_recipe: dict = {}
    for rid, station, auto_s, manual_s in c.fetchall():
        stations_by_recipe.setdefault(rid, []).append((station, auto_s, manual_s))
    conn.close()
    return (
        recipe_map,
        ing_map,
        outputs_by_recipe,
        alts_by_output,
        recipe_name_by_id,
        recipe_meta_by_id,
        stations_by_recipe,
    )


def resolve_recipe_tree(
    name,
    qty_needed=1.0,
    _visited=None,
    _recipe_map=None,
    _ing_map=None,
    _outputs_by_recipe=None,
    _root_recipe_id=None,
    _alts_by_output=None,
    _recipe_name_by_id=None,
    _recipe_meta_by_id=None,
    _alt_prefs=None,
    _stations_by_recipe=None,
    _station_prefs=None,
    max_depth=None,
    _depth=0,
):
    """
    Recursively build a breakdown tree for `name`.
    Returns: {'name', 'qty', 'is_recipe', 'output_qty', 'recipe_name', 'children',
              'alts', 'byproducts', 'station', 'auto_craft_seconds',
              'manual_craft_seconds', 'stations', 'truncated'}
    'alts' lists every other recipe producing the same output, for the alt-recipe picker popup - each entry's own ingredients are deliberately NOT resolved (no consumer reads an alt's `children`; resolving it anyway used to make a full, non-depth-limited resolve pay for recursively resolving every alternate's entire subtree, unboundedly).
    'byproducts' lists this recipe's other outputs (besides `name`), scaled to
    the same craft count — populated for multi-output recipes.
    'stations' lists every usable station for this node's recipe (station,
    auto_craft_seconds, manual_craft_seconds), so the UI can offer a picker.
    _root_recipe_id: forces a specific recipe at the top level (for alternate recipe views).
    _alt_prefs: {ingredient_name: recipe_id} of user-selected alternate recipes.
    _station_prefs: {ingredient_name: station} of user-selected preferred stations.
    max_depth: stop recursing past this many levels below the root (None = no
    limit) - a node that would have had children but hit the limit comes back
    with 'children': [] and 'truncated': True instead, so the caller can tell
    "genuinely no children" apart from "not resolved yet" and fetch that one
    node's own subtree later (see get_recipe_subtree) instead of paying to
    resolve - and transmit across the pywebview bridge - a potentially huge
    tree in one call when most of it may never even be looked at (a
    breakdown tree UI starts with almost everything collapsed).
    """
    if _recipe_map is None or _ing_map is None or _outputs_by_recipe is None:
        (
            _recipe_map,
            _ing_map,
            _outputs_by_recipe,
            _alts_by_output,
            _recipe_name_by_id,
            _recipe_meta_by_id,
            _stations_by_recipe,
        ) = _load_recipe_data()
    if _visited is None:
        _visited = frozenset()

    if _root_recipe_id is not None:
        recipe_id = _root_recipe_id
    elif _alt_prefs and name in _alt_prefs:
        recipe_id = _alt_prefs[name]
    else:
        recipe_id = _recipe_map.get(name)
    is_recipe = recipe_id is not None and name not in _visited

    children = []
    alts = []
    byproducts = []
    output_qty = 1.0
    used_recipe_name = name
    station = None
    auto_craft_seconds = None
    manual_craft_seconds = None
    craft_mode = "auto"
    stations: list = []
    if is_recipe:
        recipe_outputs = _outputs_by_recipe.get(recipe_id, [(name, 1.0)])
        output_names = [n for n, _ in recipe_outputs]
        actual_output = name if name in output_names else output_names[0]
        output_qty = next(q for n, q in recipe_outputs if n == actual_output)
        used_recipe_name = (_recipe_name_by_id or {}).get(recipe_id, name)
        meta = (_recipe_meta_by_id or {}).get(recipe_id, {})
        station = meta.get("station")
        auto_craft_seconds = meta.get("auto_craft_seconds")
        manual_craft_seconds = meta.get("manual_craft_seconds")
        craft_mode = "auto" if auto_craft_seconds else "manual"
        stations = (_stations_by_recipe or {}).get(recipe_id, [])
        pref = (_station_prefs or {}).get(name)
        pref_station, pref_mode = pref if pref else (None, None)
        if pref_station:
            for st_name, st_auto, st_manual in stations:
                if st_name == pref_station:
                    station, auto_craft_seconds, manual_craft_seconds = (
                        st_name,
                        st_auto,
                        st_manual,
                    )
                    craft_mode = pref_mode or ("auto" if st_auto else "manual")
                    break
        crafts = math.ceil(qty_needed / output_qty)
        byproducts = [
            {"name": n, "qty": crafts * q}
            for n, q in recipe_outputs
            if n != actual_output
        ]

    truncated = False
    if is_recipe:
        if max_depth is not None and _depth >= max_depth:
            truncated = True
        else:
            sub_visited = _visited | {name}
            for ing_name, ing_qty in _ing_map.get(recipe_id, []):
                child = resolve_recipe_tree(
                    ing_name,
                    crafts * ing_qty,
                    sub_visited,
                    _recipe_map,
                    _ing_map,
                    _outputs_by_recipe,
                    _alts_by_output=_alts_by_output,
                    _recipe_name_by_id=_recipe_name_by_id,
                    _recipe_meta_by_id=_recipe_meta_by_id,
                    _alt_prefs=_alt_prefs,
                    _stations_by_recipe=_stations_by_recipe,
                    _station_prefs=_station_prefs,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )
                children.append(child)
            # Find every other recipe that produces the same output - listed
            # for the alt-recipe picker popup only (frontend/js/breakdown-
            # tree.js's openStepPopup reads nothing but recipe_id/recipe_name
            # off each entry; set_alt_pref takes it from there), so unlike
            # the chosen recipe's own ingredients above, an alt's own
            # ingredient tree is deliberately NOT resolved here - no
            # consumer anywhere has ever read an alt's `children`. That
            # used to recurse into every alternate's full ingredient tree
            # (including THEIR alts, recursively) - fine when max_depth
            # capped it, but unbounded and potentially exponential for a
            # full (max_depth=None) resolve like Api.get_queue_totals_view's,
            # which is what made the queue Totals view slow to generate.
            for alt_rid, alt_rname, alt_oqty in (_alts_by_output or {}).get(
                actual_output, []
            ):
                if alt_rid == recipe_id:
                    continue
                alt_crafts = math.ceil(qty_needed / alt_oqty)
                alt_outputs = _outputs_by_recipe.get(
                    alt_rid, [(actual_output, alt_oqty)]
                )
                alt_byproducts = [
                    {"name": n, "qty": alt_crafts * q}
                    for n, q in alt_outputs
                    if n != actual_output
                ]
                alts.append(
                    {
                        "recipe_id": alt_rid,
                        "recipe_name": alt_rname,
                        "output_qty": alt_oqty,
                        "byproducts": alt_byproducts,
                        "stations": (_stations_by_recipe or {}).get(alt_rid, []),
                    }
                )

    return {
        "name": name,
        "qty": qty_needed,
        "is_recipe": is_recipe,
        "output_qty": output_qty,
        "recipe_name": used_recipe_name,
        "children": children,
        "alts": alts,
        "byproducts": byproducts,
        "station": station,
        "auto_craft_seconds": auto_craft_seconds,
        "manual_craft_seconds": manual_craft_seconds,
        "craft_mode": craft_mode,
        "stations": stations,
        "truncated": truncated,
    }


def _node_crafts(node):
    """Number of separate craft cycles needed to cover node['qty'], given its
    own output_qty per craft. 0 for raw (non-recipe) nodes."""
    if not node.get("is_recipe"):
        return 0
    return math.ceil(node["qty"] / node.get("output_qty", 1.0))


def _node_active_seconds(node):
    """(seconds, mode) for this node's currently active craft mode - the
    per-craft time, not yet scaled by how many crafts are needed."""
    mode = node.get("craft_mode", "auto")
    seconds = (
        node.get("auto_craft_seconds")
        if mode == "auto"
        else node.get("manual_craft_seconds")
    )
    return seconds, mode


def _node_own_time(node):
    """Total seconds this node's own craft step takes across every craft it
    needs (per-craft time x crafts needed) - 0 for raw nodes or ones with no
    timing data. This is the number that was previously shown un-scaled,
    which made e.g. '4x Titanium Part Casing' look like it only took one
    casing's craft time instead of four."""
    seconds, _mode = _node_active_seconds(node)
    if not seconds:
        return 0.0
    return seconds * _node_crafts(node)


def _node_path_key(node, path_parts):
    return "|".join(path_parts + [node["name"]])


def _subtree_remaining_seconds(node, path_parts, checked):
    """Sum of _node_own_time across this node and every descendant. A
    checked path_key means its whole subtree is considered done (its own
    time, and everything under it, drops out) rather than just itself."""
    if _node_path_key(node, path_parts) in checked:
        return 0.0
    total = _node_own_time(node)
    for child in node["children"]:
        total += _subtree_remaining_seconds(child, path_parts + [node["name"]], checked)
    return total


def _collect_path_keys(node, path_parts):
    """Every path_key in this node's own subtree, including itself - matches
    the scheme used when inserting breakdown-tree rows, so checking a step
    can cascade the same checked state onto everything it depends on."""
    keys = [_node_path_key(node, path_parts)]
    for child in node["children"]:
        keys.extend(_collect_path_keys(child, path_parts + [node["name"]]))
    return keys


def _node_has_step_options(node):
    """Whether this node has an alternate recipe or more than one usable
    (station, mode) combination - i.e. whether its _StepPopup would show
    anything at all."""
    if not node.get("is_recipe"):
        return False
    if node.get("alts"):
        return True
    modes_available = sum(
        (1 if st_auto else 0) + (1 if st_manual else 0)
        for _name, st_auto, st_manual in node.get("stations", [])
    )
    return modes_available > 1


def build_occurrence_specs(node):
    """Structural, CHECKED-STATE-INDEPENDENT flatten of a FULLY resolved
    job tree (excluding the tree's own root - a job's own final output is
    shown by its own job header, not a demand on anything) into one 'spec'
    dict per descendant, at EVERY tier - raw or crafted, not just the
    bottom-most crafted tier (the old collect_basic_crafted's scope, which
    made multi-tier crafting chains show only their lowest tier).

    This is the EXPENSIVE part of Totals-view aggregation (computing every
    node's path_key - an O(depth) string join - plus its display metadata)
    - and unlike checked-state (which changes on every checkbox click), a
    job's structure only changes when its own qty/recipe/station changes.
    So this is meant to be resolved once and cached alongside the job's
    resolved tree (see Api._get_totals_job_specs), NOT recomputed on every
    Totals render - checked-state pruning happens separately and cheaply,
    in filter_unchecked_occurrences below, over this already-built list,
    so a plain checkbox toggle never re-walks the tree at all.

    Each spec is in DFS pre-order and carries a `parent_index` back to its
    own parent's position in this same list (or None for a root child) -
    this is what lets filter_unchecked_occurrences reproduce
    _subtree_remaining_seconds's prune-at-checked-node rule (a checked
    node is still recorded, but nothing under it is) via one cheap linear
    pass instead of a tree walk."""
    specs = []
    _walk_occurrence_specs(node, [], None, specs)
    return specs


def _walk_occurrence_specs(node, path_parts, parent_index, specs):
    child_path_parts = path_parts + [node["name"]]
    for child in node["children"]:
        spec = {
            "name": child["name"],
            "qty": child["qty"],
            "is_recipe": child["is_recipe"],
            "path_key": _node_path_key(child, child_path_parts),
            "parent_name": node["name"],
            "parent_index": parent_index,
        }
        if child["is_recipe"]:
            spec.update(
                {
                    "output_qty": child.get("output_qty", 1.0),
                    "recipe_name": child.get("recipe_name"),
                    "alts": child.get("alts", []),
                    "byproducts": child.get("byproducts", []),
                    "station": child.get("station"),
                    "stations": child.get("stations", []),
                    "auto_craft_seconds": child.get("auto_craft_seconds"),
                    "manual_craft_seconds": child.get("manual_craft_seconds"),
                    "craft_mode": child.get("craft_mode", "auto"),
                    "raw_names": [c["name"] for c in child["children"] if not c["is_recipe"]],
                    "crafted_names": [c["name"] for c in child["children"] if c["is_recipe"]],
                }
            )
        my_index = len(specs)
        specs.append(spec)
        _walk_occurrence_specs(child, child_path_parts, my_index, specs)


def filter_unchecked_occurrences(specs, checked):
    """Cheap, checked-state-DEPENDENT pass over an already-built specs
    list (see build_occurrence_specs) - reproduces collect_item_
    occurrences' old prune-at-checked-node semantics (a checked node is
    still recorded, with checked=True, but nothing under it is) via one
    linear pass, since none of a spec's own fields (path_key, metadata)
    change with checked-state - only which specs make it into the result,
    and whether each one is flagged checked, does. `specs` is in DFS pre-
    order with every entry's parent already visited (parent_index < its
    own index), so a single forward pass is enough - no recursion."""
    pruned = [False] * len(specs)
    occurrences = []
    for i, spec in enumerate(specs):
        parent_index = spec["parent_index"]
        if parent_index is not None and pruned[parent_index]:
            pruned[i] = True
            continue
        is_checked = spec["path_key"] in checked
        occurrences.append({**spec, "checked": is_checked})
        pruned[i] = is_checked
    return occurrences


def aggregate_item_occurrences(occurrences):
    """Merge a flat occurrence list (see build_occurrence_specs/filter_unchecked_occurrences) into one
    entry per unique item name - reused identically for both the combined
    "All Jobs" Totals view and a single job's own "Per Recipe" entry (just
    given a smaller occurrences list).

    For each name:
      qty: summed from only its UNCHECKED occurrences - a checked
        occurrence contributes 0 (matches _subtree_remaining_seconds's
        convention), which alone gives the "some but not all occurrences
        checked -> show the remaining amount" semantics.
      fully_checked / any_checked: drive the frontend's tri-state
        checkbox (0 checked = unchecked, all checked = done, some checked
        = indeterminate).
      sources: qty-by-parent-name, unchecked only, sorted by -qty then
        name - the "4 direct + 2 via Titanium Frame" note; the frontend
        only shows this when there's more than one source.
      occurrences: every raw occurrence's {queue_id, path_key, parent_name,
        checked}, unfiltered - the frontend filters this down to just the
        occurrences matching one specific parent_name before round-
        tripping it to Api.set_totals_item_checked, so checking a cross-
        reference row only cascades the slice attributable to ITS parent
        rather than every occurrence of the item everywhere (parent_name/
        checked are also what let a cross-reference row compute its own
        parent-scoped tri-state checkbox, rather than showing the whole
        item's aggregate checked state).
      is_recipe, plus (only if True) output_qty/recipe_name/alts/station/
        stations/auto_craft_seconds/manual_craft_seconds/craft_mode -
        taken from an is_recipe=True occurrence if one exists, else the
        first occurrence (the same name can resolve as a real recipe
        along one ancestor chain but hit resolve_recipe_tree's _visited
        cycle-breaking along another, which would otherwise make this
        metadata depend on occurrence-list ordering); raw_names/
        crafted_names (union across every occurrence - the frontend
        nests a crafted_names lookup under this entry the same way
        raw_names becomes a deposit-location expando, building the actual
        "Option D" merged BOM TREE rather than a flat list) and
        byproducts (summed across only unchecked occurrences, same qty-
        scaling rationale as qty above).
      is_root_demand: whether ANY occurrence (checked or not - this is a
        structural property, not a remaining-quantity one, so checking an
        item off shouldn't reshuffle where it sits in the tree) is a
        direct child of some job's own root (parent_index is None).
      is_shared: whether this name has 2+ DISTINCT parent_names among its
        occurrences (checked or not, same structural rationale as
        is_root_demand) - i.e. genuinely used by more than one thing, not
        just repeated under one. root-demand items and shared items are
        both "promoted" by the frontend (own guaranteed row, own nested
        children) since both have a stable, findable home to give a
        cross-reference a meaningful destination - an item with neither
        property has exactly one real parent, so it just nests there
        directly with nothing to cross-reference at all."""
    by_name = {}
    for occ in occurrences:
        by_name.setdefault(occ["name"], []).append(occ)

    result = {}
    for name, occs in by_name.items():
        unchecked = [o for o in occs if not o["checked"]]
        fully_checked = not unchecked
        any_checked = len(unchecked) < len(occs)

        sources = {}
        for o in unchecked:
            sources[o["parent_name"]] = sources.get(o["parent_name"], 0.0) + o["qty"]
        sources_list = sorted(
            ({"parent_name": p, "qty": q} for p, q in sources.items()),
            key=lambda s: (-s["qty"], s["parent_name"].lower()),
        )

        best = next((o for o in occs if o["is_recipe"]), occs[0])
        entry = {
            "name": name,
            "qty": sum(o["qty"] for o in unchecked),
            "is_recipe": best["is_recipe"],
            "fully_checked": fully_checked,
            "any_checked": any_checked,
            "is_root_demand": any(o["parent_index"] is None for o in occs),
            "is_shared": len({o["parent_name"] for o in occs}) >= 2,
            "sources": sources_list,
            "occurrences": [
                {
                    "queue_id": o["queue_id"],
                    "path_key": o["path_key"],
                    "parent_name": o["parent_name"],
                    "checked": o["checked"],
                }
                for o in occs
            ],
        }
        if best["is_recipe"]:
            raw_names = set()
            crafted_names = set()
            byproducts = {}
            for o in occs:
                raw_names.update(o.get("raw_names", []))
                crafted_names.update(o.get("crafted_names", []))
            for o in unchecked:
                for bp in o.get("byproducts", []):
                    byproducts[bp["name"]] = byproducts.get(bp["name"], 0.0) + bp["qty"]
            entry.update(
                {
                    "output_qty": best.get("output_qty", 1.0),
                    "recipe_name": best.get("recipe_name"),
                    "alts": best.get("alts", []),
                    "station": best.get("station"),
                    "stations": best.get("stations", []),
                    "auto_craft_seconds": best.get("auto_craft_seconds"),
                    "manual_craft_seconds": best.get("manual_craft_seconds"),
                    "craft_mode": best.get("craft_mode", "auto"),
                    "raw_names": sorted(raw_names),
                    "crafted_names": sorted(crafted_names),
                    "byproducts": [
                        {"name": n, "qty": q} for n, q in sorted(byproducts.items())
                    ],
                }
            )
        result[name] = entry
    return result


