# Notice

CraftMap is a fan-made companion tool for the game **SpaceCraft** (© its
respective developer/publisher). It is not affiliated with or endorsed by
them.

This repository contains original code (see [LICENSE](LICENSE), MIT) plus a
small amount of reference material extracted from the game's own files, for
personal/non-commercial/educational use, not for redistribution as
standalone game assets:

- `game_data_extract/` — recipe/item/resource-node JSON extracted from the
  game's own `data.cdb` (see that directory's own README.md).
- `frontend/assets/poi/` — 3 small (64x64px) POI landmark icons (Meteor
  Crater/High Peak/Natural Canyon), cropped from the game's own UI sprite
  sheet by `tools/extract_poi_icons.py`.

`resources.db` (the local SQLite database CraftMap builds as you use it) is
not tracked in this repository and is populated entirely from your own
manual entries.
