"""
Compare observed rare-loot-crate counts in resources.db's wreck_events log
against the theoretical per-wreck crate odds in
game_data_extract/shipwreck_loot.json, split by wreck SIZE (Small/Big) -
not just by sector - since size, not sector or tier, is what actually
drives expected crate count (see the sibling shipbuilder repo's
tools/game_logic_notes.md Finding 8/9).

This script IS the analysis that found (Finding 11) and then narrowed
down (Finding 12) the crate-count discrepancy documented in that same
file - read Findings 11-12 in full before trusting any read of this
script's output. Summary: Finding 11 found and fixed a whole missing
generation pass (a wreck hull piece's own resGroupSpawn, confirmed live
to fire unconditionally at world-gen - see extract_shipwreck_loot.py's
secondary_spawn_group_id), closing Big's gap to within 1.3%. Finding 12
found that closing Small's MEAN gap the same way was coincidental - its
full crate-count distribution has a hard cliff between 3 and 4 crates
(model treats them as near-equally likely; observed is ~7x rarer at 4)
with zero true-zero sites, and every hypothesis tried so far (tier,
linkedResource, min-value floors, flags bits, stale baseline,
pre-existing depletion, terrain-placement retries, and - as of this
script's last update - the whole-group terrain-slope gate in
generateGroup, decompiled in full and found to predict the wrong
direction) has been ruled out with evidence, not just deprioritized.
Small wrecks' true crate-generation mechanism is still not understood.

Why size, not sector: shipwreck_loot.json's sectors[*].crate_spawn_* is a
BLENDED average across every wreck-size variant in that sector's own
wreckResGen list (weighted by how often each resGen id repeats there) -
it is not the expected count for any single wreck you actually walk up
to. A wreck's hull tells you which population it's actually drawn from,
confirmed directly from data.cdb's resGroup sheet: a "Small" wreck
(GShipWreck_Small_lvlN) places a single ShipWreck_LvlN hull piece and
rolls its JunkGroup 1-2 times; a "Big" wreck (GShipWreck_Big_lvlN) places
FOUR hull debris pieces (BigPiece1_lvlN + BigPiece2_lvlN + SmallPiece1 +
SmallPiece2 - note SmallPiece here means "small debris chunk of a Big
wreck's hull", unrelated to the Small/Big wreck-SIZE axis) and rolls its
JunkGroup 5-10 times - about 4x more chances at a rare-loot roll. Finding
8's Monte Carlo (debris field alone) puts Small at E[count]~0.89 and Big
at E[count]~3.6; Finding 11 adds a second, independent generation pass
(a hull piece's own resGroupSpawn) on top of that, bringing the full
total to ~2.89 (Small) / ~7.1 (Big) - see THEORETICAL_EXPECTED_COUNT
below and shipwreck_loot.json's crateSpawn.bySize.*.total.

Method: cluster all 'seen' wreck_events by 3D position (a single wreck's
own hull+crates spread within ~100 units per data.cdb's own resGroup
`size` prop for Big wrecks, 50 for Small; separate wreck slots are
10,000+ units apart in every planet inspected so far) rather than
counting hull resource_id rows directly, since one physical wreck can
log 1 (plain Lvl0/1/2), 4 (BigPiece1/2 + SmallPiece1/2), or 0 (hull
already gone before tracking started) separate hull 'seen' rows -
resource_id counts alone over/under-count real wreck sites depending on
format. A cluster is classified Big if it contains any BigPiece/
SmallPiece-tagged hull event, Small if it contains a plain Lvl0/1/2 hull
event and no Big-piece tags, otherwise "unknown" (crate(s) seen with no
hull ever logged for that slot - most likely a wreck whose hull was
already destroyed before this tracking session began).

Usage:
    python tools/audit_wreck_crate_rates.py
"""
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend.paths import DB_PATH  # noqa: E402

# A single wreck's own hull+crate spread stays within data.cdb's resGroup
# `size` prop (100 for Big, 50 for Small) - inter-wreck gaps observed so
# far are 10,000+ units, so this threshold comfortably separates distinct
# wreck slots without ever splitting one wreck's own debris field (tested
# down to 80 units on 2026-07-20 data before clusters started fragmenting
# genuine single-wreck debris).
CLUSTER_THRESHOLD = 150.0

BIG_HULL_TAGS = {
    "ShipWreck_BigPiece1_lvl0", "ShipWreck_BigPiece1_lvl1", "ShipWreck_BigPiece1_lvl2",
    "ShipWreck_BigPiece2_lvl0", "ShipWreck_BigPiece2_lvl1", "ShipWreck_BigPiece2_lvl2",
    "ShipWreck_SmallPiece1", "ShipWreck_SmallPiece2",
}
SMALL_HULL_TAGS = {"ShipWreck_Lvl0", "ShipWreck_Lvl1", "ShipWreck_Lvl2"}
CRATE_IDS = {
    "ShipWreck_LootChestRare_lvl0",
    "ShipWreck_LootChestRare_lvl1",
    "ShipWreck_LootChestRare_lvl2",
}

# Findings 8 + 11 (tools/game_logic_notes.md, shipbuilder repo): 20k-trial
# Monte Carlo of the full generation tree - debris field (Finding 8) PLUS
# the hull piece's own resGroupSpawn secondary pass (Finding 11), which
# fires unconditionally at world-gen, not on any player action. Both
# tier-independent - only wreck SIZE moves these numbers. Representative
# values (varies slightly per sector's own wreckResGen mix - see
# shipwreck_loot.json's crateSpawn.bySize.*.total for the exact per-sector
# figure). Big matches live-tracked reality within ~1-2%; Small's MEAN
# lands close too, but its full count distribution shape does not match
# this (or any other tested) model - see Finding 12, still open.
THEORETICAL_EXPECTED_COUNT = {"Big": 7.1, "Small": 2.89}


def cluster_planet_events(points, threshold=CLUSTER_THRESHOLD):
    """points: list of (resource_id, x, y, z). Returns list of resource_id
    lists, one per spatial cluster (union-find over pairwise distance)."""
    n = len(points)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        xi, yi, zi = points[i][1], points[i][2], points[i][3]
        for j in range(i + 1, n):
            xj, yj, zj = points[j][1], points[j][2], points[j][3]
            if math.sqrt((xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2) < threshold:
                union(i, j)

    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(points[i][0])
    return list(clusters.values())


def classify_cluster(resource_ids):
    if any(r in BIG_HULL_TAGS for r in resource_ids):
        return "Big"
    if any(r in SMALL_HULL_TAGS for r in resource_ids):
        return "Small"
    return "Unknown (no hull ever seen)"


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT system_name, planet, resource_id, x, y, z"
        " FROM wreck_events WHERE event_type='seen'"
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        print("No wreck_events rows found - nothing to audit.")
        return

    by_planet = defaultdict(list)
    for system, planet, rid, x, y, z in rows:
        by_planet[(system, planet)].append((rid, x, y, z))

    totals = defaultdict(lambda: {"sites": 0, "crates": 0})
    for points in by_planet.values():
        for cluster in cluster_planet_events(points):
            kind = classify_cluster(cluster)
            totals[kind]["sites"] += 1
            totals[kind]["crates"] += sum(1 for r in cluster if r in CRATE_IDS)

    print(f"{len(by_planet)} planets, {sum(t['sites'] for t in totals.values())} distinct wreck sites (position-clustered)\n")
    print(f"{'Wreck type':<28} {'sites':>6} {'crates':>7} {'observed avg':>13} {'theoretical avg':>16}")
    for kind in ("Big", "Small", "Unknown (no hull ever seen)"):
        t = totals.get(kind)
        if not t or not t["sites"]:
            continue
        avg = t["crates"] / t["sites"]
        theo = THEORETICAL_EXPECTED_COUNT.get(kind)
        theo_str = f"{theo:.2f}" if theo is not None else "n/a"
        print(f"{kind:<28} {t['sites']:>6} {t['crates']:>7} {avg:>13.2f} {theo_str:>16}")


if __name__ == "__main__":
    main()
