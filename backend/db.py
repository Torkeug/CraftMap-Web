"""SQLite data access - copied verbatim from craftmap/overlay.py's
Database + Recipe DB + Craft Queue DB sections. Shares resources.db with
the existing tkinter app; see paths.py.
"""

import sqlite3
from collections import deque

from .paths import DB_PATH


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            res_type TEXT,
            resource TEXT NOT NULL,
            system_name TEXT NOT NULL,
            planet TEXT NOT NULL,
            status TEXT,
            notes TEXT,
            logged_at TEXT
        )
    """)
    # migrations: add columns to older DBs that don't have them yet
    c.execute("PRAGMA table_info(deposits)")
    cols = [row[1] for row in c.fetchall()]
    if "res_type" not in cols:
        c.execute("ALTER TABLE deposits ADD COLUMN res_type TEXT")
    if "sector" not in cols:
        c.execute("ALTER TABLE deposits ADD COLUMN sector TEXT")
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            output_qty REAL NOT NULL DEFAULT 1,
            output_name TEXT
        )
    """)
    c.execute("PRAGMA table_info(recipes)")
    recipe_cols = [row[1] for row in c.fetchall()]
    if "output_qty" not in recipe_cols:
        c.execute("ALTER TABLE recipes ADD COLUMN output_qty REAL NOT NULL DEFAULT 1")
    if "output_name" not in recipe_cols:
        c.execute("ALTER TABLE recipes ADD COLUMN output_name TEXT")
    if "station" not in recipe_cols:
        c.execute("ALTER TABLE recipes ADD COLUMN station TEXT")
    if "auto_craft_seconds" not in recipe_cols:
        c.execute("ALTER TABLE recipes ADD COLUMN auto_craft_seconds REAL")
    if "manual_craft_seconds" not in recipe_cols:
        c.execute("ALTER TABLE recipes ADD COLUMN manual_craft_seconds REAL")
    if "game_craft_id" not in recipe_cols:
        c.execute("ALTER TABLE recipes ADD COLUMN game_craft_id TEXT")
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            ingredient_name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipe_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)
    # backfill: every pre-existing recipe needs at least one recipe_outputs row,
    # mirroring its old single output_qty/output_name columns
    c.execute(
        "SELECT id, COALESCE(output_name, name), output_qty FROM recipes"
        " WHERE id NOT IN (SELECT DISTINCT recipe_id FROM recipe_outputs)"
    )
    for rid, oname, oqty in c.fetchall():
        c.execute(
            "INSERT INTO recipe_outputs (recipe_id, item_name, quantity) VALUES (?, ?, ?)",
            (rid, oname, oqty),
        )
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipe_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            station TEXT NOT NULL,
            auto_craft_seconds REAL,
            manual_craft_seconds REAL,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)
    # backfill: every pre-existing recipe with a station needs at least one
    # recipe_stations row, mirroring its old single station/*_craft_seconds columns
    c.execute(
        "SELECT id, station, auto_craft_seconds, manual_craft_seconds FROM recipes"
        " WHERE station IS NOT NULL AND station != ''"
        " AND id NOT IN (SELECT DISTINCT recipe_id FROM recipe_stations)"
    )
    for rid, station, auto_s, manual_s in c.fetchall():
        c.execute(
            "INSERT INTO recipe_stations (recipe_id, station, auto_craft_seconds, manual_craft_seconds)"
            " VALUES (?, ?, ?, ?)",
            (rid, station, auto_s, manual_s),
        )
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipe_checked (
            recipe_id INTEGER NOT NULL,
            path_key TEXT NOT NULL,
            PRIMARY KEY (recipe_id, path_key),
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipe_alt_prefs (
            ingredient_name TEXT PRIMARY KEY,
            recipe_id INTEGER NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS recipe_station_prefs (
            ingredient_name TEXT PRIMARY KEY,
            station TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'auto'
        )
    """)
    c.execute("PRAGMA table_info(recipe_station_prefs)")
    if "mode" not in [row[1] for row in c.fetchall()]:
        c.execute(
            "ALTER TABLE recipe_station_prefs ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'"
        )
    # Items curated as "actually a raw material" (minable/harvestable in the
    # game, per resource_sources) even though a recipe also exists for them
    # (e.g. Quartz, Hematite - also craftable via a Crystallizer synthesis
    # recipe, but you'd normally just go mine them) - resolve_recipe_tree
    # defaults any of these to raw instead of pulling in their own crafting
    # chain, unless overridden via the normal recipe_alt_prefs mechanism.
    # Deliberately its own curated table rather than "has resource_sources
    # rows": plenty of items with sources (Structural Beam, Wire, Solar
    # Cell, ...) are really salvage-loot of the finished good, not a raw
    # material you'd default to over crafting it.
    c.execute("""
        CREATE TABLE IF NOT EXISTS raw_materials (
            ingredient_name TEXT PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS craft_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id)
        )
    """)
    c.execute("PRAGMA table_info(craft_queue)")
    queue_cols = [row[1] for row in c.fetchall()]
    if "station" not in queue_cols:
        c.execute("ALTER TABLE craft_queue ADD COLUMN station TEXT")
    if "combine" not in queue_cols:
        c.execute("ALTER TABLE craft_queue ADD COLUMN combine INTEGER NOT NULL DEFAULT 1")
    if "station_mode" not in queue_cols:
        c.execute(
            "ALTER TABLE craft_queue ADD COLUMN station_mode TEXT NOT NULL DEFAULT 'auto'"
        )
    c.execute("""
        CREATE TABLE IF NOT EXISTS queue_checked (
            queue_id INTEGER NOT NULL,
            path_key TEXT NOT NULL,
            PRIMARY KEY (queue_id, path_key)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS resource_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_name TEXT NOT NULL,
            source_name TEXT NOT NULL,
            concentration REAL,
            UNIQUE (resource_name, source_name)
        )
    """)
    c.execute("PRAGMA table_info(resource_sources)")
    if "concentration" not in [row[1] for row in c.fetchall()]:
        c.execute("ALTER TABLE resource_sources ADD COLUMN concentration REAL")
    c.execute("""
        CREATE TABLE IF NOT EXISTS galaxy_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_name TEXT NOT NULL,
            planet TEXT NOT NULL,
            sector TEXT,
            resource TEXT NOT NULL,
            node_count INTEGER,
            density REAL,
            poi_tags TEXT,
            poi_area_density REAL,
            is_asteroid INTEGER,
            temperature TEXT,
            temperature_name TEXT,
            attributes TEXT,
            attribute_names TEXT,
            UNIQUE (system_name, planet, resource)
        )
    """)
    c.execute("PRAGMA table_info(galaxy_resources)")
    galaxy_cols = [row[1] for row in c.fetchall()]
    if "poi_tags" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN poi_tags TEXT")
    if "poi_area_density" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN poi_area_density REAL")
    if "is_asteroid" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN is_asteroid INTEGER")
    if "temperature" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN temperature TEXT")
    if "temperature_name" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN temperature_name TEXT")
    if "attributes" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN attributes TEXT")
    if "attribute_names" not in galaxy_cols:
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN attribute_names TEXT")
    c.execute("""
        CREATE TABLE IF NOT EXISTS galaxy_systems (
            system_name TEXT PRIMARY KEY,
            x REAL,
            y REAL,
            z REAL,
            near_system_names TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS galaxy_poi_landmarks (
            system_name TEXT NOT NULL,
            planet TEXT NOT NULL,
            poi_index TEXT NOT NULL,
            landmark_name TEXT,
            indicator_id TEXT,
            sun_side TEXT,
            light_value REAL,
            area REAL,
            UNIQUE (system_name, planet, poi_index)
        )
    """)
    c.execute("PRAGMA table_info(galaxy_poi_landmarks)")
    if "area" not in [row[1] for row in c.fetchall()]:
        c.execute("ALTER TABLE galaxy_poi_landmarks ADD COLUMN area REAL")
    conn.commit()
    conn.close()


def fetch_all(filter_text="", allowed_types=None, order_by="resource"):
    """allowed_types: None = no type filtering, [] = nothing matches, list = only those types
    (rows with empty/NULL res_type are always included so untyped entries don't vanish).
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    base = """
        SELECT id, res_type, resource, sector, system_name, planet, notes, logged_at
        FROM deposits
    """
    where = []
    params = []
    if filter_text:
        like = f"%{filter_text.lower()}%"
        where.append(
            """(lower(resource) LIKE ? OR lower(system_name) LIKE ?
               OR lower(planet) LIKE ? OR lower(notes) LIKE ?
               OR lower(COALESCE(res_type,'')) LIKE ? OR lower(COALESCE(sector,'')) LIKE ?)"""
        )
        params += [like, like, like, like, like, like]
    if allowed_types is not None:
        if len(allowed_types) == 0:
            conn.close()
            return []
        placeholders = ",".join("?" for _ in allowed_types)
        where.append(f"(COALESCE(res_type,'') = '' OR res_type IN ({placeholders}))")
        params += list(allowed_types)
    if where:
        base += " WHERE " + " AND ".join(where)
    if order_by == "location":
        base += (
            " ORDER BY sector COLLATE NOCASE, system_name COLLATE NOCASE,"
            " planet COLLATE NOCASE, res_type COLLATE NOCASE, resource COLLATE NOCASE"
        )
    else:
        base += (
            " ORDER BY res_type COLLATE NOCASE, resource COLLATE NOCASE,"
            " sector COLLATE NOCASE, system_name COLLATE NOCASE, planet COLLATE NOCASE"
        )
    c.execute(base, params)
    rows = c.fetchall()
    conn.close()
    return rows


def distinct_values(column):
    """Pull distinct values already in the DB to power autocomplete dropdowns.
    No hardcoded lists - this grows automatically as you log new entries."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        f"SELECT DISTINCT {column} FROM deposits"
        f" WHERE {column} IS NOT NULL AND {column} != ''"
        f" ORDER BY {column} COLLATE NOCASE"
    )
    vals = [r[0] for r in c.fetchall()]
    conn.close()
    return vals


def insert_row(res_type, resource, sector, system_name, planet, notes, logged_at):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO deposits"
        " (res_type, resource, sector, system_name, planet, notes, logged_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (res_type, resource, sector, system_name, planet, notes, logged_at),
    )
    conn.commit()
    conn.close()


def rename_deposit_resource(old_name, new_name):
    """Bulk-renames every deposits row using old_name to new_name - used by
    tools/fix_resource_name_mismatches.py to reconcile a manually-typed
    resource name with galaxy_resources' own node-type spelling (e.g.
    "Pyrite" -> "Pyrite Formation"), so get_deposits_for_ingredient's
    exact-match LOGGED-pin lookup (see frontend/js/galaxy.js) can find it.
    Returns the number of rows updated."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE deposits SET resource=? WHERE resource=?", (new_name, old_name))
    conn.commit()
    updated = c.rowcount
    conn.close()
    return updated


def update_row(
    row_id, res_type, resource, sector, system_name, planet, notes, logged_at
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE deposits"
        " SET res_type=?, resource=?, sector=?, system_name=?, planet=?,"
        " notes=?, logged_at=? WHERE id=?",
        (
            res_type,
            resource,
            sector,
            system_name,
            planet,
            notes,
            logged_at,
            row_id,
        ),
    )
    conn.commit()
    conn.close()


def delete_row(row_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM deposits WHERE id=?", (row_id,))
    conn.commit()
    conn.close()


def get_deposit(row_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT res_type, resource, sector, system_name, planet, notes"
        " FROM deposits WHERE id=?",
        (row_id,),
    )
    row = c.fetchone()
    conn.close()
    return row


def get_res_type_for_resource(resource_name):
    """The res_type already used by other logged deposits of this exact
    resource name, if any (every resource name observed so far uses
    exactly one res_type consistently - e.g. every 'Quartz' row is
    'Resources', every 'Dense Iron Deposit' row is 'Deposit') - lets a
    quick-add flow like Api.add_galaxy_note infer the right type instead
    of leaving it blank. None if this resource has never been logged
    before."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT res_type FROM deposits WHERE resource=? AND res_type IS NOT NULL"
        " AND res_type != '' LIMIT 1",
        (resource_name,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def find_duplicate_deposit(
    res_type, resource, sector, system_name, planet, exclude_id=None
):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    q = (
        "SELECT id FROM deposits"
        " WHERE COALESCE(res_type,'')=? AND COALESCE(resource,'')=?"
        " AND COALESCE(sector,'')=? AND COALESCE(system_name,'')=?"
        " AND COALESCE(planet,'')=?"
    )
    params = [res_type, resource, sector, system_name, planet]
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(exclude_id)
    cur.execute(q, params)
    row = cur.fetchone()
    conn.close()
    return row


# Columns the galaxy-wide dump (tools/backfill_galaxy_resources.py) can also
# supply suggestions for - it has no res_type column (that's a deposits-only
# user category, e.g. "Ore"/"Deposit"), so a res_type constraint only ever
# narrows the deposits side of the union below.
_GALAXY_DROPDOWN_COLUMNS = {"resource", "sector", "system_name", "planet"}

# Node-type names confirmed (game_data_extract/resource_nodes.json's own
# props.itemType, cross-checked by tools/report_resource_name_mismatches.py)
# to be PlanetResource_Deposit (auto-drilled, no walkable node to visit) -
# this app's own res_type field exists to distinguish exactly this from
# everything else hand-gathered (PlanetResource_RegularNode/Shell/Geyser/
# Exploration), using the values "Deposit" vs "Resources" (see
# Api.add_galaxy_note's own docstring). Not every name is itself "obvious" -
# "Brine Pool"/"Mercury Pool"/"Vitriol Pool" are Deposit-type despite not
# containing the word "Deposit". Static game data, unlikely to change -
# hardcoded rather than reading game_data_extract/ at runtime, same call
# RESOURCE_SIZE_VARIANTS above makes.
DEPOSIT_TYPE_RESOURCE_NAMES = {
    "Aluminum Deposit", "Brine Pool", "Coal Deposit", "Copper Deposit",
    "Dense Aluminum Deposit", "Dense Copper Deposit", "Dense Iron Deposit",
    "Dense Platinum Deposit", "Iron Deposit", "Mercury Pool",
    "Platinum Deposit", "Pyrite Deposit", "Sandstone Deposit",
    "Sulfur Deposit", "Titanium Deposit", "Tungsten Deposit",
    "Vanadium Deposit", "Vitriol Pool",
}


def _is_deposit_type_name(name):
    """True if `name` is a Deposit-type (auto-drilled) node. Handles
    tools/backfill_galaxy_resources.py's composite rows (e.g. "Coal Deposit
    / Iron Deposit / Titanium Deposit") by checking every joined member,
    since composite_rows_for_planet only ever combines resGroups where
    EVERY member is itself Deposit-type."""
    return all(part in DEPOSIT_TYPE_RESOURCE_NAMES for part in name.split(" / "))


def distinct_values_where(column, constraints):
    """Cascading dropdown query - e.g. distinct `system_name` values given a
    chosen `sector`. `constraints` is {column: value}; falsy values are
    ignored so an empty box doesn't over-constrain the query. For
    resource/sector/system_name/planet, unions in galaxy_resources (the
    galaxy-wide dump) alongside the user's own logged `deposits`, so
    autocomplete can prefill correct spellings/values straight from galaxy
    data even before anything's been manually logged.

    When `column` is "resource" and `constraints["res_type"]` is exactly
    "Deposit" or "Resources" (this app's own two mineral categories - see
    DEPOSIT_TYPE_RESOURCE_NAMES), the result is further narrowed to just
    that category, so picking a Type first filters the Resource suggestions
    to match rather than mixing auto-drilled and hand-gathered names
    together. Any other res_type (or none) leaves the result unfiltered -
    DEPOSIT_TYPE_RESOURCE_NAMES has no coverage for non-mineral categories
    like "Plant"/"Shipwreck" anyway."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    active = [(c, v) for c, v in constraints.items() if v]

    q = (
        f"SELECT DISTINCT {column} FROM deposits"
        f" WHERE {column} IS NOT NULL AND {column} != ''"
    )
    params = []
    if active:
        q += " AND " + " AND ".join(f"{c} = ?" for c, _ in active)
        params += [v for _, v in active]

    if column in _GALAXY_DROPDOWN_COLUMNS:
        galaxy_active = [(c, v) for c, v in active if c in _GALAXY_DROPDOWN_COLUMNS]
        gq = (
            f"SELECT DISTINCT {column} FROM galaxy_resources"
            f" WHERE {column} IS NOT NULL AND {column} != ''"
        )
        if galaxy_active:
            gq += " AND " + " AND ".join(f"{c} = ?" for c, _ in galaxy_active)
        q += " UNION " + gq
        params += [v for _, v in galaxy_active]

    q += f" ORDER BY {column} COLLATE NOCASE"
    cur.execute(q, params)
    vals = [row[0] for row in cur.fetchall()]
    conn.close()

    if column == "resource":
        res_type = constraints.get("res_type")
        if res_type == "Deposit":
            vals = [v for v in vals if _is_deposit_type_name(v)]
        elif res_type == "Resources":
            vals = [v for v in vals if not _is_deposit_type_name(v)]

    return vals


# ---------- Recipe DB ----------


def get_all_recipes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name FROM recipes ORDER BY name COLLATE NOCASE")
    rows = c.fetchall()
    conn.close()
    return rows  # [(id, name), ...]


def get_recipe_by_name(name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM recipes WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_recipe_ingredients(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT ingredient_name, quantity FROM recipe_ingredients"
        " WHERE recipe_id=? ORDER BY id",
        (recipe_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def distinct_ingredient_names():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT ingredient_name FROM recipe_ingredients"
        " ORDER BY ingredient_name COLLATE NOCASE"
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_basic_resources():
    """Ingredient names that are never the *primary* output of any recipe -
    i.e. raw materials with no craft chain of their own (mined/gathered, not
    crafted), plus items that are only ever a secondary/byproduct output
    (e.g. Malachite Stone, an 8x byproduct of the Azurite Stone recipe) and
    so have no recipe of their own name to pick in the combo. Lets the
    recipe combo's Used-In lookup work for these too, not just actual
    recipes."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT ingredient_name FROM recipe_ingredients"
        " WHERE ingredient_name NOT IN ("
        "   SELECT item_name FROM recipe_outputs ro"
        "   WHERE ro.id = (SELECT MIN(id) FROM recipe_outputs ro2"
        "                  WHERE ro2.recipe_id = ro.recipe_id)"
        " )"
        " ORDER BY ingredient_name COLLATE NOCASE"
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_recipes_using_ingredient(ingredient_name):
    """Return (recipe_id, recipe_name, qty, output_name, output_qty) for every
    recipe that uses ingredient_name. output_name/output_qty are the recipe's
    primary (first) output."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT r.id, r.name, ri.quantity, ro.item_name, ro.quantity"
        " FROM recipe_ingredients ri"
        " JOIN recipes r ON r.id = ri.recipe_id"
        " JOIN recipe_outputs ro ON ro.recipe_id = r.id"
        " WHERE ri.ingredient_name = ?"
        " AND ro.id = (SELECT MIN(id) FROM recipe_outputs WHERE recipe_id = r.id)"
        " ORDER BY r.name COLLATE NOCASE",
        (ingredient_name,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def save_recipe(
    recipe_id,
    name,
    outputs,
    ingredients,
    stations,
):
    """Insert (recipe_id=None) or update a recipe, replacing its outputs,
    ingredients, and stations. `outputs` is a non-empty list of
    (item_name, qty) tuples; outputs[0] is the primary output. `stations`
    is a non-empty list of (station, auto_craft_seconds, manual_craft_seconds)
    tuples; stations[0] is the primary station. Returns id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    primary_name, primary_qty = outputs[0]
    oname = primary_name if primary_name != name else None
    primary_station, primary_auto_s, primary_manual_s = stations[0]
    if recipe_id is None:
        c.execute(
            "INSERT INTO recipes"
            " (name, output_qty, output_name, station, auto_craft_seconds, manual_craft_seconds)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                primary_qty,
                oname,
                primary_station,
                primary_auto_s,
                primary_manual_s,
            ),
        )
        recipe_id = c.lastrowid
    else:
        c.execute(
            "UPDATE recipes SET name=?, output_qty=?, output_name=?,"
            " station=?, auto_craft_seconds=?, manual_craft_seconds=? WHERE id=?",
            (
                name,
                primary_qty,
                oname,
                primary_station,
                primary_auto_s,
                primary_manual_s,
                recipe_id,
            ),
        )
        c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (recipe_id,))
        c.execute("DELETE FROM recipe_outputs WHERE recipe_id=?", (recipe_id,))
        c.execute("DELETE FROM recipe_stations WHERE recipe_id=?", (recipe_id,))
    for ing_name, qty in ingredients:
        c.execute(
            "INSERT INTO recipe_ingredients (recipe_id, ingredient_name, quantity)"
            " VALUES (?, ?, ?)",
            (recipe_id, ing_name, qty),
        )
    for out_name, out_qty in outputs:
        c.execute(
            "INSERT INTO recipe_outputs (recipe_id, item_name, quantity)"
            " VALUES (?, ?, ?)",
            (recipe_id, out_name, out_qty),
        )
    for st_name, st_auto_s, st_manual_s in stations:
        c.execute(
            "INSERT INTO recipe_stations"
            " (recipe_id, station, auto_craft_seconds, manual_craft_seconds)"
            " VALUES (?, ?, ?, ?)",
            (recipe_id, st_name, st_auto_s, st_manual_s),
        )
    conn.commit()
    conn.close()
    return recipe_id


def get_recipe_name(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM recipes WHERE id=?", (recipe_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""


def get_recipe_output_name(recipe_id):
    """The recipe's primary (first) output item name."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT item_name FROM recipe_outputs WHERE recipe_id=? ORDER BY id LIMIT 1",
        (recipe_id,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""


def get_all_output_names():
    """Distinct item names that recipes produce (including secondary/byproduct
    outputs), for autocomplete."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT item_name FROM recipe_outputs ORDER BY 1 COLLATE NOCASE")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_recipe_output_qty(recipe_id):
    """The recipe's primary (first) output quantity."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT quantity FROM recipe_outputs WHERE recipe_id=? ORDER BY id LIMIT 1",
        (recipe_id,),
    )
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 1.0


def get_recipe_outputs(recipe_id):
    """All of a recipe's outputs, ordered with the primary first."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT item_name, quantity FROM recipe_outputs"
        " WHERE recipe_id=? ORDER BY id",
        (recipe_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_recipe_meta(recipe_id):
    """Return (station, auto_craft_seconds, manual_craft_seconds) for a
    recipe's primary station."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT station, auto_craft_seconds, manual_craft_seconds"
        " FROM recipes WHERE id=?",
        (recipe_id,),
    )
    row = c.fetchone()
    conn.close()
    return row if row else (None, None, None)


def get_recipe_stations(recipe_id):
    """All of a recipe's usable stations, ordered with the primary first."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT station, auto_craft_seconds, manual_craft_seconds"
        " FROM recipe_stations WHERE recipe_id=? ORDER BY id",
        (recipe_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_recipe_station_times(recipe_id, station):
    """Return (auto_craft_seconds, manual_craft_seconds) for one of a
    recipe's stations by name, or None if that recipe has no such station."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT auto_craft_seconds, manual_craft_seconds FROM recipe_stations"
        " WHERE recipe_id=? AND station=? ORDER BY id LIMIT 1",
        (recipe_id, station),
    )
    row = c.fetchone()
    conn.close()
    return tuple(row) if row else None


def get_all_stations():
    """Distinct craft stations already in use, for autocomplete - no hardcoded
    lists, grows automatically as recipes are tagged with a station."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT station FROM recipe_stations ORDER BY station COLLATE NOCASE"
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def delete_recipe(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (recipe_id,))
    c.execute("DELETE FROM recipe_outputs WHERE recipe_id=?", (recipe_id,))
    c.execute("DELETE FROM recipe_stations WHERE recipe_id=?", (recipe_id,))
    c.execute("DELETE FROM recipe_checked WHERE recipe_id=?", (recipe_id,))
    c.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
    conn.commit()
    conn.close()


def get_checked_paths(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT path_key FROM recipe_checked WHERE recipe_id=?", (recipe_id,))
    paths = {row[0] for row in c.fetchall()}
    conn.close()
    return paths


def set_checked_many(recipe_id, path_keys, checked):
    """Set (not toggle) every path_key in path_keys to the same checked
    state in one go - used to cascade a step's checkbox onto its whole
    subtree instead of toggling each descendant individually."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if checked:
        c.executemany(
            "INSERT OR REPLACE INTO recipe_checked (recipe_id, path_key) VALUES (?, ?)",
            [(recipe_id, pk) for pk in path_keys],
        )
    else:
        c.executemany(
            "DELETE FROM recipe_checked WHERE recipe_id=? AND path_key=?",
            [(recipe_id, pk) for pk in path_keys],
        )
    conn.commit()
    conn.close()


def get_raw_material_names():
    """Set of ingredient names curated as "actually a raw material" (see
    init_db's raw_materials table comment) - resolve_recipe_tree defaults
    any of these to raw instead of crafting them, even when a recipe
    exists."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ingredient_name FROM raw_materials")
    names = {row[0] for row in c.fetchall()}
    conn.close()
    return names


def add_raw_material(ingredient_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO raw_materials (ingredient_name) VALUES (?)",
        (ingredient_name,),
    )
    conn.commit()
    conn.close()


def remove_raw_material(ingredient_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM raw_materials WHERE ingredient_name=?", (ingredient_name,))
    conn.commit()
    conn.close()


def get_alt_prefs():
    """Return {ingredient_name: recipe_id} of user-chosen alternate recipes."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ingredient_name, recipe_id FROM recipe_alt_prefs")
    prefs = dict(c.fetchall())
    conn.close()
    return prefs


def set_alt_pref(ingredient_name, recipe_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO recipe_alt_prefs (ingredient_name, recipe_id) VALUES (?, ?)",
        (ingredient_name, recipe_id),
    )
    conn.commit()
    conn.close()


def clear_alt_pref(ingredient_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM recipe_alt_prefs WHERE ingredient_name=?", (ingredient_name,)
    )
    conn.commit()
    conn.close()


def get_station_prefs():
    """Return {ingredient_name: (station, mode)} of user-chosen preferred
    crafting stations and craft mode ('auto'/'manual'), same idea as
    get_alt_prefs but for which station/mode (rather than which alternate
    recipe) to use for an ingredient."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ingredient_name, station, mode FROM recipe_station_prefs")
    prefs = {name: (station, mode) for name, station, mode in c.fetchall()}
    conn.close()
    return prefs


def set_station_pref(ingredient_name, station, mode="auto"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO recipe_station_prefs (ingredient_name, station, mode)"
        " VALUES (?, ?, ?)",
        (ingredient_name, station, mode),
    )
    conn.commit()
    conn.close()


def clear_station_pref(ingredient_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM recipe_station_prefs WHERE ingredient_name=?", (ingredient_name,)
    )
    conn.commit()
    conn.close()


def get_deposits_for_ingredient(resource_name):
    """Deposit locations for a resource, including each one's own id/notes -
    frontend/js/galaxy.js uses notes to show what you wrote down for an
    already-logged planet."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, COALESCE(sector,''), system_name, planet, notes"
        " FROM deposits"
        " WHERE resource = ?"
        " ORDER BY sector COLLATE NOCASE, system_name COLLATE NOCASE, planet COLLATE NOCASE",
        (resource_name,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


# ---------- Craft Queue DB ----------


def get_craft_queue():
    """Return [(queue_id, recipe_id, recipe_name, output_name, quantity,
    station, combine, station_mode), ...]. output_name is the recipe's
    primary (first) output. station is the station chosen for this job
    (None = the recipe's primary/default station); station_mode is which of
    that station's auto/manual times to use. combine is whether this job's
    numbers count toward the Totals view's combined "All Jobs" aggregate."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT cq.id, cq.recipe_id, r.name, ro.item_name, cq.quantity,"
        " cq.station, cq.combine, cq.station_mode"
        " FROM craft_queue cq"
        " JOIN recipes r ON r.id = cq.recipe_id"
        " JOIN recipe_outputs ro ON ro.recipe_id = r.id"
        " WHERE ro.id = (SELECT MIN(id) FROM recipe_outputs WHERE recipe_id = r.id)"
        " ORDER BY cq.id"
    )
    rows = c.fetchall()
    conn.close()
    return rows


def add_to_queue(recipe_id, quantity=1.0, station=None):
    """Add a job, merging into an existing queue entry for the same recipe
    AND station (bumping its quantity) instead of creating a duplicate row -
    queuing a recipe/station that's already queued should read as "craft
    more of it", not a second identical entry, and this also preserves that
    entry's checked ingredient state instead of resetting it in a fresh row.
    The same recipe queued at a *different* station is a distinct job."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, quantity FROM craft_queue WHERE recipe_id=? AND station IS ?",
        (recipe_id, station),
    )
    existing = c.fetchone()
    if existing:
        queue_id, existing_qty = existing
        c.execute(
            "UPDATE craft_queue SET quantity=? WHERE id=?",
            (existing_qty + quantity, queue_id),
        )
    else:
        c.execute(
            "INSERT INTO craft_queue (recipe_id, quantity, station) VALUES (?, ?, ?)",
            (recipe_id, quantity, station),
        )
        queue_id = c.lastrowid
    conn.commit()
    conn.close()
    return queue_id


def update_queue_qty(queue_id, quantity):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE craft_queue SET quantity=? WHERE id=?", (quantity, queue_id))
    conn.commit()
    conn.close()


def update_queue_station(queue_id, station, mode="auto"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE craft_queue SET station=?, station_mode=? WHERE id=?",
        (station, mode, queue_id),
    )
    conn.commit()
    conn.close()


def update_queue_combine(queue_id, combine):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE craft_queue SET combine=? WHERE id=?", (1 if combine else 0, queue_id)
    )
    conn.commit()
    conn.close()


def remove_from_queue(queue_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM queue_checked WHERE queue_id=?", (queue_id,))
    c.execute("DELETE FROM craft_queue WHERE id=?", (queue_id,))
    conn.commit()
    conn.close()


def get_queue_checked(queue_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT path_key FROM queue_checked WHERE queue_id=?", (queue_id,))
    paths = {row[0] for row in c.fetchall()}
    conn.close()
    return paths


def clear_queue_checked(queue_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM queue_checked WHERE queue_id=?", (queue_id,))
    conn.commit()
    conn.close()


# ---------- Resource sources (dedicated Sources tab) ----------


def get_resource_sources(resource_name):
    """(source_name, concentration) pairs for the node types that yield a
    given raw resource - distinct from `deposits`, which tracks specific
    manually-logged in-game locations, not general node-type categories.
    `concentration` is what % of that node's primary-yield rolls land on
    this resource (its proba weight vs its kind-0 sibling items', from the
    game's own resource-generation data - see
    tools/backfill_resource_sources.py); None for hand-entered rows with no
    game-data match. Highest concentration first (best sources first), then
    name for ties/nulls."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT source_name, concentration FROM resource_sources"
        " WHERE resource_name=?"
        " ORDER BY concentration IS NULL, concentration DESC, source_name COLLATE NOCASE",
        (resource_name,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def set_resource_sources(resource_name, sources):
    """Replace the full set of source nodes for a resource in one go - same
    replace-all-on-save pattern as save_recipe's ingredients/outputs.
    `sources` is a list of (source_name, concentration) tuples;
    concentration may be None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM resource_sources WHERE resource_name=?", (resource_name,))
    deduped = {}
    for name, conc in sources:
        name = name.strip()
        if name:
            deduped[name] = conc
    c.executemany(
        "INSERT OR IGNORE INTO resource_sources"
        " (resource_name, source_name, concentration) VALUES (?, ?, ?)",
        [(resource_name, n, c_) for n, c_ in deduped.items()],
    )
    conn.commit()
    conn.close()


def get_all_resource_source_names():
    """Distinct source node names already logged, for autocomplete."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT source_name FROM resource_sources ORDER BY source_name COLLATE NOCASE"
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_resources_with_sources():
    """Distinct resource names that have at least one source node logged -
    for the Sources tab's own resource combo."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT resource_name FROM resource_sources ORDER BY resource_name COLLATE NOCASE"
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------- Galaxy resources (tools/backfill_galaxy_resources.py) ----------


def get_galaxy_resource_keys():
    """Existing (system_name, planet, resource) triples already imported -
    lets the backfill tool report what a re-run would add without writing
    anything (--dry-run)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT system_name, planet, resource FROM galaxy_resources")
    keys = set(c.fetchall())
    conn.close()
    return keys


def get_galaxy_resource_names():
    """Distinct node-type names known to galaxy_resources, for the Galaxy
    sub-tab's own autocomplete - a node-type namespace (matches
    resource_sources' own source_name column), not raw materials, since
    every row here comes from a live per-node placement count."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT resource FROM galaxy_resources ORDER BY resource COLLATE NOCASE")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def import_galaxy_resources(rows):
    """Bulk INSERT OR IGNORE galaxy_resources rows. `rows` is a list of
    (system_name, planet, sector, resource, node_count, density, poi_tags,
    poi_area_density, is_asteroid, temperature, temperature_name, attributes,
    attribute_names) tuples - poi_tags is a comma-joined string of which
    POI(s) that resource is tied to on that planet (e.g. "poi0",
    "poi0,poi1"), "general" if it's scattered planet-wide with no POI
    anchor, or "poi0,general" if it's split between both. poi_area_density
    is `density` divided by the POI(s)' own combined surface-area fraction
    (see tools/backfill_galaxy_resources.py's poi_surface) - only
    computable, and only ever set, when the resource is PURELY POI-anchored
    (no "general" entry) and every POI it's tied to has a known size; None
    otherwise. Deliberately built from `density`, not raw node_count, so it
    stays on the SAME scale as a "general" resource's own `density` - the
    game's own generation formula never applies this area scaling to
    non-POI resources at all, i.e. implicitly treats "general" as area-
    fraction 1, so this is a fair, directly comparable number, not a
    different unit. is_asteroid (0/1/None) distinguishes an ent.Asteroid
    debris field from a regular ent.Planet - both show up in the same
    per-planet dump entries, and asteroid field names (e.g. "PHY-AF1") are
    otherwise the only clue. temperature/temperature_name are the planet's
    resolved temperature attribute (e.g. "PlanetHot2"/"Very Hot" - always
    set, defaults to "PlanetTemperate"/"Temperate"); attributes/
    attribute_names are comma-joined lists of ALL of the planet's raw
    generation-time attributes (e.g. water presence, radioactive, foggy -
    temperature is one possible member of this same list, duplicated into
    its own columns since it's the one every planet always resolves to).
    These four are planet-level, not resource-level, so they repeat across
    every resource row for the same planet - same treatment as system_name/
    sector already get. Existing rows are left alone
    (UNIQUE(system_name, planet, resource)), so re-running an import after
    further in-game exploration only adds new ones. Returns the number of
    rows actually inserted."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT OR IGNORE INTO galaxy_resources"
        " (system_name, planet, sector, resource, node_count, density, poi_tags,"
        " poi_area_density, is_asteroid, temperature, temperature_name,"
        " attributes, attribute_names)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    inserted = conn.total_changes
    conn.close()
    return inserted


# Some resources are the same underlying deposit as another, just a bigger
# node that yields more per gather - confirmed via data.cdb's `resource`
# sheet: each variant's own row has an explicit `props.linkedResource`
# pointing at the base id, and an empty `items` list (it inherits the
# base's yield table rather than defining its own, e.g. "Big Coal Clump"
# has no items of its own - it IS Coal Clump, just a bigger node). 13 real
# pairs found (a handful of other linkedResource entries point at
# themselves - a no-op, not a family). Static game data, unlikely to
# change - hardcoded rather than adding a runtime dependency on
# game_data_extract/, which backend/db.py otherwise never reads directly
# (see CLAUDE.md - those files are backfill-time-only inputs).
RESOURCE_SIZE_VARIANTS = {
    "Big Ferrous Outcrop": "Ferrous Outcrop",
    "Big Magnetite": "Magnetite",
    "Big Brassy Outcrop": "Brassy Outcrop",
    "Big Coal Clump": "Coal Clump",
    "Huge Titanite": "Titanite",
    "Huge Plagnetite": "Plagnetite",
    "Big Cooperite": "Cooperite",
    "Big Uraninite Outcrop": "Uraninite Outcrop",
    "Big Titanomagnetite": "Titanomagnetite",
    "Big Augurite": "Augurite",
    "Big Bauxite Rock": "Bauxite Rock",
    "Big Wolframite": "Wolframite",
    "Huge Basalt Shell": "Basalt Shell",
}


def _resource_family(resource_name):
    """All resource names representing the same underlying deposit as
    resource_name (itself included) - see RESOURCE_SIZE_VARIANTS. Works
    whether called with the base name or a size-variant's own name."""
    base = RESOURCE_SIZE_VARIANTS.get(resource_name, resource_name)
    family = {base}
    family.update(name for name, b in RESOURCE_SIZE_VARIANTS.items() if b == base)
    return sorted(family)


def get_galaxy_sources_for_resource(resource_name, include_asteroids=True):
    """Every known planet with this resource OR any of its known size-
    variant siblings (see RESOURCE_SIZE_VARIANTS - e.g. querying "Coal
    Clump" also pulls in a planet's "Big Coal Clump" rows, since it's the
    same deposit; a player doesn't make two separate trips just because
    part of a deposit happens to be the bigger node-size variant), combined
    per planet into one row: node_count and density are summed (valid -
    density is linearly proportional to count for a fixed planet, see
    tools/backfill_galaxy_resources.py, so summing densities equals summing
    counts then rescaling once), poi_tags is the union of every
    contributing row's tags. poi_area_density is only re-combined (summed)
    when every contributing row shares the EXACT same poi_tags string (same
    POI footprint, so the same area denominator) - otherwise it's left None
    and the combined row falls back to combined density, same as any other
    genuinely mixed-portion row.

    Sorted by "effective density" descending: `poi_area_density` when set,
    otherwise plain `density` - both on the same scale (see
    import_galaxy_resources), so this is a fair single ranking, not an
    arbitrary pure-POI-first override. Each row is also annotated with
    pure_poi (True if poi_tags is set with no "general" entry).
    include_asteroids=False filters out ent.Asteroid debris fields, keeping
    only regular numbered planets.

    Also annotated with poi_landmarks (list of {poi_index, name,
    indicator_id, sun_side, light_value} dicts, one per POI this row's own
    poi_tags references - see import_galaxy_poi_landmarks; every in-game POI
    has a landmark, one of 3 kinds, confirmed by checking that poiSizes and
    poiLandmarks share the exact same index set for every planet in the
    live dump - so this is empty only for a "general"-only row with no POI
    anchor at all, never for a genuinely POI-anchored one) and poi_sun_states
    (sorted list of the distinct sun_side values among those landmarks, e.g. ["day"],
    ["day", "night"] for a row split across POIs with different lighting,
    or [] when this row has no landmark data at all - the frontend's
    day/night/twilight filter chips are driven directly off this list, see
    js/galaxy.js's chipsForRow).

    Returns (system_name, planet, sector, node_count, density, poi_tags,
    pure_poi, poi_area_density, is_asteroid, temperature, temperature_name,
    attributes, attribute_names, poi_landmarks, poi_sun_states) tuples."""
    family = _resource_family(resource_name)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ",".join("?" for _ in family)
    query = (
        "SELECT system_name, planet, sector, node_count, density, poi_tags,"
        " poi_area_density, is_asteroid, temperature, temperature_name,"
        f" attributes, attribute_names FROM galaxy_resources WHERE resource IN ({placeholders})"
    )
    params = list(family)
    if not include_asteroids:
        query += " AND is_asteroid IS NOT 1"
    c.execute(query, params)
    rows = c.fetchall()

    # Small table (bounded by known-planet count, a handful of landmarks
    # each) - loaded whole rather than filtered per-planet in SQL, same
    # "combine in Python" style already used for `rows` above.
    c.execute(
        "SELECT system_name, planet, poi_index, landmark_name, indicator_id,"
        " sun_side, light_value, area FROM galaxy_poi_landmarks"
    )
    landmarks_by_planet = {}
    for (system_name, planet, poi_index, landmark_name, indicator_id, sun_side, light_value, area) in c.fetchall():
        landmarks_by_planet.setdefault((system_name, planet), {})[poi_index] = {
            "poi_index": poi_index,
            "name": landmark_name,
            "indicator_id": indicator_id,
            "sun_side": sun_side,
            "light_value": light_value,
            "area": area,
        }
    conn.close()

    def is_pure_poi(poi_tags):
        return bool(poi_tags) and "general" not in poi_tags.split(",")

    combined = {}
    for (
        system_name, planet, sector, node_count, density, poi_tags,
        poi_area_density, is_asteroid, temperature, temperature_name,
        attributes, attribute_names,
    ) in rows:
        entry = combined.setdefault((system_name, planet), {
            "sector": sector, "node_count": 0, "density": 0.0,
            "poi_tag_labels": set(), "poi_tags_seen": set(),
            "poi_area_densities": [], "is_asteroid": is_asteroid,
            "temperature": temperature, "temperature_name": temperature_name,
            "attributes": attributes, "attribute_names": attribute_names,
        })
        entry["node_count"] += node_count or 0
        entry["density"] += density or 0.0
        entry["poi_tags_seen"].add(poi_tags)
        if poi_tags:
            entry["poi_tag_labels"].update(poi_tags.split(","))
        if poi_area_density is not None:
            entry["poi_area_densities"].append(poi_area_density)

    annotated = []
    for (system_name, planet), entry in combined.items():
        poi_tags = ",".join(sorted(entry["poi_tag_labels"])) if entry["poi_tag_labels"] else None
        poi_area_density = (
            sum(entry["poi_area_densities"])
            if len(entry["poi_tags_seen"]) == 1 and entry["poi_area_densities"]
            else None
        )
        planet_landmarks = landmarks_by_planet.get((system_name, planet), {})
        poi_landmarks = [
            planet_landmarks[tag] for tag in sorted(entry["poi_tag_labels"])
            if tag in planet_landmarks
        ]
        poi_sun_states = sorted({lm["sun_side"] for lm in poi_landmarks if lm["sun_side"]})
        annotated.append((
            system_name, planet, entry["sector"], entry["node_count"],
            entry["density"], poi_tags, is_pure_poi(poi_tags), poi_area_density,
            bool(entry["is_asteroid"]), entry["temperature"], entry["temperature_name"],
            entry["attributes"], entry["attribute_names"], poi_landmarks, poi_sun_states,
        ))

    # KNOWN RANKING LIMITATION: a "general,poiN" (mixed) row and a pure-
    # "general" row of equal plain `density` rank IDENTICALLY here, even
    # though the mixed row has a real advantage (part of its total IS
    # reachable at a walkable POI) - poi_area_density is None for both (see
    # the loop above), so both fall back to plain density with no way to
    # credit the mixed row's POI portion. This isn't a bug to fix so much
    # as a hard ceiling: the live-memory dump never records how a planet's
    # total density splits between its general and POI portions (only
    # THAT a POI is involved, via poi_tags) - see this function's own
    # docstring and tools/backfill_galaxy_resources.py's load_rows. Only
    # mitigation currently in place: js/galaxy.js's poiState gives mixed
    # rows their own ◐ mark (vs · for pure-general) so this distinction is
    # at least visible, even though it isn't priced into the sort.
    annotated.sort(key=lambda r: -((r[7] if r[7] is not None else r[4]) or 0))
    return annotated


# ---- Galaxy systems (jump-hop distance - tools/backfill_galaxy_resources.py) ----
# Separate from galaxy_resources: systemPosition/nearSystemNames are
# system-level facts carried on EVERY planet entry in the dump, including
# planets with no resourceCounts at all (galaxy_resources only ever gets
# rows for planets that DO have live counts - see import_galaxy_resources) -
# a system with no mineral data can still be a real hop on the way to one
# that does, so it needs to exist here even when it has no galaxy_resources
# rows of its own.


def import_galaxy_systems(rows):
    """Bulk INSERT OR REPLACE galaxy_systems rows - `rows` is a list of
    (system_name, x, y, z, near_system_names) tuples, near_system_names a
    comma-joined list of directly jump-connected neighbor system names.
    REPLACE (not IGNORE, unlike import_galaxy_resources) since a system's
    own neighbor list can grow as more jump lanes are discovered around it
    over further play - re-running the backfill should pick up the latest
    known connectivity, not freeze on whatever was known the first time
    that system was ever seen."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT OR REPLACE INTO galaxy_systems (system_name, x, y, z, near_system_names)"
        " VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def import_galaxy_poi_landmarks(rows):
    """Bulk INSERT OR REPLACE galaxy_poi_landmarks rows - `rows` is a list
    of (system_name, planet, poi_index, landmark_name, indicator_id,
    sun_side, light_value, area) tuples, one per POI (every in-game POI has
    a landmark - see tools/backfill_galaxy_resources.py's
    load_poi_landmark_rows for the empirical confirmation). poi_index is
    the same "poiN" string used by galaxy_resources.poi_tags (same index
    space, confirmed in the dump), so a resource row's poi_tags can be
    matched directly against this table's poi_index without any
    translation - see get_galaxy_sources_for_resource. sun_side is
    "day"/"night"/"twilight", light_value the raw signed value it was
    thresholded from (see the sibling spacecraft-memory-research repo's
    classify_light) - planets don't rotate in this game, so this is a
    stable per-POI fact, not a stale snapshot. area is this POI's own
    surface-area fraction of the planet (tools/backfill_galaxy_resources.py's
    poi_surface(poiSizes[poi_index]), same conversion import_galaxy_resources'
    poi_area_density already uses, just kept per-POI instead of pre-combined
    across a whole row's footprint) - None when this POI's size wasn't
    known at import time. Used by js/galaxy.js's survivingAreaFraction to
    estimate how much of a row's density is still "reachable" once some of
    its POIs are excluded by the lighting filter - see that function's own
    comment for why a per-POI area (not a raw count) is what's needed for a
    meaningful estimate. REPLACE (not IGNORE, like import_galaxy_systems)
    since re-running the backfill after further exploration should pick up
    freshly-observed landmarks/lighting rather than freeze on whatever was
    first seen."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT OR REPLACE INTO galaxy_poi_landmarks"
        " (system_name, planet, poi_index, landmark_name, indicator_id, sun_side, light_value, area)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_galaxy_system_names():
    """Every system with known position/neighbor data - for the Galaxy
    sub-tab's "current system" autocomplete. Broader than
    get_galaxy_resource_names' own system_name column (that's scoped to
    whatever resource is currently selected) - this covers every system
    the player has ever passed through, resource data or not."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT system_name FROM galaxy_systems ORDER BY system_name COLLATE NOCASE")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def get_galaxy_hop_distances(from_system):
    """Plain BFS over the galaxy_systems jump-connection graph, starting at
    from_system. Returns {system_name: hop_count} for every system
    reachable from it (from_system itself maps to 0); a system not present
    in the returned dict simply hasn't been confirmed reachable through
    explored jump lanes yet. Edges are treated as bidirectional - a jump
    lane works both ways in-game even if the dump only captured the
    connection from one side's own nearSystemNames. Returns {} if
    from_system isn't a known system at all."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT system_name, near_system_names FROM galaxy_systems")
    graph = {}
    for name, neighbors in c.fetchall():
        graph.setdefault(name, set())
        if neighbors:
            for neighbor in neighbors.split(","):
                graph[name].add(neighbor)
                graph.setdefault(neighbor, set()).add(name)
    conn.close()

    if from_system not in graph:
        return {}
    dist = {from_system: 0}
    queue = deque([from_system])
    while queue:
        current = queue.popleft()
        for neighbor in graph[current]:
            if neighbor not in dist:
                dist[neighbor] = dist[current] + 1
                queue.append(neighbor)
    return dist


def set_queue_checked_many(queue_id, path_keys, checked):
    """Set (not toggle) every path_key in path_keys to the same checked
    state in one go - used to cascade a step's checkbox onto its whole
    subtree instead of toggling each descendant individually."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if checked:
        c.executemany(
            "INSERT OR REPLACE INTO queue_checked (queue_id, path_key) VALUES (?, ?)",
            [(queue_id, pk) for pk in path_keys],
        )
    else:
        c.executemany(
            "DELETE FROM queue_checked WHERE queue_id=? AND path_key=?",
            [(queue_id, pk) for pk in path_keys],
        )
    conn.commit()
    conn.close()


