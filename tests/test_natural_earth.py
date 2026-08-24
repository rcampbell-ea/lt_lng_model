"""
Unit tests for lt_lng_flows.geo.natural_earth on synthetic geometry, so the
dissolve/centroid/adjacency/landlocked logic is checked independently of the
pulled snapshot (build plan 4.8 checks 1, 4, 8, 9).
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, box

from lt_lng_flows.geo import natural_earth as ne

TYPE_ORDER = [
    "Sovereign country",
    "Country",
    "Sovereignty",
    "Disputed",
    "Indeterminate",
    "Dependency",
]


def _admin0_row(name, type_, iso_a2, iso_a2_eh, iso_a3, iso_a3_eh, continent, subregion, geometry):
    return {
        "NAME": name,
        "TYPE": type_,
        "ISO_A2": iso_a2,
        "ISO_A2_EH": iso_a2_eh,
        "ISO_A3": iso_a3,
        "ISO_A3_EH": iso_a3_eh,
        "CONTINENT": continent,
        "SUBREGION": subregion,
        "geometry": geometry,
    }


def test_patched_iso2_prefers_eh_over_disputed_code():
    """Reproduces the pinned vintage's Taiwan encoding: ISO_A2='CN-TW' (not
    a valid two-letter code) while ISO_A2_EH='TW' is correct (build plan
    trap 5).
    """
    row = _admin0_row(
        "Taiwan",
        "Sovereign country",
        "CN-TW",
        "TW",
        "TWN",
        "TWN",
        "Asia",
        "E Asia",
        box(0, 0, 1, 1),
    )
    gdf = gpd.GeoDataFrame([row])
    patched = ne.patched_iso2(gdf)
    assert patched.iloc[0] == "TW"


def test_patched_iso2_falls_back_to_iso_a2_for_negative99_eh():
    row = _admin0_row(
        "Nowhereland", "Disputed", "XX", "-99", "-99", "-99", "Asia", "E Asia", box(0, 0, 1, 1)
    )
    gdf = gpd.GeoDataFrame([row])
    patched = ne.patched_iso2(gdf)
    assert patched.iloc[0] == "XX"


def test_dissolve_unions_multiple_rows_and_reports_inconsistency():
    rows = [
        _admin0_row(
            "Mainland",
            "Sovereign country",
            "AU",
            "AU",
            "AUS",
            "AUS",
            "Oceania",
            "ANZ",
            box(0, 0, 1, 1),
        ),
        _admin0_row(
            "Island Territory",
            "Dependency",
            "AU",
            "AU",
            "AUS",
            "AUS",
            "Asia",
            "Seven seas",
            box(2, 2, 3, 3),
        ),
        _admin0_row(
            "France",
            "Sovereign country",
            "FR",
            "FR",
            "FRA",
            "FRA",
            "Europe",
            "W Europe",
            box(5, 5, 6, 6),
        ),
    ]
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    dissolved, inconsistencies = ne.dissolve_by_country_iso2(gdf, TYPE_ORDER)
    assert set(dissolved["country_iso2"]) == {"AU", "FR"}
    au_row = dissolved[dissolved["country_iso2"] == "AU"].iloc[0]
    assert au_row["continent"] == "Oceania"
    assert au_row["admin0_row_count"] == 2
    assert isinstance(au_row.geometry, MultiPolygon)
    assert len(inconsistencies) == 1
    assert inconsistencies[0]["country_iso2"] == "AU"


def test_pole_of_inaccessibility_is_interior_for_concave_polygon():
    # An L-shaped (concave) polygon: the plain bounding-box centroid would
    # land in the notch, outside the shape.
    concave = Polygon([(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)])
    point = ne.pole_of_inaccessibility(concave, precision=0.01)
    assert concave.contains(point)


def test_compute_adjacency_is_symmetric_for_touching_squares():
    rows = [
        _admin0_row("A", "Sovereign country", "AA", "AA", "AAA", "AAA", "X", "X", box(0, 0, 1, 1)),
        _admin0_row("B", "Sovereign country", "BB", "BB", "BBB", "BBB", "X", "X", box(1, 0, 2, 1)),
        _admin0_row("C", "Sovereign country", "CC", "CC", "CCC", "CCC", "X", "X", box(5, 5, 6, 6)),
    ]
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    dissolved, _ = ne.dissolve_by_country_iso2(gdf, TYPE_ORDER)
    adjacency = ne.compute_adjacency(dissolved, buffer_degrees=0.001)
    pairs = set(map(tuple, adjacency.values.tolist()))
    assert ("AA", "BB") in pairs
    assert ("BB", "AA") in pairs
    assert ("AA", "CC") not in pairs


def test_compute_is_landlocked_true_for_fully_enclosed_country():
    # B is a 1x1 square fully surrounded by A (a 3x3 square with a 1x1 hole).
    outer = box(0, 0, 3, 3)
    hole = box(1, 1, 2, 2)
    a_geom = outer.difference(hole)
    b_geom = hole

    rows = [
        _admin0_row("A", "Sovereign country", "AA", "AA", "AAA", "AAA", "X", "X", a_geom),
        _admin0_row("B", "Sovereign country", "BB", "BB", "BBB", "BBB", "X", "X", b_geom),
    ]
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    dissolved, _ = ne.dissolve_by_country_iso2(gdf, TYPE_ORDER)
    landlocked = ne.compute_is_landlocked(dissolved, buffer_degrees=0.001).set_index("country_iso2")
    assert landlocked.loc["BB", "is_landlocked"] == True  # noqa: E712
    assert landlocked.loc["AA", "is_landlocked"] == False  # noqa: E712
