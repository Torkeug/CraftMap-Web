"""
Read-only check: for every recipe in resources.db, verify its ingredients/
outputs still match the game-authoritative data it was matched against
(recipes.game_craft_id, set by tools/backfill_recipe_metadata.py). Does NOT
modify resources.db - this is purely a report to review before deciding
whether to lock the recipe editor down to "trust game data" mode.

A recipe can end up in one of four buckets:
    - clean:   game_craft_id set, ingredients/outputs match game data exactly.
    - drifted: game_craft_id set, but current DB ingredients/outputs differ
               from what that craft id actually specifies - either hand-edited
               after matching, or the match was wrong to begin with.
    - no_match: no game_craft_id at all - backfill_recipe_metadata.py never
                found a matching game craft for this recipe's output+ingredients.
    - stale_id: game_craft_id set but that id no longer exists in
                craft_recipes.json (shouldn't normally happen; would mean the
                game data snapshot regressed a recipe that used to exist).

Usage:
    python tools/verify_recipes_match_game_data.py
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend.paths import DB_PATH  # noqa: E402

GAME_DATA_DIR = REPO_ROOT / "game_data_extract"


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def load_game_data():
    items = json.loads((GAME_DATA_DIR / "items.json").read_text(encoding="utf-8"))
    recipes = json.loads(
        (GAME_DATA_DIR / "craft_recipes.json").read_text(encoding="utf-8")
    )
    return items, recipes


def item_name(items, item_id):
    return items.get(item_id, {}).get("name") or item_id


def qty_set(rows, name_qty_pairs=None):
    """rows: [(name, qty), ...] -> {(_norm(name), float(qty)), ...}"""
    return {(_norm(n), float(q)) for n, q in rows}


def main():
    items, recipes = load_game_data()
    crafts_by_id = {c["id"]: c for c in recipes}

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, game_craft_id FROM recipes ORDER BY name COLLATE NOCASE")
    db_recipes = c.fetchall()

    clean, drifted, no_match, stale_id = [], [], [], []

    for rid, name, craft_id in db_recipes:
        if not craft_id:
            no_match.append((rid, name))
            continue
        craft = crafts_by_id.get(craft_id)
        if craft is None:
            stale_id.append((rid, name, craft_id))
            continue

        c.execute(
            "SELECT ingredient_name, quantity FROM recipe_ingredients WHERE recipe_id=?",
            (rid,),
        )
        db_ings = qty_set(c.fetchall())
        game_ings = qty_set(
            [(item_name(items, i["item"]), i["qty"]) for i in craft["inputs"]]
        )

        c.execute(
            "SELECT item_name, quantity FROM recipe_outputs WHERE recipe_id=?", (rid,)
        )
        db_outs = qty_set(c.fetchall())
        game_outs = qty_set(
            [
                (item_name(items, o["item"]), o.get("qty", 1))
                for o in craft["outputs"]
            ]
        )

        issues = []
        if db_ings != game_ings:
            issues.append(
                f"ingredients: db has {db_ings - game_ings or '{}'}, "
                f"game has {game_ings - db_ings or '{}'}"
            )
        if db_outs != game_outs:
            issues.append(
                f"outputs: db has {db_outs - game_outs or '{}'}, "
                f"game has {game_outs - db_outs or '{}'}"
            )

        if issues:
            drifted.append((rid, name, craft_id, issues))
        else:
            clean.append((rid, name))

    conn.close()

    total = len(db_recipes)
    print(f"{total} recipes total:")
    print(f"  clean (matches game data exactly): {len(clean)}")
    print(f"  drifted (matched, but DB differs from game data): {len(drifted)}")
    print(f"  no_match (never matched to a game craft): {len(no_match)}")
    print(f"  stale_id (game_craft_id no longer in game data): {len(stale_id)}")

    if drifted:
        print("\n--- drifted ---")
        for rid, name, craft_id, issues in drifted:
            print(f"  [{rid}] {name!r} (craft_id={craft_id})")
            for issue in issues:
                print(f"      {issue}")

    if no_match:
        print("\n--- no_match ---")
        for rid, name in no_match:
            print(f"  [{rid}] {name!r}")

    if stale_id:
        print("\n--- stale_id ---")
        for rid, name, craft_id in stale_id:
            print(f"  [{rid}] {name!r} (craft_id={craft_id})")


if __name__ == "__main__":
    main()
