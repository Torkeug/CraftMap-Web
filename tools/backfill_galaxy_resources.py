"""
Repeatable maintenance script: import a galaxy-wide resource-type snapshot
into resources.db's galaxy_resources table, from the sibling
spacecraft-memory-research repo's dump_galaxy_resources.py output (reads a
live SpaceCraft.exe process's exploration history, not extracted from
data.cdb). Unlike everything in game_data_extract/ (universal,
data.cdb-derived reference data meant to be committed), this dump is
personal and per-Quadrant - it reflects one player's own playthrough and
goes stale as they explore further - so it is never copied into this repo,
the same treatment resources.db itself already gets (see .gitignore).

Only INSERT OR IGNOREs against galaxy_resources' own
UNIQUE(system_name, planet, resource) constraint, so rerunning this after
further exploration (a fresh dump covers more explored planets over time)
just adds new rows - does not touch any other table.

Only imports resourceCounts/resourceDensities - the exact, live per-resource
counts (see the dump's own docstring), not the coarser resGroup-level
resourceNodeCountEstimates. Planets with no resourceCounts (not yet
generated client-side) are silently skipped, not imported as empty/
placeholder rows.

Also carries over resourcesByPoi (per planet, which POI index or "general"
each resource is tied to - the dump doesn't split node_count/density per
POI, only which POI(s) a resource shows up at) as a comma-joined poi_tags
string per row, e.g. "poi0", "poi0,poi1", or "general" - a resource with NO
"general" entry is purely POI-anchored on that planet (all its nodes are at
one walkable spot rather than scattered across the whole surface), a
meaningfully better gather spot than the same total density spread planet-
wide. Left as raw data rather than a precomputed "better spot" flag, so that
comparison (a POI-anchored planet's density vs. that resource's typical
"general" density elsewhere) can be made at query time.

For resources that are purely POI-anchored AND have a known size for every
POI they're tied to (planetScale/poiSizes - see dump_galaxy_resources.py's
own CLAUDE.md for the derivation), also computes poi_area_density: density
divided by the summed surface-area fraction of those POI(s) (poi_surface
below, the same angleFromDistance-based conversion compute_density already
uses internally for its own generation-quota estimate - reused here, not
reinvented). Built from `density`, not raw node_count, specifically so it
stays on the SAME scale as a "general" resource's own `density` - see
poi_surface's own docstring for why that's a fair comparison, not two
different units.

Also carries over isAsteroid (ent.Asteroid debris field vs. a regular
ent.Planet - see dump_galaxy_resources.py's own CLAUDE.md) as-is, so a
query can filter fields out of "planet" results.

Also carries over temperature/temperatureName (the planet's resolved
temperature attribute, e.g. "PlanetHot2"/"Very Hot" - always set, defaults
to "PlanetTemperate"/"Temperate" when the planet has no explicit
temperature attribute) and attributes/attributeNames (ALL of the planet's
raw generation-time attributes - water presence, radioactive, foggy, etc,
not just temperature - see dump_galaxy_resources.py's own CLAUDE.md,
"planet.inf.attributes"), comma-joined the same way poi_tags already is.

Also synthesizes composite entity rows from depositGroupSizes (per-planet
list of {resGroup, sizes: [{resource, min, max}]} - which Deposit-type
resources share one physical auto-extractor spot on THIS planet, since a
resGroup's possible members are static per-resGroup-id but which resGroup
id spawned is per-planet). Each distinct resGroup with 2+ member resources,
where EVERY member is itself a PlanetResource_Deposit node type (checked
against game_data_extract/resource_nodes.json - depositGroupSizes also
covers RegularNode/Geyser co-spawn clusters, which are a different kind of
fact and deliberately excluded here, see composite_rows_for_planet's own
docstring), becomes its own extra galaxy_resources row named e.g. "Coal
Deposit / Iron Deposit", independently searchable/rankable from either
member alone. Its count/density are a conservative MIN across members, not
an exact per-spot figure - see composite_rows_for_planet's own docstring
for the full reasoning.

Also imports galaxy_systems (a separate table, see load_system_rows and
backend.db's own docstring for it) from systemPosition/nearSystemNames -
system-level facts carried on every planet entry, including planets with
no resourceCounts at all (a system with no mineral data can still be a
real jump-hop on the way to one that does, so it's collected independently
of the resourceCounts-gated logic above). Powers the Galaxy sub-tab's
"current system" jump-hop distance sort - see get_galaxy_hop_distances'
own docstring for why hop count (not straight-line systemPosition
distance) is the meaningful "closest" metric for travel planning.

Usage:
    python tools/backfill_galaxy_resources.py
    python tools/backfill_galaxy_resources.py --dump-path path/to/galaxy_resources.json
    python tools/backfill_galaxy_resources.py --dry-run   # report what would be
                                                             # added, no writes
"""
import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend import db  # noqa: E402
from backend.db import init_db  # noqa: E402
from tools.report_resource_name_mismatches import (  # noqa: E402
    DEPOSIT_ITEM_TYPE,
    load_node_item_types,
)

# Local-machine-only default - the sibling repo's own dump output, never
# copied into this repo (see this module's own docstring).
DEFAULT_DUMP_PATH = (
    REPO_ROOT.parent / "spacecraft-memory-research" / "galaxy_resources.json"
)

# st.PlanetResourceManager.getDensityCount's own POI-surface constant - see
# dump_galaxy_resources.py's compute_density (PLANET_DENSITY_POI_SCALE).
# Reused verbatim rather than re-derived, so this matches the game's own
# formula exactly.
PLANET_DENSITY_POI_SCALE = 5


def angle_from_distance(size, radius=1.0):
    """lib.Helper.angleFromDistance, decompiled - see
    dump_galaxy_resources.py's own copy of this function for the full
    derivation. Reused unmodified so poi_surface below matches the game's
    own math exactly."""
    k = math.floor(size / radius)
    if k < 0:
        return 0.0
    return math.asin(size / radius - k) + (math.pi / 2) * k


def poi_surface(poi_size):
    """A POI's raw `size` converted to its surface-area fraction of the
    planet, via the same angleFromDistance-based conversion
    compute_density (dump_galaxy_resources.py) already applies internally
    to scale its own generation-quota estimate down for POI-anchored
    resources. Reused here for a different purpose: dividing `density`
    (not raw node_count - see poi_area_density's own note in load_rows) by
    this gives an area-adjusted density directly comparable to a "general"
    resource's own `density`, since compute_density's own formula never
    applies this scaling for non-POI-anchored resources at all - i.e. it
    implicitly treats "general" as covering area-fraction 1. Dividing by a
    fraction less than 1 is exactly the same operation the game's own
    generation code performs when shrinking a quota for a small POI, just
    applied to an exact live count instead of a generation-quota estimate."""
    angle = angle_from_distance(poi_size)
    return (angle * 2) ** 2 * PLANET_DENSITY_POI_SCALE / (4 * math.pi)


# Joins a resGroup's member resource names into one composite entity name -
# see composite_rows_for_planet's own docstring for why these need to exist
# as their own searchable galaxy_resources rows, not just an annotation on
# each member's individual row.
COMPOSITE_NAME_SEP = " / "


def composite_resource_name(names):
    return COMPOSITE_NAME_SEP.join(sorted(names))


def composite_rows_for_planet(deposit_group_sizes, counts, densities, node_item_types):
    """One (name, count, density) tuple per distinct resGroup in
    depositGroupSizes that has 2+ distinct resource names, live count data
    for ALL of them on this planet, AND is made up ENTIRELY of
    PlanetResource_Deposit (auto-drilled) node types - e.g.
    GD_3_IronTitaniumCarbon's ['Coal Deposit', 'Iron Deposit', 'Titanium
    Deposit'] becomes a single "Coal Deposit / Iron Deposit / Titanium
    Deposit" entity.

    Why this needs to be a real row of its own rather than a note on each
    member's individual row: a resGroup is a single physical drilling spot
    an auto-extractor sits on - "does this planet have a spot that produces
    BOTH Coal and Iron together" is a genuinely different question than
    "does this planet have Coal" and "does this planet have Iron"
    separately (a planet can easily have both without them being
    co-located), so it needs to be independently searchable/rankable, not
    merely surfaced while browsing a single resource.

    Why the itemType filter: resGroup co-spawn data isn't exclusive to
    Deposit-type auto-extractor clusters - the SAME depositGroupSizes field
    also carries resGroups for regular hand-gathered surface nodes
    (PlanetResource_RegularNode) and geysers, confirmed against live dump
    data (see tests/test_backfill_galaxy_resources.py). "One auto-extractor
    covers both ores" is a real, useful distinction for Deposit-type
    resources; for a RegularNode or Geyser, "found near each other" isn't
    the same kind of fact and isn't what this feature was built for, so
    those combinations are skipped entirely rather than synthesizing a
    misleading composite entity for them.

    depositGroupSizes only tells us WHICH resources share a resGroup on
    this planet, not how resourceCounts/resourceDensities (unsplit by
    resGroup variant) divide between that shared spot and any OTHER
    resGroup a member resource might also independently spawn in - so
    node_count/density for the composite row is the MIN across its
    members: a conservative lower bound on what that specific shared spot
    actually provides (never overstates it), not a claim at an exact
    per-spot figure the dump data can't provide.

    Deposit-type resources are confirmed (checked against live dump data)
    to never carry a POI tag - they're auto-drilled planet-wide, not tied
    to a walkable POI - so composite rows always rank on plain density,
    same as any other "general" resource; callers should not attempt
    poi_area_density for them."""
    seen = set()
    combos = []
    for group in deposit_group_sizes or []:
        names = sorted({s.get("resource") for s in (group.get("sizes") or []) if s.get("resource")})
        if len(names) < 2:
            continue
        if not all(node_item_types.get(n) == DEPOSIT_ITEM_TYPE for n in names):
            continue
        key = tuple(names)
        if key in seen or not all(n in counts for n in names):
            continue
        seen.add(key)
        density = min(densities[n] for n in names) if all(n in densities for n in names) else None
        combos.append((composite_resource_name(names), min(counts[n] for n in names), density))
    return combos


def load_rows(dump_path):
    planets = json.loads(dump_path.read_text(encoding="utf-8"))
    node_item_types = load_node_item_types()
    rows = []
    for p in planets:
        system_name = p.get("system_name")
        planet = p.get("planet_name")
        counts = p.get("resourceCounts") or {}
        if not system_name or not planet or not counts:
            continue
        sector = p.get("sector_name")
        densities = p.get("resourceDensities") or {}
        poi_sizes = p.get("poiSizes") or {}
        is_asteroid = p.get("isAsteroid")
        temperature = p.get("temperature")
        temperature_name = p.get("temperatureName")
        attributes = p.get("attributes") or []
        attribute_names = p.get("attributeNames") or []

        poi_tags_by_resource = {}
        for poi_label, resource_names in (p.get("resourcesByPoi") or {}).items():
            for name in resource_names:
                poi_tags_by_resource.setdefault(name, set()).add(poi_label)

        for resource, count in counts.items():
            poi_tags = poi_tags_by_resource.get(resource)
            poi_area_density = None
            resource_density = densities.get(resource)
            if poi_tags and "general" not in poi_tags and resource_density is not None:
                sizes = [poi_sizes.get(tag) for tag in poi_tags]
                if all(s is not None for s in sizes):
                    total_surface = sum(poi_surface(s) for s in sizes)
                    if total_surface:
                        # density, not raw count - density already carries the
                        # same PLANET_DENSITY_CONSTANT/scale^2 normalization a
                        # "general" resource's own density has, so dividing
                        # THAT by the POI's area fraction is what stays
                        # directly comparable to a general resource's density
                        # (see poi_surface's own docstring for why).
                        poi_area_density = resource_density / total_surface
            rows.append((
                system_name,
                planet,
                sector,
                resource,
                count,
                densities.get(resource),
                ",".join(sorted(poi_tags)) if poi_tags else None,
                poi_area_density,
                is_asteroid,
                temperature,
                temperature_name,
                ",".join(attributes) if attributes else None,
                ",".join(attribute_names) if attribute_names else None,
            ))

        for combo_name, combo_count, combo_density in composite_rows_for_planet(
            p.get("depositGroupSizes"), counts, densities, node_item_types
        ):
            rows.append((
                system_name,
                planet,
                sector,
                combo_name,
                combo_count,
                combo_density,
                None,  # poi_tags - Deposit-type resources are never POI-anchored
                None,  # poi_area_density
                is_asteroid,
                temperature,
                temperature_name,
                ",".join(attributes) if attributes else None,
                ",".join(attribute_names) if attribute_names else None,
            ))
    return rows


def load_system_rows(dump_path):
    """One (system_name, x, y, z, near_system_names) tuple per distinct
    system_name across ALL planet entries in the dump - independent of
    whether that planet has resourceCounts (unlike load_rows above), since
    systemPosition/nearSystemNames are system-level facts and a system with
    no mineral data can still be a real jump-hop on the way to one that
    does. First-seen entry per system wins (identical across every planet
    in the same system anyway - both fields describe the SYSTEM, not the
    planet, even though the dump repeats them on every planet entry)."""
    planets = json.loads(dump_path.read_text(encoding="utf-8"))
    seen = {}
    for p in planets:
        system_name = p.get("system_name")
        if not system_name or system_name in seen:
            continue
        pos = p.get("systemPosition") or {}
        near = p.get("nearSystemNames") or []
        seen[system_name] = (
            system_name,
            pos.get("x"),
            pos.get("y"),
            pos.get("z"),
            ",".join(near) if near else None,
        )
    return list(seen.values())


def load_poi_landmark_rows(dump_path):
    """One (system_name, planet, poi_index, landmark_name, indicator_id,
    sun_side, light_value, area) tuple per POI - poiLandmarks (per planet,
    keyed "poi0"/"poi1"/... - the SAME index space as poiSizes/
    resourcesByPoi, confirmed against the live dump, so this lines up
    directly with galaxy_resources.poi_tags with no translation needed).
    Every in-game POI turns out to have a landmark - confirmed empirically
    across the full live dump, poiSizes and poiLandmarks share the exact
    same index set for every planet, zero gaps either direction - one of
    only 3 landmark kinds (Meteor Crater/High Peak/Natural Canyon,
    indicatorId BalisePOI/BalisePOI1/BalisePOI2 - see
    tools/extract_poi_icons.py, which crops their icons from the game's own
    UI sprite sheet). `color` (the dump's own poiLandmarks[*].color field,
    always null - the only traced icon-selection code path never routes
    through the game's own ColorPOI1..5 rows) is likewise NOT carried over
    here, but NOT because color is unknowable: the real per-planet marker
    color is fully reproducible from poi_index alone (reverse-engineered
    selection rule: colorSlot = ordinal-position-in-planet's-POI-list % 5 -
    NOT tied to landmark kind at all), so it's computed client-side
    (js/galaxy.js's poiMarkerColor) rather than stored redundantly here.
    sun_side/light_value ARE real per-POI facts (the planet's lighting at
    that landmark's location - planets don't rotate in this game, so this
    doesn't go stale). area is poi_surface(poiSizes[poi_index]) - this
    POI's OWN surface-area fraction, the same conversion load_rows already
    applies when combining ALL of a resource's POIs into one
    poi_area_density figure, just kept per-POI here instead - lets
    js/galaxy.js's survivingAreaFraction estimate how much of a row's
    density survives once some of its POIs are excluded by the lighting
    filter, weighted by each excluded POI's actual size rather than
    assuming every POI on a planet is equally sized. None when this POI's
    size wasn't in poiSizes."""
    planets = json.loads(dump_path.read_text(encoding="utf-8"))
    rows = []
    for p in planets:
        system_name = p.get("system_name")
        planet = p.get("planet_name")
        if not system_name or not planet:
            continue
        poi_sizes = p.get("poiSizes") or {}
        for poi_index, landmark in (p.get("poiLandmarks") or {}).items():
            size = poi_sizes.get(poi_index)
            rows.append((
                system_name,
                planet,
                poi_index,
                landmark.get("name"),
                landmark.get("indicatorId"),
                landmark.get("sunSide"),
                landmark.get("lightValue"),
                poi_surface(size) if size is not None else None,
            ))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-path",
        default=str(DEFAULT_DUMP_PATH),
        help="galaxy_resources.json dump to import"
        " (default: ../spacecraft-memory-research/galaxy_resources.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many rows would be added without writing anything",
    )
    args = parser.parse_args()

    dump_path = Path(args.dump_path)
    if not dump_path.exists():
        print(f"No dump found at {dump_path}", file=sys.stderr)
        raise SystemExit(1)

    init_db()
    rows = load_rows(dump_path)
    system_rows = load_system_rows(dump_path)
    landmark_rows = load_poi_landmark_rows(dump_path)

    if args.dry_run:
        existing = db.get_galaxy_resource_keys()
        new_rows = [r for r in rows if (r[0], r[1], r[3]) not in existing]
        print(
            f"Would add {len(new_rows)} of {len(rows)} parsed resource rows"
            f" ({len(rows) - len(new_rows)} already present) from {dump_path}."
        )
        existing_systems = set(db.get_galaxy_system_names())
        new_systems = [s for s in system_rows if s[0] not in existing_systems]
        print(
            f"Would add/refresh {len(system_rows)} systems' position/neighbor data"
            f" ({len(new_systems)} not previously known) for jump-hop distance."
        )
        print(f"Would add/refresh {len(landmark_rows)} POI landmarks (sun-side/lighting data).")
        return

    inserted = db.import_galaxy_resources(rows)
    print(
        f"Imported {inserted} new resource rows"
        f" ({len(rows) - inserted} already present) from {dump_path}."
    )
    db.import_galaxy_systems(system_rows)
    print(f"Refreshed position/neighbor data for {len(system_rows)} systems.")
    db.import_galaxy_poi_landmarks(landmark_rows)
    print(f"Refreshed {len(landmark_rows)} POI landmarks (sun-side/lighting data).")


if __name__ == "__main__":
    main()
