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
):
    """
    Recursively build a breakdown tree for `name`.
    Returns: {'name', 'qty', 'is_recipe', 'output_qty', 'recipe_name', 'children',
              'alts', 'byproducts', 'station', 'auto_craft_seconds',
              'manual_craft_seconds', 'stations'}
    'alts' lists every other recipe producing the same output — shown as collapsible branches.
    'byproducts' lists this recipe's other outputs (besides `name`), scaled to
    the same craft count — populated for multi-output recipes.
    'stations' lists every usable station for this node's recipe (station,
    auto_craft_seconds, manual_craft_seconds), so the UI can offer a picker.
    _root_recipe_id: forces a specific recipe at the top level (for alternate recipe views).
    _alt_prefs: {ingredient_name: recipe_id} of user-selected alternate recipes.
    _station_prefs: {ingredient_name: station} of user-selected preferred stations.
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
            )
            children.append(child)
        # Find every other recipe that produces the same output
        for alt_rid, alt_rname, alt_oqty in (_alts_by_output or {}).get(
            actual_output, []
        ):
            if alt_rid == recipe_id:
                continue
            alt_crafts = math.ceil(qty_needed / alt_oqty)
            alt_outputs = _outputs_by_recipe.get(alt_rid, [(actual_output, alt_oqty)])
            alt_byproducts = [
                {"name": n, "qty": alt_crafts * q}
                for n, q in alt_outputs
                if n != actual_output
            ]
            alt_children = []
            for ing_name, ing_qty in _ing_map.get(alt_rid, []):
                alt_child = resolve_recipe_tree(
                    ing_name,
                    alt_crafts * ing_qty,
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
                )
                alt_children.append(alt_child)
            alts.append(
                {
                    "recipe_id": alt_rid,
                    "recipe_name": alt_rname,
                    "output_qty": alt_oqty,
                    "children": alt_children,
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


