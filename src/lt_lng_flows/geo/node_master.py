"""
node_master.py
-----------------
Session 2, build plan 4.3, sessions_02_03_build_plan.md 2.6. Builds
``dim_supply_node`` and ``dim_demand_node``: exactly the splits section 4.3
names for US, Canada, Russia and Australia, one node per country everywhere
else. Node to country aggregation is proven with real workbook capacity, not
asserted, for every country this session can actually assign projects to a
node for -- which is every country except the four split ones, because no
sub-national field exists anywhere in the pinned workbooks to assign a
project row to `us_gulf` versus `us_east` and so on. That assignment is
`xwalk_project_node` (build plan 4.3), a proposed-then-signed-off crosswalk
like the port candidates in 2.7, and it is out of scope for this session:
building it from project names would be exactly the fuzzy, invented mapping
CLAUDE.md's data model rules forbid. The gap is reported, not hidden.
"""

from __future__ import annotations

import pandas as pd


def build_node_master(
    dim_country: pd.DataFrame, split_country_nodes: dict[str, list[str]]
) -> pd.DataFrame:
    """One row per node: node_id, country_iso2, is_split_country. Applies to
    whichever of dim_supply_node / dim_demand_node the caller is building --
    the caller filters ``dim_country`` to the relevant ``role_lng`` values
    first (exporter/both for supply, importer/both for demand).
    """
    rows = []
    for _, country in dim_country.iterrows():
        code = country["country_iso2"]
        if code in split_country_nodes:
            for node_id in split_country_nodes[code]:
                rows.append({"node_id": node_id, "country_iso2": code, "is_split_country": True})
        else:
            rows.append(
                {
                    "node_id": country["country_name_slug"],
                    "country_iso2": code,
                    "is_split_country": False,
                }
            )
    return pd.DataFrame(rows, columns=["node_id", "country_iso2", "is_split_country"])


def build_supply_node(
    dim_country: pd.DataFrame, split_country_nodes: dict[str, list[str]]
) -> pd.DataFrame:
    exporters = dim_country[dim_country["role_lng"].isin(["exporter", "both"])]
    return build_node_master(exporters, split_country_nodes)


def build_demand_node(
    dim_country: pd.DataFrame, split_country_nodes: dict[str, list[str]]
) -> pd.DataFrame:
    importers = dim_country[dim_country["role_lng"].isin(["importer", "both"])]
    return build_node_master(importers, split_country_nodes)


def build_xwalk_project_node_proposed(
    capacity_rows: list[dict], applied_crosswalk: pd.DataFrame, split_country_codes: set[str]
) -> pd.DataFrame:
    """One row per project, resolving its raw country string to
    ``country_iso2`` via the applied crosswalk and proposing ``node_id`` only
    for the non-split countries, where the country's one node is unambiguous.
    Split-country rows are ``method = unresolved_split_country``,
    ``node_id = ""``: assigning them needs project-level knowledge (which
    coast, which terminal) that is not in any pinned source this session
    reads, and inventing it from the project name is exactly the fuzzy
    matching CLAUDE.md forbids.
    """
    xwalk = applied_crosswalk[
        applied_crosswalk["source_system"].isin(capacity_rows_source_systems(capacity_rows))
    ]
    xwalk_map = {
        (row["source_system"], row["raw_value"]): row["country_iso2"] for _, row in xwalk.iterrows()
    }

    rows = []
    for record in capacity_rows:
        key = (record["source_system"], record["country_raw"])
        if key not in xwalk_map:
            raise ValueError(f"build_xwalk_project_node_proposed: unresolved raw value {key!r}")
        country_iso2 = xwalk_map[key]
        if country_iso2 in split_country_codes:
            node_id, method = "", "unresolved_split_country"
        else:
            node_id, method = country_iso2, "single_node_country"
        rows.append(
            {
                "source_system": record["source_system"],
                "project": record["project"],
                "country_iso2": country_iso2,
                "capacity": record["capacity"],
                "node_id": node_id,
                "method": method,
            }
        )
    return pd.DataFrame(rows)


def capacity_rows_source_systems(capacity_rows: list[dict]) -> set[str]:
    return {r["source_system"] for r in capacity_rows}


def resolve_node_id_for_single_node_countries(
    xwalk_project_node: pd.DataFrame, dim_country: pd.DataFrame
) -> pd.DataFrame:
    """Replace the placeholder node_id (= country_iso2) used above with the
    actual country_name_slug node_id for single-node countries, so the
    result is directly comparable to dim_supply_node/dim_demand_node.
    """
    slug_by_code = dim_country.set_index("country_iso2")["country_name_slug"]
    out = xwalk_project_node.copy()
    single_mask = out["method"] == "single_node_country"
    out.loc[single_mask, "node_id"] = out.loc[single_mask, "country_iso2"].map(slug_by_code)
    return out


def check_node_country_capacity_aggregation(
    xwalk_project_node_resolved: pd.DataFrame, node_master: pd.DataFrame
) -> dict:
    """Sum project capacity by node and by country, for the rows this
    session can assign (single-node countries only), and assert the two
    aggregations agree exactly. Returns a report dict: countries proven,
    countries skipped (split, pending xwalk_project_node sign-off), and the
    capacity share that leaves untested, so the gap has a number attached
    rather than just a name.
    """
    resolved = xwalk_project_node_resolved[
        xwalk_project_node_resolved["method"] == "single_node_country"
    ]
    skipped = xwalk_project_node_resolved[
        xwalk_project_node_resolved["method"] == "unresolved_split_country"
    ]

    by_node = resolved.groupby("node_id")["capacity"].sum()
    node_to_country = node_master.set_index("node_id")["country_iso2"]
    by_country_via_node = by_node.rename(index=node_to_country).groupby(level=0).sum()
    by_country_direct = resolved.groupby("country_iso2")["capacity"].sum()

    aligned = by_country_via_node.reindex(by_country_direct.index)
    mismatches = by_country_direct[(aligned - by_country_direct).abs() > 1e-9]
    if not mismatches.empty:
        raise AssertionError(
            f"check_node_country_capacity_aggregation: node-summed capacity does not "
            f"reproduce country-summed capacity for {sorted(mismatches.index)}"
        )

    total_capacity = xwalk_project_node_resolved["capacity"].sum()
    skipped_capacity = skipped["capacity"].sum()
    return {
        "countries_proven": sorted(resolved["country_iso2"].unique().tolist()),
        "countries_skipped_split": sorted(skipped["country_iso2"].unique().tolist()),
        "total_capacity": float(total_capacity),
        "skipped_capacity": float(skipped_capacity),
        "skipped_capacity_share": float(skipped_capacity / total_capacity)
        if total_capacity
        else None,
    }
