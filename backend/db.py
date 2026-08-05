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
    resource_sources_cols = [row[1] for row in c.fetchall()]
    if "concentration" not in resource_sources_cols:
        c.execute("ALTER TABLE resource_sources ADD COLUMN concentration REAL")
    if "expected_qty" not in resource_sources_cols:
        c.execute("ALTER TABLE resource_sources ADD COLUMN expected_qty REAL")
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
            planet_scale REAL,
            explored INTEGER,
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
    if "planet_scale" not in galaxy_cols:
        # planet.inf.props.scale (see tools/backfill_galaxy_resources.py's
        # own docstring and get_galaxy_sources_for_resource's general_value
        # derivation) - NULL for any row imported before this column
        # existed; treated as 1.0 (the common/default scale) wherever read,
        # not an error.
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN planet_scale REAL")
    if "explored" not in galaxy_cols:
        # game.me.progress.systems, decoded per-planet by the sibling
        # spacecraft-memory-research repo's dump_galaxy_resources.py - THIS
        # player's own, personal "have I explored this" flag (distinct from
        # resourcesGenerated/shared quadrant state). NULL for any row
        # imported before this column existed, or where the dump itself
        # didn't have it - treated as "unknown", not "unexplored", wherever
        # read (see get_galaxy_sources_for_resource).
        c.execute("ALTER TABLE galaxy_resources ADD COLUMN explored INTEGER")
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
    # Live shipwreck-hull/crate sighting log - see the sibling
    # spacecraft-memory-research repo's live_tracker.py (a long-running
    # poller, not a one-shot dump like dump_galaxy_resources.py) and
    # tools/import_wreck_events.py, which reads its event_log_db (SQLite,
    # `wreck_events` table - migrated 2026-08-04 off an earlier
    # wreck_events.jsonl, see that repo's RESEARCH_LOG.md) into this
    # table. Deliberately an EVENT LOG (one row per sighting/loot/
    # despawn), not a live-position table: unlike galaxy_resources (exact
    # counts that stay true once recorded), a wreck's exact position goes
    # stale the moment it despawns or gets looted - CRAFTMAP_INTEGRATION.md
    # covers why that's the wrong shape for a durable SQLite table (the
    # LIVE, right-now position instead lives in live_tracker.py's own
    # overwritten JSON snapshot file, read directly, never imported here).
    # This table only ever answers "what have I seen over time" (counts/
    # stats), not "what's there right now". resource_id is one of
    # ShipWreck_Lvl0/1/2 (the wreck body/site) or
    # ShipWreck_LootChestRare_lvl0/1/2 (crates) - see live_tracker.py's
    # own scope note for why every other wreck-family resourceId (scrap/
    # junk) is deliberately never logged here. sector is NOT stored here -
    # resolved via a lookup against galaxy_resources at query time (see
    # get_wreck_stats), since deriving it live would need the same
    # full-galaxy voting pass dump_galaxy_resources.py runs, which the
    # lightweight poller deliberately doesn't duplicate. wreck_size/
    # wreck_tier (added alongside the SQLite migration) come straight from
    # the sibling repo's own annotate_wreck_size_tier - NULL for events
    # logged before that existed, or wherever it couldn't resolve either
    # axis for a given wreck. parent_id (added right after, same session -
    # raised directly by the user: per-resource_id counting fragments ONE
    # Big wreck sighting into up to 4 stat rows, since a Big wreck's hull
    # is BigPiece1/BigPiece2/SmallPiece1/SmallPiece2, four separate
    # resource_ids) is the sibling repo's live parentId - every hull piece
    # of the SAME wreck shares it, so COUNT(DISTINCT parent_id) gives the
    # actual number of wreck SITES, not hull-piece sightings. NULL for
    # anything logged before this column existed - see get_wreck_site_stats.
    # Not a durable cross-session wreck identity (see the sibling repo's
    # own docstring on this) - only guaranteed stable within one continuous
    # scan, which is exactly what's needed since a wreck's pieces are all
    # discovered in the same poll cycle.
    c.execute("""
        CREATE TABLE IF NOT EXISTS wreck_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_name TEXT NOT NULL,
            planet TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            wreck_size TEXT,
            wreck_tier INTEGER,
            parent_id INTEGER,
            x REAL,
            y REAL,
            z REAL,
            observed_at TEXT NOT NULL,
            UNIQUE (system_name, planet, resource_id, event_type, observed_at, x, y, z)
        )
    """)
    c.execute("PRAGMA table_info(wreck_events)")
    wreck_event_cols = [row[1] for row in c.fetchall()]
    if "wreck_size" not in wreck_event_cols:
        c.execute("ALTER TABLE wreck_events ADD COLUMN wreck_size TEXT")
    if "wreck_tier" not in wreck_event_cols:
        c.execute("ALTER TABLE wreck_events ADD COLUMN wreck_tier INTEGER")
    if "parent_id" not in wreck_event_cols:
        c.execute("ALTER TABLE wreck_events ADD COLUMN parent_id INTEGER")
    # Cursor into the sibling repo's event_log_db wreck_events table, so
    # backend/wreck_import.py only ever re-reads rows NEWER than the last
    # imported id instead of the whole table every time - added after the
    # live HUD window started polling get_live_wreck_snapshot (and thus
    # this import) at 5Hz, at which point "just reread everything, it's
    # small" stopped being a safe assumption for a long-running session.
    # Keyed by source_db_path (not a fixed single row) in case a different
    # source db path ever gets configured. Was byte_offset into a JSONL
    # file (columns source_path/byte_offset) before the 2026-08-04 SQLite
    # migration - last_id (an AUTOINCREMENT id in the SOURCE db, not this
    # one) replaces it end-to-end. SAME table name, though, so `CREATE
    # TABLE IF NOT EXISTS` alone is a no-op against an already-existing
    # old-schema table (confirmed live: this crashed a real import with
    # "no such column: last_id" - the table existed, just with the wrong
    # columns) - needs an explicit drop first. Safe to just drop rather
    # than migrate the old byte_offset value: it's meaningless once the
    # source changed from a flat file to a row-id-keyed db, and a fresh
    # cursor simply re-imports everything from last_id=0, which
    # wreck_events' own UNIQUE constraint + INSERT OR IGNORE already makes
    # idempotent even for rows already imported under the old scheme.
    c.execute("PRAGMA table_info(wreck_event_import_cursor)")
    cursor_cols = [row[1] for row in c.fetchall()]
    if cursor_cols and "last_id" not in cursor_cols:
        c.execute("DROP TABLE wreck_event_import_cursor")
    c.execute("""
        CREATE TABLE IF NOT EXISTS wreck_event_import_cursor (
            source_db_path TEXT PRIMARY KEY,
            last_id INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Exact, on-planet-confirmed per-POI resource node counts - see the
    # sibling spacecraft-memory-research repo's live_tracker.py (extended
    # to also aggregate ordinary resource nodes by POI membership, not just
    # wreck/crate tracking - see its own module docstring's "EXACT PER-POI
    # RESOURCE NODE COUNTS" section) and CRAFTMAP_INTEGRATION.md's matching
    # section there. Strictly BETTER ground truth than galaxy_resources.
    # poi_tags (which only says WHICH POI(s) a resource is tied to, never
    # the per-POI split) but only available for planets actually visited
    # (in a ship or on foot - same Game.lastPlanet-gated scope the wreck
    # tracker itself already has), so most planets will have no rows here.
    # INSERT OR REPLACE (not IGNORE, unlike galaxy_resources): unlike a
    # wreck sighting, an ordinary resource node's placement is static/
    # generation-time-fixed (see read_planet_static_resources's own
    # docstring in the sibling repo), so a later observation superseding an
    # earlier one is safe - REPLACE exists for robustness against a sloppy
    # first read, not because the ground truth itself changes.
    c.execute("""
        CREATE TABLE IF NOT EXISTS poi_resource_nodes (
            system_name TEXT NOT NULL,
            planet TEXT NOT NULL,
            poi_index TEXT NOT NULL,
            resource TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            UNIQUE (system_name, planet, poi_index, resource)
        )
    """)
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
    """(source_name, concentration, expected_qty) triples for the node types
    that yield a given raw resource - distinct from `deposits`, which tracks
    specific manually-logged in-game locations, not general node-type
    categories. `concentration` is what % of that node's primary-yield rolls
    land on this resource (its proba weight vs its kind-0 sibling items',
    from the game's own resource-generation data - see
    tools/backfill_resource_sources.py). `expected_qty` is the average
    quantity of this resource yielded per harvest of that node - the same
    number the game's own Encyclopedia shows next to each item (reverse
    engineered from `ResourceUtils.hx:getItemsExpectations` - see that
    tool's docstring); unlike `concentration` it's an absolute figure, so it
    still distinguishes between sources that happen to share a %. Both may
    be None for hand-entered rows with no game-data match. Highest
    concentration first (best sources first), then name for ties/nulls."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT source_name, concentration, expected_qty FROM resource_sources"
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
    `sources` is a list of (source_name, concentration, expected_qty)
    triples; concentration/expected_qty may be None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM resource_sources WHERE resource_name=?", (resource_name,))
    deduped = {}
    for name, conc, expected_qty in sources:
        name = name.strip()
        if name:
            deduped[name] = (conc, expected_qty)
    c.executemany(
        "INSERT OR IGNORE INTO resource_sources"
        " (resource_name, source_name, concentration, expected_qty) VALUES (?, ?, ?, ?)",
        [(resource_name, n, conc, eq) for n, (conc, eq) in deduped.items()],
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
    attribute_names, planet_scale, explored) tuples - poi_tags is a comma-joined
    string of which POI(s) that resource is tied to on that planet (e.g.
    "poi0", "poi0,poi1"), "general" if it's scattered planet-wide with no
    POI anchor, or "poi0,general" if it's split between both. poi_area_density
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
    planet_scale is `planet.inf.props.scale` (defaults to 1.0 in-game when
    unset - the dump's own "planetScale" field, see
    tools/backfill_galaxy_resources.py) - used by get_galaxy_sources_for_
    resource to convert `density` (which the game's own
    compute_display_density formula scales UP with planet size) into a true,
    physically-normalized density for general/scattered-gathering ranking.
    explored (0/1/None) is THIS player's own, personal per-planet
    exploration flag (game.me.progress.systems, decoded by the dump's own
    read_explored_bits_by_system) - distinct from resourcesGenerated/shared
    quadrant state, and covers ent.Asteroid slots the same as ent.Planet
    slots. These six are planet-level, not resource-level, so they repeat
    across every resource row for the same planet - same treatment as
    system_name/sector already get. Existing rows are left alone
    (UNIQUE(system_name, planet, resource)), so re-running an import after
    further in-game exploration only adds new ones. Returns the number of
    rows actually inserted."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT OR IGNORE INTO galaxy_resources"
        " (system_name, planet, sector, resource, node_count, density, poi_tags,"
        " poi_area_density, is_asteroid, temperature, temperature_name,"
        " attributes, attribute_names, planet_scale, explored)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    inserted = conn.total_changes
    conn.close()
    return inserted


def update_galaxy_explored(rows):
    """Bulk UPDATE galaxy_resources.explored for rows ALREADY in the table,
    keyed by (system_name, planet) - deliberately not folded into
    import_galaxy_resources's own INSERT OR IGNORE. Every other column
    there is a static, generation-time fact (is_asteroid/temperature/
    planet_scale/...) that's correctly frozen at first import, so INSERT
    OR IGNORE silently skipping an already-known planet/resource row is
    exactly right for those - but explored is the one column that
    genuinely changes as THIS player keeps exploring, so a fresh dump must
    be able to update it on rows imported long ago, not just attach it to
    brand-new ones.

    `rows` is a list of (system_name, planet, explored) tuples (see
    tools/backfill_galaxy_resources.py's load_explored_rows) - explored is
    applied unconditionally to every existing resource row for that
    planet (it's duplicated per-resource-row the same way is_asteroid
    already is). A planet with no galaxy_resources rows yet (never had
    any resourceCounts) is a harmless no-op. Returns the number of
    resource rows actually touched (matches, not distinct planets - a
    planet with 3 logged resources counts as 3)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "UPDATE galaxy_resources SET explored = ? WHERE system_name = ? AND planet = ?",
        [(explored, system_name, planet) for system_name, planet, explored in rows],
    )
    conn.commit()
    updated = conn.total_changes
    conn.close()
    return updated


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


# Decay applied to the 2nd, 3rd, ... confirmed/estimated POI slot when
# combining a row's POI-anchored contributions in get_galaxy_sources_for_resource
# - see that function's own inline comment for the full derivation. Not a
# value derivable from any game data - a genuinely subjective tuning knob
# for "how much does a 2nd/3rd good spot matter relative to the best one",
# picked as a reasonable, easy-to-reason-about starting point (each
# additional spot is worth half of the previous one) rather than derived
# from anything - retune this single constant directly if it doesn't feel
# right once used against real data.
POI_DENSITY_DECAY_WEIGHT = 0.5


def _discrimination_weight(nonzero_values):
    """How much a ranking component's own population actually varies, as a
    0-1 factor: (max-min)/max among values that are actually present for
    this resource (a row with 0 for this component isn't part of "the
    field" being judged - it contributes nothing regardless of this
    weight, whatever it works out to). Used by get_galaxy_sources_for_
    resource to scale poi_ratio/general_ratio before summing them into
    effective_score.

    Why this is needed: ratio-to-max (value / max(all values)) always gives
    SOME row a ratio of 1.0, even when every value in the population is
    almost identical - "the best of a barely-differentiated field" is not
    the same claim as "the best of a field with real spread", but a plain
    ratio can't tell the two apart. Confirmed against real data: for some
    resources, general_value's whole population (across every planet that
    has ANY of it) spans under 2x top-to-bottom even with hundreds of
    samples (e.g. Elmerite), while for others it spans 60-80x (e.g. Ferrous
    Outcrop, Magnetite) - a single fixed weight applied to every resource's
    general_ratio would either needlessly suppress the genuinely
    discriminating cases or fail to suppress the barely-discriminating
    ones. Scaling by each resource's own actual spread targets the real
    cause instead: a general_value of "0.41, out of a field that only ever
    reaches 0.66" is nowhere near as meaningful a signal as the same 0.41
    would be "out of a field reaching 14" - the population itself says how
    much confidence a ratio of X within it deserves.

    Defaults to full weight (1.0) with fewer than 2 samples - there's
    nothing to call "clustered" yet (clustering is a property of multiple
    points relative to each other), so this isn't a case to suppress; a
    lone confirmed data point still deserves full credit."""
    if len(nonzero_values) < 2:
        return 1.0
    best = max(nonzero_values)
    worst = min(nonzero_values)
    return (best - worst) / best if best > 0 else 1.0


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
    contributing row's tags.

    RANKING: split into two separately-scored components rather than one
    "effective density" number, because a POI-bounded stop and an
    open-planet spread genuinely aren't the same kind of value and
    conflating them (the area-adjusted `poi_area_density` this function used
    to compute) was actively misleading - see the design discussion this
    replaced for the full reasoning. compute_display_density (the
    decompiled, UI-verified source of `density` - see
    dump_planet_resources.py) is `node_count * const * planet_scale^2`: it
    scales UP with a planet's physical size for a fixed count, which is
    exactly backwards for judging a small bounded POI (visiting one nets you
    its full count regardless of the POI's or planet's area - there's no
    extra "more walking" cost the way there is for scattered nodes across an
    entire planet), and can just as easily bury a real POI stash on a
    physically small planet behind an arbitrary scale penalty.

    - `poi_value`: how much this row is worth as a POI-anchored, one-stop
      visit. Raw node counts, never area-divided - see below for how the
      count is assembled per pure-vs-mixed row.
    - `general_value`: how much this row is worth as open-planet, walk-the-
      whole-surface gathering. Starts from plain `density` (minus whatever's
      already credited to a confirmed POI sub-portion, see the mixed-row
      case below, so the same nodes are never counted in both components),
      then converted from the game's own DISPLAY-density basis to a true,
      physically-normalized one: `density` is `count * const * scale^2`
      (see compute_display_density, dump_planet_resources.py) - it scales UP
      with planet size for a fixed count, the opposite of an actual areal
      density (count / surface_area, which scales DOWN with size, since a
      bigger planet's same count is spread thinner). A real density is what
      "covering more of a bigger planet genuinely costs more" actually
      requires - using the game's own display stat as-is would reward large
      planets for exactly the extra search effort they cost. Since
      surface_area is proportional to (PlanetReferenceSize * scale)^2,
      substituting shows true_density is proportional to `density /
      scale^4` - the PlanetReferenceSize/const factors are global constants
      that cancel out of every ratio this function computes, so dividing by
      scale^4 is the complete conversion, applied right before this value is
      stored (see the `scale = entry["planet_scale"]` line below).
      planet_scale is `planet.inf.props.scale` (see tools/
      backfill_galaxy_resources.py) - defaults to 1.0 (a no-op) for rows
      imported before this column existed.

    Each row's `effective_score` is poi_ratio + general_ratio, where each
    ratio is that row's own component divided by the MAX of that same
    component across every row returned for this resource, then scaled by
    _discrimination_weight of that component's own nonzero population (both
    components normalized and weighted independently, then summed - not
    multiplied like the frontend's "combined" sort mode, since these are
    two additive value sources you collect on the SAME visit, not two
    competing descriptions of one quantity). The discrimination weight
    matters because ratio-to-max alone always gives SOME row a 1.0, even
    when this resource's general spreads (or, in principle, its POI hauls)
    are all roughly the same middling size everywhere they're found - see
    _discrimination_weight's own docstring for the real data that motivated
    this and why a single fixed downweight can't substitute for it (some
    resources' general spreads genuinely do vary a lot planet to planet,
    and deserve full weight; others barely vary at all, and shouldn't claim
    a near-1.0 ratio on that basis). This is what the final sort orders by.
    A pure-POI row naturally has general_value=0 (ranks purely on
    poi_ratio); a pure-general row has poi_value=0 (ranks purely on
    general_ratio, in the same relative order plain density always gave,
    since scaling every row by the same max and weight is order-
    preserving).

    poi_value's raw-count assembly, per row shape:
    - No real POI tag at all ("general" only, or no poi_tags): poi_value=0,
      general_value=plain density. Same as this function's old fallback.
    - Pure POI row (poi_tags has no "general" entry), single tag: poi_value
      is just this row's own node_count - resourceCounts (what node_count is
      built from, see tools/backfill_galaxy_resources.py) is the exact,
      live placed-node count read straight from the game's own exploration
      memory, NOT a generation-quota estimate needing an on-planet visit to
      confirm - so this is already exact with zero poi_resource_nodes data.
    - Pure POI row, multiple tags (e.g. "poi0,poi1"): the dump gives an
      exact TOTAL across the tags but never how it splits between them.
      Wherever poi_resource_nodes (an actual on-planet visit - see the
      sibling spacecraft-memory-research repo's live_tracker.py) has
      confirmed one or more of those specific tags, each confirmed count is
      a real individual data point; the STILL-unconfirmed remainder
      (node_count minus whatever's confirmed) is folded in as one more
      synthetic slot in the same list, at whatever rank its own size earns,
      rather than assumed to be zero - both extremes (nothing confirmed
      -> the remainder IS the whole node_count, ranks first, gets full
      weight, so an entirely unconfirmed multi-POI row still ranks on its
      full honest total; everything confirmed -> no remainder, purely
      individual counts) fall out of the same formula, no special-casing
      needed. The full list (confirmed counts + at most one remainder slot)
      is sorted descending and combined via POI_DENSITY_DECAY_WEIGHT-decayed
      rank weighting (score = c1 + w*c2 + w^2*c3 + ...) - this is what
      correctly prefers "one POI with most of the total" over "several
      roughly-equal POIs" for the same total count, since reaching an equal
      total via more separate stops on the same planet genuinely costs more
      (real inter-POI travel), not nothing. poi_value_is_exact is True
      whenever at least one tag is actually confirmed (even if a remainder
      slot still also contributes); poi_value_poi_index names the single
      rank-1 tag ONLY when that top slot is a real confirmed tag, not a
      synthetic remainder (there's nothing to point the player at yet if the
      biggest chunk is still unvisited).
    - Mixed row ("general,poiN", at least one real POI tag AND a general
      share): unlike the pure case, an unconfirmed leftover here can't
      safely be assumed to be more POI - it might just be "general" - so
      ONLY actually-confirmed tags feed poi_value's decayed sum (no
      synthetic remainder slot). general_value then backs out whatever WAS
      confirmed from the row's own density (via density_per_node = density
      / node_count, an exact reconstruction of compute_display_density's
      per-planet scale constant from this same row's own already-stored
      pair - not an approximation), so a confirmed POI's nodes are credited
      once, not twice. With nothing confirmed this degenerates to
      poi_value=0, general_value=plain density - the same conservative
      fallback an unconfirmed row always had; this row's true POI
      concentration stays invisible to ranking until someone visits and
      confirms it, a known, accepted data limitation of the no-travel dump
      (it never records how a mixed row's total splits between general and
      POI to begin with), not something this formula can work around
      without that visit.

    Each row is also annotated with pure_poi (True if poi_tags is set with
    no "general" entry). include_asteroids=False filters out ent.Asteroid
    debris fields, keeping only regular numbered planets.

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

    Also annotated with explored (True/False/None - None means no row for
    this planet has ever carried the dump's own "explored" field, e.g.
    imported before that column existed; treated as unknown, not
    unexplored, by callers) - THIS player's own, personal per-planet
    exploration flag, see import_galaxy_resources's own docstring.

    Returns (system_name, planet, sector, node_count, density, poi_tags,
    pure_poi, is_asteroid, temperature, temperature_name, attributes,
    attribute_names, poi_landmarks, poi_sun_states, poi_value, general_value,
    effective_score, poi_value_is_exact, poi_value_poi_index, explored) tuples,
    already sorted by effective_score descending (node_count descending as a
    tiebreak)."""
    family = _resource_family(resource_name)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ",".join("?" for _ in family)
    query = (
        "SELECT system_name, planet, sector, node_count, density, poi_tags,"
        " is_asteroid, temperature, temperature_name,"
        " attributes, attribute_names, planet_scale, explored"
        f" FROM galaxy_resources WHERE resource IN ({placeholders})"
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

    # Exact, on-planet-confirmed per-POI counts (poi_resource_nodes) - used
    # below to build poi_value's raw-count assembly. Small table, same
    # "load whole, combine in Python" style as landmarks_by_planet above.
    c.execute(
        f"SELECT system_name, planet, poi_index, node_count"
        f" FROM poi_resource_nodes WHERE resource IN ({placeholders})",
        params,
    )
    exact_counts_by_planet = {}
    for system_name, planet, poi_index, node_count in c.fetchall():
        bucket = exact_counts_by_planet.setdefault((system_name, planet), {})
        bucket[poi_index] = bucket.get(poi_index, 0) + node_count
    conn.close()

    def is_pure_poi(poi_tags):
        return bool(poi_tags) and "general" not in poi_tags.split(",")

    combined = {}
    for (
        system_name, planet, sector, node_count, density, poi_tags,
        is_asteroid, temperature, temperature_name,
        attributes, attribute_names, planet_scale, explored,
    ) in rows:
        entry = combined.setdefault((system_name, planet), {
            "sector": sector, "node_count": 0, "density": 0.0,
            "poi_tag_labels": set(), "is_asteroid": is_asteroid,
            "temperature": temperature, "temperature_name": temperature_name,
            "attributes": attributes, "attribute_names": attribute_names,
            "planet_scale": planet_scale, "explored": explored,
        })
        entry["node_count"] += node_count or 0
        entry["density"] += density or 0.0
        if poi_tags:
            entry["poi_tag_labels"].update(poi_tags.split(","))

    rows_data = []
    for (system_name, planet), entry in combined.items():
        poi_tags = ",".join(sorted(entry["poi_tag_labels"])) if entry["poi_tag_labels"] else None
        planet_landmarks = landmarks_by_planet.get((system_name, planet), {})
        poi_landmarks = [
            planet_landmarks[tag] for tag in sorted(entry["poi_tag_labels"])
            if tag in planet_landmarks
        ]
        poi_sun_states = sorted({lm["sun_side"] for lm in poi_landmarks if lm["sun_side"]})

        poi_only_labels = entry["poi_tag_labels"] - {"general"}
        has_general = "general" in entry["poi_tag_labels"]
        exact_counts = exact_counts_by_planet.get((system_name, planet), {})
        confirmed = sorted(
            ((exact_counts[tag], tag) for tag in poi_only_labels if tag in exact_counts),
            key=lambda pair: -pair[0],
        )
        confirmed_sum = sum(count for count, _tag in confirmed)

        poi_value = 0.0
        general_value = 0.0
        poi_value_is_exact = bool(confirmed)
        poi_value_poi_index = None

        if poi_only_labels and not has_general:
            # Pure POI row: any leftover after confirmed counts MUST be more
            # (still-unconfirmed) POI, since there's no general share to
            # attribute it to - fold it in as one synthetic slot at whatever
            # rank its size earns, rather than assuming it's zero. See this
            # function's own docstring for why this degenerates correctly at
            # both ends (nothing confirmed -> ranks on the full honest
            # node_count; everything confirmed -> pure per-POI counts).
            remainder = entry["node_count"] - confirmed_sum
            ranked = list(confirmed)
            if remainder > 0:
                ranked.append((remainder, None))
            ranked.sort(key=lambda pair: -pair[0])
            poi_value = sum(
                count * (POI_DENSITY_DECAY_WEIGHT ** rank)
                for rank, (count, _tag) in enumerate(ranked)
            )
            if ranked and ranked[0][1] is not None:
                poi_value_poi_index = ranked[0][1]
        elif poi_only_labels and has_general:
            # Mixed row: only ACTUALLY confirmed tags count toward poi_value
            # (an unconfirmed leftover here could just be "general", unlike
            # the pure case above) - general_value backs out whatever was
            # confirmed so the same nodes aren't credited twice.
            poi_value = sum(
                count * (POI_DENSITY_DECAY_WEIGHT ** rank)
                for rank, (count, _tag) in enumerate(confirmed)
            )
            if confirmed:
                poi_value_poi_index = confirmed[0][1]
            density_per_node = (
                entry["density"] / entry["node_count"] if entry["node_count"] else 0.0
            )
            general_value = max(entry["node_count"] - confirmed_sum, 0) * density_per_node
        else:
            # No real POI tag at all.
            general_value = entry["density"]
            poi_value_is_exact = False

        # Convert general_value from the game's own display-density basis
        # (count * const * scale^2 - INCREASES with planet size, see
        # dump_planet_resources.py's compute_display_density) to a true,
        # physically-normalized density (count / surface_area, which
        # DECREASES with planet size, matching what "more planet to search"
        # actually means effort-wise) - see this function's own docstring
        # for the full derivation. true_density = count / (4*pi*R^2) where
        # R = PlanetReferenceSize * scale, and since density = count * const
        # * scale^2, substituting gives true_density proportional to
        # density / scale^4 - the PlanetReferenceSize/const factors are
        # GLOBAL constants that cancel out of every ratio this function ever
        # computes, so dividing by scale^4 alone is the complete, correct
        # conversion for ranking purposes. planet_scale defaults to 1.0
        # (scale^4 = 1, a no-op) for any row imported before this column
        # existed, or where the dump itself didn't have it.
        scale = entry["planet_scale"] if entry["planet_scale"] else 1.0
        general_value = general_value / (scale ** 4)

        rows_data.append({
            "system_name": system_name, "planet": planet, "sector": entry["sector"],
            "node_count": entry["node_count"], "density": entry["density"],
            "poi_tags": poi_tags, "pure_poi": is_pure_poi(poi_tags),
            "is_asteroid": bool(entry["is_asteroid"]), "temperature": entry["temperature"],
            "temperature_name": entry["temperature_name"], "attributes": entry["attributes"],
            "attribute_names": entry["attribute_names"], "poi_landmarks": poi_landmarks,
            "poi_sun_states": poi_sun_states, "poi_value": poi_value,
            "general_value": general_value, "poi_value_is_exact": poi_value_is_exact,
            "poi_value_poi_index": poi_value_poi_index,
            "explored": bool(entry["explored"]) if entry["explored"] is not None else None,
        })

    max_poi_value = max((r["poi_value"] for r in rows_data), default=0.0)
    max_general_value = max((r["general_value"] for r in rows_data), default=0.0)
    poi_weight = _discrimination_weight([r["poi_value"] for r in rows_data if r["poi_value"] > 0])
    general_weight = _discrimination_weight(
        [r["general_value"] for r in rows_data if r["general_value"] > 0]
    )
    for r in rows_data:
        poi_ratio = (
            r["poi_value"] / max_poi_value * poi_weight if max_poi_value > 0 else 0.0
        )
        general_ratio = (
            r["general_value"] / max_general_value * general_weight
            if max_general_value > 0 else 0.0
        )
        r["effective_score"] = poi_ratio + general_ratio

    rows_data.sort(key=lambda r: (-r["effective_score"], -r["node_count"]))

    return [
        (
            r["system_name"], r["planet"], r["sector"], r["node_count"], r["density"],
            r["poi_tags"], r["pure_poi"], r["is_asteroid"], r["temperature"],
            r["temperature_name"], r["attributes"], r["attribute_names"],
            r["poi_landmarks"], r["poi_sun_states"], r["poi_value"], r["general_value"],
            r["effective_score"], r["poi_value_is_exact"], r["poi_value_poi_index"],
            r["explored"],
        )
        for r in rows_data
    ]


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


def import_poi_resource_nodes(rows):
    """Bulk INSERT OR REPLACE poi_resource_nodes rows - `rows` is a list of
    (system_name, planet, poi_index, resource, node_count, observed_at)
    tuples, one per (POI, resource) pair actually observed on a visited
    planet (see backend/poi_resource_import.py, which builds these from
    the sibling spacecraft-memory-research repo's live_tracker.py's
    poi_resource_counts.json snapshot). REPLACE (not IGNORE, unlike
    import_galaxy_resources) since a later, better on-planet observation of
    the same POI should supersede an earlier one - see poi_resource_nodes'
    own table comment in init_db for why that's safe here."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT OR REPLACE INTO poi_resource_nodes"
        " (system_name, planet, poi_index, resource, node_count, observed_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_poi_resource_node_counts_for_resource(resource):
    """(system_name, planet, poi_index, node_count, observed_at) rows for
    every planet where this exact resource's per-POI count has been
    on-planet-confirmed - used by Api.get_galaxy_sources to batch-attach
    exact counts onto the coarse galaxy_resources rows it already returns,
    one query per call rather than one per row."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT system_name, planet, poi_index, node_count, observed_at"
        " FROM poi_resource_nodes WHERE resource=?",
        (resource,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


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


# ---- Wreck events (tools/import_wreck_events.py, sibling repo's live_tracker.py) ----


# Display names/tiers for the resourceIds live_tracker.py ever logs -
# static, data.cdb-derived, same "small hardcoded table" call
# RESOURCE_SIZE_VARIANTS/DEPOSIT_TYPE_RESOURCE_NAMES above already make for
# similarly tiny/unlikely-to-change lookups, rather than adding a runtime
# dependency on the sibling repo's data.cdb loading. Both hull and crate
# resourceIds share the SAME display name across all their tiers in
# data.cdb (id -> name: ShipWreck_Lvl0/1/2 and the BigPiece1/BigPiece2/
# SmallPiece1/SmallPiece2 hull-piece variants -> "Shipwreck",
# ShipWreck_LootChestRare_lvl0/1/2 -> "Precious Cargo") - the trailing
# digit is a loot-level/progression tier, not a separate display identity,
# so it's surfaced as its own `level` field rather than folded into the
# name. SmallPiece1/SmallPiece2 have no _lvl suffix in data.cdb at all
# (level=None) - not a gap, they're simply not tiered.
#
# Originally only had the plain Lvl0/1/2 hull ids - missed that a wreck's
# hull can instead be built from BigPiece1/BigPiece2/SmallPiece1/
# SmallPiece2 sibling pieces (same parentId, same data.cdb type=7
# "Shipwreck" category, see live_tracker.py's WRECK_HULL_IDS for the full
# derivation) - any such event fell back to raw resource_id/kind=None here,
# same underlying gap as the frontend's wreck-tracker-panel.js HULL_IDS.
WRECK_RESOURCE_INFO = {
    "ShipWreck_Lvl0": {"display_name": "Shipwreck", "kind": "hull", "level": 0},
    "ShipWreck_Lvl1": {"display_name": "Shipwreck", "kind": "hull", "level": 1},
    "ShipWreck_Lvl2": {"display_name": "Shipwreck", "kind": "hull", "level": 2},
    "ShipWreck_BigPiece1_lvl0": {"display_name": "Shipwreck", "kind": "hull", "level": 0},
    "ShipWreck_BigPiece1_lvl1": {"display_name": "Shipwreck", "kind": "hull", "level": 1},
    "ShipWreck_BigPiece1_lvl2": {"display_name": "Shipwreck", "kind": "hull", "level": 2},
    "ShipWreck_BigPiece2_lvl0": {"display_name": "Shipwreck", "kind": "hull", "level": 0},
    "ShipWreck_BigPiece2_lvl1": {"display_name": "Shipwreck", "kind": "hull", "level": 1},
    "ShipWreck_BigPiece2_lvl2": {"display_name": "Shipwreck", "kind": "hull", "level": 2},
    "ShipWreck_SmallPiece1": {"display_name": "Shipwreck", "kind": "hull", "level": None},
    "ShipWreck_SmallPiece2": {"display_name": "Shipwreck", "kind": "hull", "level": None},
    "ShipWreck_LootChestRare_lvl0": {"display_name": "Precious Cargo", "kind": "crate", "level": 0},
    "ShipWreck_LootChestRare_lvl1": {"display_name": "Precious Cargo", "kind": "crate", "level": 1},
    "ShipWreck_LootChestRare_lvl2": {"display_name": "Precious Cargo", "kind": "crate", "level": 2},
    # Added alongside live_tracker.py's BLACKBOX_IDS - a rare, untiered
    # walk-up pickup (data.cdb type=8, no _lvl variants), tracked by the
    # live overlay as its own on-foot-only red marker.
    "ShipWreck_BlackBox": {"display_name": "Black Box", "kind": "blackbox", "level": None},
}


def import_wreck_events(rows):
    """Bulk INSERT OR IGNORE wreck_events rows - `rows` is a list of
    (system_name, planet, resource_id, event_type, wreck_size, wreck_tier,
    parent_id, x, y, z, observed_at) tuples, straight from the sibling
    repo's event_log_db (SQLite `wreck_events` table - see backend/
    wreck_import.py for the id-cursor-based read). `INSERT OR IGNORE`
    against UNIQUE(system_name, planet, resource_id, event_type,
    observed_at, x, y, z) - x/y/z are part of the key specifically because
    two DIFFERENT wrecks/crates of the same resourceId are routinely
    'seen' in the same poll cycle (sharing the same observed_at
    timestamp) - without position in the key, a genuinely real second
    sighting silently collided with the first and got dropped (caught
    live: a 3-wreck test planet with 2 same-tier hulls + 2 same-tier
    crates imported as only 1 of each until this was added). wreck_size/
    wreck_tier/parent_id are deliberately NOT part of the UNIQUE key (same
    sighting shouldn't duplicate just because one of those resolved
    differently) - IGNORE is a safety net for re-importing a source row
    already seen, not the primary de-dup mechanism now that the id cursor
    (see get/set_wreck_event_import_cursor) already skips already-imported
    rows in the normal case. Returns the number of rows actually
    inserted."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT OR IGNORE INTO wreck_events"
        " (system_name, planet, resource_id, event_type, wreck_size, wreck_tier, parent_id, x, y, z, observed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    inserted = conn.total_changes
    conn.close()
    return inserted


def get_wreck_stats():
    """One row per (system_name, planet, resource_id, wreck_size) ever
    logged: counts of each event_type - seen (every distinct sighting,
    including ones later looted/despawned - a cumulative "how many have I
    ever found here" count, not a current-count), looted, despawned.
    wreck_size is grouped separately (not just carried along) because a
    Big and Small wreck sharing the same resource_id at the same planet
    are genuinely different sighting populations, same reasoning as
    splitting by resource_id (crate tier) in the first place - see the
    sibling repo's annotate_wreck_size_tier. Rows with wreck_size IS NULL
    (a crate/Black Box whose own wreck's hull piece wasn't in the same
    scan cycle to resolve size from) get their own group rather than
    being dropped or merged into a guess. sector is a best-effort lookup
    against galaxy_resources (None if that system was never covered by a
    galaxy-wide dump import - see this table's own docstring in init_db
    for why wreck_events doesn't store sector itself). Caller (Api layer /
    frontend) rolls this up by planet/system/sector as needed - already
    the finest useful grain per row, so no separate pre-aggregated variant
    is needed for each rollup level. Returns (system_name, planet, sector,
    resource_id, wreck_size, seen_count, looted_count, despawned_count)
    tuples.

    WHERE parent_id IS NOT NULL - raised directly by the user: without
    this, crate/Black Box counts here are a "since forever" cumulative
    total (4835+ pre-parent_id historical rows) sitting next to
    get_wreck_site_stats' "since parent_id tracking began" wreck-site
    counts in the SAME UI panel - two different time windows that invite
    a misleading comparison (e.g. "230 crates, 2 wreck sites" reads like
    ~115 crates/wreck, which isn't a real ratio, just an artifact of the
    site count's much shorter accumulation window). Filtering both
    queries to the identical parent_id-based cutoff keeps every number in
    this panel on the same time window - not a data-quality filter (the
    excluded historical rows aren't wrong), a comparability one. The
    excluded rows stay in the table, just unsurfaced here - nothing
    deleted, reversible by dropping this filter later if the two stats
    ever stop being shown together."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT system_name, planet, resource_id, wreck_size,
               SUM(CASE WHEN event_type='seen' THEN 1 ELSE 0 END),
               SUM(CASE WHEN event_type='looted' THEN 1 ELSE 0 END),
               SUM(CASE WHEN event_type='despawned' THEN 1 ELSE 0 END)
        FROM wreck_events
        WHERE parent_id IS NOT NULL
        GROUP BY system_name, planet, resource_id, wreck_size
        ORDER BY system_name COLLATE NOCASE, planet COLLATE NOCASE, resource_id
    """)
    rows = c.fetchall()
    c.execute(
        "SELECT DISTINCT system_name, sector FROM galaxy_resources WHERE sector IS NOT NULL"
    )
    sector_by_system = dict(c.fetchall())
    conn.close()
    return [
        (system_name, planet, sector_by_system.get(system_name), resource_id, wreck_size, seen, looted, despawned)
        for (system_name, planet, resource_id, wreck_size, seen, looted, despawned) in rows
    ]


def get_wreck_site_stats():
    """One row per (system_name, planet, sector, wreck_size, wreck_tier)
    ever logged, counting distinct wreck SITES - not hull-piece sightings.
    Raised directly by the user: per-resource_id counting (get_wreck_stats)
    fragments ONE Big wreck into up to 4 rows, since a Big wreck's hull is
    BigPiece1/BigPiece2/SmallPiece1/SmallPiece2 (4 separate resource_ids,
    only 2 of which even carry a tier) - "what's useful is big and small
    wreck SITE, not individual hull count."

    Two-stage aggregation: first collapse every hull-piece row sharing a
    parent_id (the sibling repo's live wreck-instance grouping - see that
    repo's diff_nodes) down to ONE site-row (its resolved size/tier, and
    whether it was ever seen/despawned), THEN aggregate those site-rows
    into counts per (system, planet, size, tier). wreck_size/wreck_tier
    are read via MAX() rather than a plain column reference because
    they're aggregated-away by the first GROUP BY - safe/unambiguous since
    every hull piece of the same wreck already carries the IDENTICAL
    resolved size/tier (both stamped once per parent_id group by the
    sibling repo's annotate_wreck_size_tier, not per-piece).

    Only rows with parent_id IS NOT NULL count here (sightings logged
    before that column existed are invisible to this query, not
    mis-attributed as their own site - see RESEARCH_LOG.md for why
    backfilling parent_id onto historical rows isn't possible: the
    correlation data was never persisted, only used transiently in memory
    at scan time). No 'looted' count - hull pieces are only ever 'seen'/
    'despawned' (see the sibling repo's diff_nodes; only crates/Black Box
    ever get classified 'looted'). Returns (system_name, planet, sector,
    wreck_size, wreck_tier, seen_count, despawned_count) tuples."""
    hull_ids = [rid for rid, info in WRECK_RESOURCE_INFO.items() if info["kind"] == "hull"]
    placeholders = ",".join("?" * len(hull_ids))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"""
        WITH sites AS (
            SELECT system_name, planet, parent_id,
                   MAX(wreck_size) AS wreck_size,
                   MAX(wreck_tier) AS wreck_tier,
                   MAX(CASE WHEN event_type='seen' THEN 1 ELSE 0 END) AS was_seen,
                   MAX(CASE WHEN event_type='despawned' THEN 1 ELSE 0 END) AS was_despawned
            FROM wreck_events
            WHERE parent_id IS NOT NULL AND resource_id IN ({placeholders})
            GROUP BY system_name, planet, parent_id
        )
        SELECT system_name, planet, wreck_size, wreck_tier,
               SUM(was_seen), SUM(was_despawned)
        FROM sites
        GROUP BY system_name, planet, wreck_size, wreck_tier
        ORDER BY system_name COLLATE NOCASE, planet COLLATE NOCASE
    """, hull_ids)
    rows = c.fetchall()
    c.execute(
        "SELECT DISTINCT system_name, sector FROM galaxy_resources WHERE sector IS NOT NULL"
    )
    sector_by_system = dict(c.fetchall())
    conn.close()
    return [
        (system_name, planet, sector_by_system.get(system_name), wreck_size, wreck_tier, seen, despawned)
        for (system_name, planet, wreck_size, wreck_tier, seen, despawned) in rows
    ]


def get_wreck_event_import_cursor(source_db_path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT last_id FROM wreck_event_import_cursor WHERE source_db_path=?",
        (source_db_path,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def set_wreck_event_import_cursor(source_db_path, last_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO wreck_event_import_cursor (source_db_path, last_id) VALUES (?, ?)",
        (source_db_path, last_id),
    )
    conn.commit()
    conn.close()


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


