"""SQLite data access - copied verbatim from craftmap/overlay.py's
Database + Recipe DB + Craft Queue DB sections. Shares resources.db with
the existing tkinter app; see paths.py.
"""

import sqlite3

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
    conn.commit()
    conn.close()


def fetch_all(filter_text="", allowed_types=None, order_by="resource"):
    """allowed_types: None = no type filtering, [] = nothing matches, list = only those types
    (rows with empty/NULL res_type are always included so untyped entries don't vanish).
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    base = """
        SELECT id, res_type, resource, sector, system_name, planet, status, notes, logged_at
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


def insert_row(
    res_type, resource, sector, system_name, planet, status, notes, logged_at
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO deposits"
        " (res_type, resource, sector, system_name, planet, status, notes, logged_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (res_type, resource, sector, system_name, planet, status, notes, logged_at),
    )
    conn.commit()
    conn.close()


def update_row(
    row_id, res_type, resource, sector, system_name, planet, status, notes, logged_at
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE deposits"
        " SET res_type=?, resource=?, sector=?, system_name=?, planet=?,"
        " status=?, notes=?, logged_at=? WHERE id=?",
        (
            res_type,
            resource,
            sector,
            system_name,
            planet,
            status,
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
        "SELECT res_type, resource, sector, system_name, planet, status, notes"
        " FROM deposits WHERE id=?",
        (row_id,),
    )
    row = c.fetchone()
    conn.close()
    return row


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


def distinct_values_where(column, constraints):
    """Cascading dropdown query - e.g. distinct `system_name` values given a
    chosen `sector`. `constraints` is {column: value}; falsy values are
    ignored so an empty box doesn't over-constrain the query."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    active = [(c, v) for c, v in constraints.items() if v]
    q = (
        f"SELECT DISTINCT {column} FROM deposits"
        f" WHERE {column} IS NOT NULL AND {column} != ''"
    )
    if active:
        q += " AND " + " AND ".join(f"{c} = ?" for c, _ in active)
    q += f" ORDER BY {column} COLLATE NOCASE"
    cur.execute(q, [v for _, v in active])
    vals = [row[0] for row in cur.fetchall()]
    conn.close()
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
    """Deposit locations for a resource, excluding Claimed."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(sector,''), system_name, planet, COALESCE(status,'')"
        " FROM deposits"
        " WHERE resource = ? AND COALESCE(status,'') != 'Claimed'"
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


