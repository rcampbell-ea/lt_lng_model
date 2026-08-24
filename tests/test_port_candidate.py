"""
Unit tests for lt_lng_flows.geo.port_candidate: exact-name-within-country
matching only, no fuzzy matching, coordinates null on every unresolved row
(build plan 2.7, 2.9).
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from lt_lng_flows.geo import port_candidate


def test_load_port_gazetteer_with_country_spatial_join():
    ports = gpd.GeoDataFrame(
        {"name": ["Ras Laffan", "Nowhere Port"], "ne_id": [1, 2]},
        geometry=[Point(51.6, 25.9), Point(500, 500)],
        crs="EPSG:4326",
    )
    countries = gpd.GeoDataFrame(
        {"country_iso2": ["QA"]}, geometry=[box(50, 24, 52, 27)], crs="EPSG:4326"
    )
    result = port_candidate.load_port_gazetteer_with_country(ports, countries)
    assert result.loc[result["gazetteer_id"] == 1, "country_iso2"].iloc[0] == "QA"
    assert pd.isna(result.loc[result["gazetteer_id"] == 2, "country_iso2"].iloc[0])


def _port_row(gazetteer_id, name, country_iso2, latitude, longitude):
    return {
        "gazetteer_id": gazetteer_id,
        "gazetteer_port_name": name,
        "country_iso2": country_iso2,
        "latitude": latitude,
        "longitude": longitude,
    }


def test_exact_match_only_within_same_country_case_insensitive():
    applied_crosswalk = pd.DataFrame(
        [
            {"source_system": "workbook_liquefaction", "raw_value": "Qatar", "country_iso2": "QA"},
            {
                "source_system": "workbook_liquefaction",
                "raw_value": "Nigeria",
                "country_iso2": "NG",
            },
        ]
    )
    node_by_country = pd.DataFrame(
        [{"country_iso2": "QA", "node_id": "qatar"}, {"country_iso2": "NG", "node_id": "nigeria"}]
    )
    port_gazetteer = pd.DataFrame(
        [
            _port_row(1, "ras laffan", "QA", 25.9, 51.6),
            # Same name, wrong country: must never match across borders.
            _port_row(2, "Ras Laffan", "NG", 4.0, 7.0),
        ]
    )
    project_rows = [
        {"source_system": "workbook_liquefaction", "project": "Ras Laffan", "country_raw": "Qatar"},
        {"source_system": "workbook_liquefaction", "project": "Bonny", "country_raw": "Nigeria"},
    ]
    result = port_candidate.build_dim_port_candidate(
        project_rows,
        {"workbook_liquefaction": "load"},
        applied_crosswalk,
        node_by_country,
        port_gazetteer,
    )

    ras_laffan_row = result[result["ea_project_name"] == "Ras Laffan"].iloc[0]
    assert ras_laffan_row["method"] == "exact_name"
    assert ras_laffan_row["country_iso2"] == "QA"
    assert ras_laffan_row["latitude"] == 25.9

    bonny_row = result[result["ea_project_name"] == "Bonny"].iloc[0]
    assert bonny_row["method"] == "unresolved"
    assert bonny_row["confidence"] == "none"
    assert pd.isna(bonny_row["latitude"])
    assert pd.isna(bonny_row["longitude"])
