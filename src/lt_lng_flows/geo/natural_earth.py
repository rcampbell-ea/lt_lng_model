"""
natural_earth.py
-------------------
Session 2, build plan 4.2 to 4.5. Reads the pinned Natural Earth Admin 0
Countries 1:50m snapshot and turns it into the geometry-derived pieces of
``dim_country`` (build plan 4.3) plus ``geo_country_geometry`` and
``dim_country_adjacency`` (build plan 4.3, 4.5).

Field schemas are read from the actual pulled shapefile, not assumed (build
plan 4.2): this module asserts the columns it needs are present rather than
hardcoding an index.

Natural Earth vintages carry ``ISO_A2`` as ``-99`` for several entities
(build plan 4.5 trap 1), and can carry more than one admin0 row for a single
ISO2 code (dependencies and island territories reported as separate polygons
of the same sovereign country, e.g. Australia plus Indian Ocean Territory and
Ashmore and Cartier Islands in the 2022-05 vintage). Both are handled here:
the ``-99`` values are patched from ``ISO_A2_EH``, and rows sharing one
ISO2 are dissolved into a single geometry, with the continent/subregion/
display-name attributes taken from whichever row is the most "primary"
polity per ``type_preference_order`` in ``config/session_02_constants.yaml``.
"""

from __future__ import annotations

import heapq
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

REQUIRED_ADMIN0_COLUMNS = {
    "NAME",
    "TYPE",
    "ISO_A2",
    "ISO_A2_EH",
    "ISO_A3",
    "ISO_A3_EH",
    "CONTINENT",
    "SUBREGION",
    "geometry",
}
NON_COUNTRY_ISO2 = {"-99"}


def read_admin0(shapefile_path: Path) -> gpd.GeoDataFrame:
    if not shapefile_path.is_file():
        raise FileNotFoundError(f"Natural Earth admin0 shapefile not found: {shapefile_path}")
    gdf = gpd.read_file(shapefile_path)
    missing = REQUIRED_ADMIN0_COLUMNS - set(gdf.columns)
    if missing:
        raise ValueError(
            f"{shapefile_path.name}: expected columns {sorted(missing)} not found in the "
            f"pulled snapshot; field schema has moved and must be re-read, not assumed"
        )
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        raise ValueError(f"{shapefile_path.name}: expected EPSG:4326, found {gdf.crs}")
    return gdf


def patched_iso2(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Build plan 4.5 trap 1, and trap 5 (Taiwan) discovered empirically in
    the same field: ``ISO_A2_EH`` is used ahead of ``ISO_A2`` in every case,
    not only where ``ISO_A2`` is ``-99``. The pinned vintage encodes
    Taiwan's ``ISO_A2`` as the non-ISO value ``"CN-TW"`` rather than ``-99``,
    reflecting a political dispute Natural Earth is taking a side on; only
    ``ISO_A2_EH`` gives the plain ``TW`` the plan's trap 5 requires
    regardless of how a third party layer labels it. Falling back to
    ``ISO_A2`` only where ``ISO_A2_EH`` is itself ``-99`` never actually
    triggers in the pinned vintage (checked: every row where ``ISO_A2`` is
    ``-99`` has a valid ``ISO_A2_EH`` except the three non-ISO entities --
    Somaliland, Northern Cyprus, Siachen Glacier -- which are correctly
    dropped, not patched, because there is no ISO2 to patch them to).
    """
    iso2 = gdf["ISO_A2_EH"].where(gdf["ISO_A2_EH"] != "-99", gdf["ISO_A2"])
    return iso2


def _rank_type(type_value: str, type_preference_order: list[str]) -> int:
    try:
        return type_preference_order.index(type_value)
    except ValueError:
        return len(type_preference_order)


def dissolve_by_country_iso2(
    gdf: gpd.GeoDataFrame, type_preference_order: list[str]
) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """One row per real country_iso2: geometry is the union of every admin0
    row sharing that code; display attributes (name, continent, subregion,
    iso3) come from the single most "primary" row per
    ``type_preference_order``.

    When a country's admin0 rows disagree on continent or subregion (seen in
    the pinned vintage for AU, whose Indian Ocean Territory row is tagged
    Asia/"Seven seas" against the mainland's Oceania/"Australia and New
    Zealand"), the primary row's value is used and the disagreement is
    returned in the second element rather than raised: this is a known
    artefact of how Natural Earth classifies island territories, not a data
    quality question for EA, and it must not silently disappear either, so
    it is reported in ``docs/session_02_geo_master.md``.
    """
    working = gdf.copy()
    working["country_iso2"] = patched_iso2(working)
    working = working[~working["country_iso2"].isin(NON_COUNTRY_ISO2)].copy()
    working["_type_rank"] = working["TYPE"].map(lambda t: _rank_type(t, type_preference_order))

    rows = []
    inconsistencies: list[dict] = []
    for iso2, group in working.groupby("country_iso2"):
        primary = group.sort_values("_type_rank").iloc[0]
        if group["CONTINENT"].nunique() > 1 or group["SUBREGION"].nunique() > 1:
            inconsistencies.append(
                {
                    "country_iso2": iso2,
                    "continent_values": sorted(group["CONTINENT"].unique().tolist()),
                    "subregion_values": sorted(group["SUBREGION"].unique().tolist()),
                    "resolved_continent": primary["CONTINENT"],
                    "resolved_subregion": primary["SUBREGION"],
                    "resolved_from_row": primary["NAME"],
                }
            )
        geometry = unary_union(group.geometry.tolist())
        rows.append(
            {
                "country_iso2": iso2,
                "country_name_ne": primary["NAME"],
                "country_iso3_ne": primary["ISO_A3_EH"]
                if primary["ISO_A3_EH"] != "-99"
                else primary["ISO_A3"],
                "continent": primary["CONTINENT"],
                "un_subregion": primary["SUBREGION"],
                "admin0_row_count": len(group),
                "geometry": geometry,
            }
        )

    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf.crs)
    return out.sort_values("country_iso2").reset_index(drop=True), inconsistencies


def _largest_polygon(geometry: BaseGeometry) -> Polygon:
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        return max(geometry.geoms, key=lambda g: g.area)
    raise ValueError(f"expected Polygon or MultiPolygon, got {type(geometry).__name__}")


def _cell_potential(cx: float, cy: float, half: float, distance_to_boundary: float) -> float:
    return distance_to_boundary + half * math.sqrt(2)


def pole_of_inaccessibility(geometry: BaseGeometry, precision: float = 0.01) -> Point:
    """Mapbox-style polylabel: the point inside the polygon that maximises
    distance to the boundary, found by quadtree refinement over a priority
    queue rather than a plain centroid, so it sits inside concave and
    multipart shapes (build plan 4.3). Precision is in the geometry's own
    units (degrees, for EPSG:4326).

    Operates on the largest ring of a multipolygon: the representative point
    for an archipelagic country is inside its main landmass, not averaged
    across disconnected islands.
    """
    polygon = _largest_polygon(geometry)
    minx, miny, maxx, maxy = polygon.bounds
    width = maxx - minx
    height = maxy - miny
    cell_size = min(width, height)
    if cell_size == 0:
        return polygon.representative_point()
    half = cell_size / 2.0

    best_cx = minx + width / 2.0
    best_cy = miny + height / 2.0
    best_distance = _signed_distance(polygon, best_cx, best_cy)

    heap: list[tuple] = []
    counter = 0
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            cx, cy = x + half, y + half
            d = _signed_distance(polygon, cx, cy)
            potential = _cell_potential(cx, cy, half, d)
            counter += 1
            heapq.heappush(heap, (-potential, counter, cx, cy, half, d))
            y += cell_size
        x += cell_size

    if best_distance is not None:
        centroid_potential = _cell_potential(best_cx, best_cy, half, best_distance)
        counter += 1
        heapq.heappush(heap, (-centroid_potential, counter, best_cx, best_cy, half, best_distance))

    best_cx, best_cy, best_distance = None, None, -math.inf
    while heap:
        neg_potential, _, cx, cy, half, d = heapq.heappop(heap)
        potential = -neg_potential
        if d > best_distance:
            best_cx, best_cy, best_distance = cx, cy, d
        if potential - best_distance <= precision:
            continue
        new_half = half / 2.0
        for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            ncx, ncy = cx + dx * new_half, cy + dy * new_half
            nd = _signed_distance(polygon, ncx, ncy)
            npotential = _cell_potential(ncx, ncy, new_half, nd)
            counter += 1
            heapq.heappush(heap, (-npotential, counter, ncx, ncy, new_half, nd))

    point = Point(best_cx, best_cy)
    if not polygon.contains(point):
        # Precision-limited edge case on a very thin polygon: fall back to a
        # point shapely itself guarantees is interior, rather than emitting
        # an exterior point (build plan 4.4, checked by geo_checks).
        point = polygon.representative_point()
    return point


def _signed_distance(polygon: Polygon, x: float, y: float) -> float:
    point = Point(x, y)
    distance = point.distance(polygon.boundary)
    return distance if polygon.contains(point) else -distance


def compute_centroids(dissolved: gpd.GeoDataFrame, precision: float = 0.01) -> pd.DataFrame:
    rows = []
    for _, row in dissolved.iterrows():
        point = pole_of_inaccessibility(row.geometry, precision=precision)
        rows.append(
            {
                "country_iso2": row["country_iso2"],
                "centroid_lat": point.y,
                "centroid_lon": point.x,
            }
        )
    return pd.DataFrame(rows)


def compute_adjacency(dissolved: gpd.GeoDataFrame, buffer_degrees: float) -> pd.DataFrame:
    """Build plan 4.3: shared land border, from the geometry. Two countries
    are adjacent if their (buffered) polygons touch or overlap. The buffer
    absorbs 1:50m vector digitising slack between two borders that are the
    same line in reality but not bit-identical in this dataset. Symmetric by
    construction: both (a, b) and (b, a) are written.
    """
    codes = dissolved["country_iso2"].tolist()
    geoms = {
        row["country_iso2"]: row.geometry.buffer(buffer_degrees) for _, row in dissolved.iterrows()
    }
    sindex = gpd.GeoSeries(geoms.values(), index=list(geoms.keys())).sindex

    pairs: set[tuple[str, str]] = set()
    for a in codes:
        candidate_idx = sindex.query(geoms[a], predicate="intersects")
        candidate_codes = [codes[i] for i in candidate_idx]
        for b in candidate_codes:
            if b == a:
                continue
            if geoms[a].intersects(geoms[b]):
                pairs.add((a, b))
                pairs.add((b, a))

    rows = sorted(pairs)
    return pd.DataFrame(rows, columns=["country_iso2_a", "country_iso2_b"])


def compute_is_landlocked(dissolved: gpd.GeoDataFrame, buffer_degrees: float) -> pd.DataFrame:
    """Build plan 4.3, is_landlocked: a country whose entire boundary is
    covered by the buffered union of every other country's geometry has no
    coastline. The buffer is the same order of digitising slack used for
    adjacency, so a border and a coastline are not confused with each other.
    """
    whole = unary_union(dissolved.geometry.tolist())
    rows = []
    for _, row in dissolved.iterrows():
        others = whole.difference(row.geometry.buffer(buffer_degrees / 2))
        others_buffered = others.buffer(buffer_degrees)
        remainder = row.geometry.boundary.difference(others_buffered)
        is_landlocked = remainder.is_empty or remainder.length < buffer_degrees
        rows.append({"country_iso2": row["country_iso2"], "is_landlocked": bool(is_landlocked)})
    return pd.DataFrame(rows)
