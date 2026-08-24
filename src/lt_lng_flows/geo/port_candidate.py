"""
port_candidate.py
--------------------
Session 2, build plan 4.3, sessions_02_03_build_plan.md 2.7. Builds
``crosswalks/dim_port_candidate.csv``: one row per liquefaction or regas
project, with ``node_id``, ``country_iso2``, ``ea_project_name`` and
``port_role`` populated from the workbooks, then a single automated
assignment attempt against the pulled port gazetteer.

Preferred source order was set in ``config/geo_sources.yaml``; this session's
pull actually landed Natural Earth 10m ports (the World Port Index pull
failed with HTTP 403, see the pull manifest), which carries no country
attribute of its own. Country is derived here by a point-in-polygon spatial
join against the pinned Natural Earth Admin 0 geometry already loaded for
``dim_country`` -- a deterministic geometric operation on two already-pinned
snapshots, not a name match, so it is not the "fuzzy join" CLAUDE.md
forbids. A port with no enclosing country polygon at 1:50m resolution
(small islands can fall in gaps) is left with a null country and is
therefore never proposed.

Matching an EA project name to a gazetteer port name is exact,
case-insensitive, and scoped to the same country only. Everything else is
`method = unresolved`, coordinates null. No fuzzy matching, no edit
distance, no nearest-port-in-country (build plan 2.7).
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd


def load_port_gazetteer_with_country(
    ports_shapefile: gpd.GeoDataFrame, dissolved_country_geometry: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Assign each gazetteer port point a country_iso2 by point-in-polygon
    join against the dissolved Natural Earth country geometry. Returns
    columns: gazetteer_id, gazetteer_port_name, country_iso2 (nullable),
    latitude, longitude.
    """
    ports = ports_shapefile[["name", "ne_id", "geometry"]].copy()
    joined = gpd.sjoin(
        ports,
        dissolved_country_geometry[["country_iso2", "geometry"]],
        how="left",
        predicate="within",
    )
    joined = joined.drop_duplicates(subset="ne_id")
    out = pd.DataFrame(
        {
            "gazetteer_id": joined["ne_id"],
            "gazetteer_port_name": joined["name"],
            "country_iso2": joined["country_iso2"],
            "latitude": joined.geometry.y,
            "longitude": joined.geometry.x,
        }
    )
    return out.reset_index(drop=True)


def build_dim_port_candidate(
    project_rows: list[dict],
    port_role_by_source_system: dict[str, str],
    applied_crosswalk: pd.DataFrame,
    node_by_country: pd.DataFrame,
    port_gazetteer: pd.DataFrame,
) -> pd.DataFrame:
    """``project_rows``: dicts with source_system, project, country_raw
    (matching workbook_reader.read_project_capacity's shape; capacity is
    ignored here). ``node_by_country``: country_iso2 -> node_id for
    single-node countries only (see node_master.py); split-country projects
    get an empty node_id for the same reason xwalk_project_node does.
    """
    xwalk_map = {
        (row["source_system"], row["raw_value"]): row["country_iso2"]
        for _, row in applied_crosswalk.iterrows()
    }
    node_map = (
        node_by_country.set_index("country_iso2")["node_id"]
        if len(node_by_country)
        else pd.Series(dtype=str)
    )

    gazetteer_by_country: dict[str, pd.DataFrame] = {
        code: group
        for code, group in port_gazetteer.dropna(subset=["country_iso2"]).groupby("country_iso2")
    }
    # Case-insensitive exact name index per country.
    name_index: dict[str, dict[str, pd.Series]] = {}
    for code, group in gazetteer_by_country.items():
        name_index[code] = {}
        for _, port_row in group.iterrows():
            key = str(port_row["gazetteer_port_name"]).strip().lower()
            # First match wins; a duplicate name within one country is
            # reported via the row count, not silently overwritten twice.
            name_index[code].setdefault(key, port_row)

    rows = []
    for record in project_rows:
        key = (record["source_system"], record["country_raw"])
        if key not in xwalk_map:
            raise ValueError(f"build_dim_port_candidate: unresolved raw value {key!r}")
        country_iso2 = xwalk_map[key]
        node_id = node_map.get(country_iso2, "")
        port_role = port_role_by_source_system[record["source_system"]]
        project_name = str(record["project"]).strip()

        candidates = name_index.get(country_iso2, {})
        match = candidates.get(project_name.lower())
        if match is not None:
            method, confidence = "exact_name", "high"
            gazetteer_port_name = match["gazetteer_port_name"]
            gazetteer_id = match["gazetteer_id"]
            latitude, longitude = match["latitude"], match["longitude"]
        else:
            method, confidence = "unresolved", "none"
            gazetteer_port_name, gazetteer_id, latitude, longitude = "", "", None, None

        rows.append(
            {
                "node_id": node_id,
                "country_iso2": country_iso2,
                "ea_project_name": project_name,
                "port_role": port_role,
                "gazetteer_port_name": gazetteer_port_name,
                "gazetteer_id": gazetteer_id,
                "latitude": latitude,
                "longitude": longitude,
                "method": method,
                "confidence": confidence,
                "source": "natural_earth_10m_ports",
                "note": ""
                if method == "exact_name"
                else "no exact case-insensitive name match within country",
            }
        )

    columns = [
        "node_id",
        "country_iso2",
        "ea_project_name",
        "port_role",
        "gazetteer_port_name",
        "gazetteer_id",
        "latitude",
        "longitude",
        "method",
        "confidence",
        "source",
        "note",
    ]
    return pd.DataFrame(rows, columns=columns)
