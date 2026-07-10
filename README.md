# CraftMap

A Windows desktop overlay for tracking resource deposits and crafting recipes
while playing SpaceCraft.

See [NOTICE.md](NOTICE.md) for licensing information.

A companion browser-based ship builder for designing ships against the
game's real part catalogue lives in a separate repository:
[SpaceCraft-ShipBuilder](https://github.com/Torkeug/SpaceCraft-ShipBuilder).

## Overlay

A [pywebview](https://pywebview.flowrl.com/)-based app (Python backend,
HTML/CSS/JS frontend rendered via an embedded WebView2 control) that sits
always-on-top over the game window (borderless mode) and toggles
visible/hidden via a global hotkey (default: F1, rebindable from the
in-app Settings dialog). A separate, independently pinnable Craft Queue
window tracks jobs across multiple recipes at once.

**Run from source:**
```
python main.py
```
Run as administrator if the global hotkey fails to register.

**Install dependencies:**
```
pip install -r requirements.txt
```

**Build a standalone executable:**
```
build.bat
```
Runs PyInstaller (`--onefile --noconsole`) and produces `CraftMap.exe` in
the project root.

**Run tests:**
```
pip install pytest
python -m pytest tests/
```

Tracks resource deposit locations (type, sector, system, planet, status) and
crafting recipes with recursive ingredient-tree resolution, alternate-recipe
selection, multi-station/craft-time metadata, and persistent checkbox/
progress state — all backed by a local SQLite database (`resources.db`).

## Tools

`tools/backfill_recipe_metadata.py` enriches `resources.db`'s recipes with
game-authoritative station/craft-time/multi-output data pulled from
`game_data_extract/` (itself extracted from the game's own data files by a
script in the sibling shipbuilder repo). See the script's own docstring and
`game_data_extract/README.md` for details.
