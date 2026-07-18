"""
One-off maintenance script: crop the 3 real POI landmark icons (Meteor
Crater / High Peak / Natural Canyon - the only planetGen.poiIndicator
values ever actually reachable in-game, see tools/backfill_galaxy_resources.py's
own docstring for how poi_tags/poiLandmarks are sourced) out of the game's
own UI sprite sheet, into small standalone PNGs under frontend/assets/poi/
for the Galaxy sub-tab to display.

Source sprite sheet lives in the sibling shipbuilder repo
(pak_out/ui/windows/hd_sprite-sheet_ic.png, extracted from the game's own
res.pak - see shipbuilder/tools/), never copied into this repo wholesale;
only these 3 small icon crops get committed here (frontend/assets/poi/ -
see NOTICE.md for why that's a materially smaller/more scoped inclusion than
redistributing the sheet itself).

Grid coordinates (x/y in cells, width/height in cells, "size" = px per cell)
come straight from galaxy_resources.json's poiLandmarks[*].icon field, which
is IDENTICAL across every occurrence of the same landmark name/indicatorId
(confirmed by inspecting the live dump - these are static UI icon
placements, not per-planet data), so they're hardcoded here rather than
read from the dump at run time.

Usage:
    python tools/extract_poi_icons.py
    python tools/extract_poi_icons.py --sprite-sheet path/to/hd_sprite-sheet_ic.png
"""
import argparse
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent

# Local-machine-only default - the sibling shipbuilder repo's own extracted
# asset, never copied into this repo wholesale (see this module's own
# docstring).
DEFAULT_SPRITE_SHEET = (
    REPO_ROOT.parent / "shipbuilder" / "pak_out" / "ui" / "windows" / "hd_sprite-sheet_ic.png"
)

OUT_DIR = REPO_ROOT / "frontend" / "assets" / "poi"

# (output filename, indicatorId, x, y, width, height) - x/y/width/height in
# grid cells, size=32px/cell for all three (see this module's own docstring).
CELL_SIZE = 32
ICONS = [
    ("meteor-crater.png", "BalisePOI", 12, 3, 2, 2),
    ("high-peak.png", "BalisePOI1", 14, 3, 2, 2),
    ("natural-canyon.png", "BalisePOI2", 16, 3, 2, 2),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sprite-sheet",
        default=str(DEFAULT_SPRITE_SHEET),
        help="hd_sprite-sheet_ic.png to crop from"
        " (default: ../shipbuilder/pak_out/ui/windows/hd_sprite-sheet_ic.png)",
    )
    args = parser.parse_args()

    sheet_path = Path(args.sprite_sheet)
    if not sheet_path.exists():
        raise SystemExit(f"No sprite sheet found at {sheet_path}")

    sheet = Image.open(sheet_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, indicator_id, x, y, w, h in ICONS:
        box = (x * CELL_SIZE, y * CELL_SIZE, (x + w) * CELL_SIZE, (y + h) * CELL_SIZE)
        crop = sheet.crop(box)
        out_path = OUT_DIR / filename
        crop.save(out_path)
        print(f"{indicator_id} -> {out_path} ({crop.size[0]}x{crop.size[1]})")


if __name__ == "__main__":
    main()
