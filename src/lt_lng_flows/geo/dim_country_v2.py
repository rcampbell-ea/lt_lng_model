"""
dim_country_v2.py
--------------------
Session 2, build plan 4.3. Builds the full ``dim_country`` that replaces
session 1's interim version: ISO3, name slug, continent/subregion and
centroid from the geometry (``natural_earth.py``), ``is_landlocked`` from the
geometry, ``role_lng``/``role_pipe`` derived from where a country appears in
the pinned workbooks and the IEA GTF file, and the lineage columns from the
2.1 pull manifest. ``lt_region`` is created and left null: it depends on the
LT demand series, not pulled this session (sessions_02_03_build_plan.md 2.3).
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

PLAN_4_3_COLUMNS = [
    "country_iso2",
    "country_iso3",
    "country_name_display",
    "country_name_slug",
    "is_real_country",
    "continent",
    "un_subregion",
    "lt_region",
    "is_landlocked",
    "role_lng",
    "role_pipe",
    "centroid_lat",
    "centroid_lon",
    "geo_source",
    "geo_snapshot_date",
    "geo_snapshot_sha256",
]


def slugify(name: str) -> str:
    """ASCII lower snake case per CLAUDE.md identifiers rule."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_name).strip("_").lower()
    return slug


def resolve_workbook_countries(
    raw_country_strings: pd.DataFrame,
    applied_crosswalk: pd.DataFrame,
    source_system: str,
    column_name: str,
) -> set[str]:
    """The set of country_iso2 values appearing under one (source_system,
    column_name) in the raw country strings, resolved through the applied
    alias crosswalk. Every raw value here is expected to already resolve
    (checked at 4.8 check 2); a value that does not resolve raises rather
    than being silently skipped from role derivation.
    """
    raw_values = raw_country_strings.loc[
        (raw_country_strings["source_system"] == source_system)
        & (raw_country_strings["column_name"] == column_name),
        "raw_value",
    ].unique()

    xwalk = applied_crosswalk[applied_crosswalk["source_system"] == source_system].set_index(
        "raw_value"
    )["country_iso2"]

    codes = set()
    unresolved = []
    for raw in raw_values:
        if raw not in xwalk.index:
            unresolved.append(raw)
            continue
        codes.add(xwalk.loc[raw])
    if unresolved:
        raise ValueError(
            f"resolve_workbook_countries: {source_system}.{column_name} has raw values "
            f"with no entry in the applied crosswalk: {sorted(unresolved)}"
        )
    return codes


def derive_role_lng(
    raw_country_strings: pd.DataFrame, applied_crosswalk: pd.DataFrame
) -> pd.DataFrame:
    """importer, exporter, both, or none (build plan 4.3), from whether the
    country appears in the liquefaction workbook (exporter axis) or the
    regas workbook (importer axis), per sessions_02_03_build_plan.md 2.3.
    The contracts workbook is not consulted: the spec names only the
    liquefaction and regas workbooks as the role_lng source.
    """
    exporters = resolve_workbook_countries(
        raw_country_strings, applied_crosswalk, "workbook_liquefaction", "Country"
    )
    importers = resolve_workbook_countries(
        raw_country_strings, applied_crosswalk, "workbook_regas", "Country"
    )
    all_codes = sorted(exporters | importers)
    rows = []
    for code in all_codes:
        is_exp, is_imp = code in exporters, code in importers
        role = "both" if is_exp and is_imp else "exporter" if is_exp else "importer"
        rows.append({"country_iso2": code, "role_lng": role})
    return pd.DataFrame(rows, columns=["country_iso2", "role_lng"])


def derive_role_pipe(
    raw_country_strings: pd.DataFrame, applied_crosswalk: pd.DataFrame
) -> pd.DataFrame:
    """importer, exporter, transit, both, or none (build plan 4.3), from
    whether the country appears as an Exit or Entry party in the IEA GTF
    file.

    Scoped decision, reported in docs/session_02_geo_master.md rather than
    silently picked: the GTF file gives only per-border-point Exit/Entry
    country pairs, with no flow-direction or volume-netting data pulled this
    session, so there is no test available yet to tell a transit country
    (gas passes through) apart from a country that is simply both an
    importer and an exporter at different border points. A country seen as
    both Exit and Entry is classified 'both' here; 'transit' is not assigned
    by this session's derivation and is left for session 3 once actual flow
    values are available to test net throughput.
    """
    exits_ = resolve_workbook_countries(raw_country_strings, applied_crosswalk, "iea_gtf", "Exit")
    entries = resolve_workbook_countries(raw_country_strings, applied_crosswalk, "iea_gtf", "Entry")
    all_codes = sorted(exits_ | entries)
    rows = []
    for code in all_codes:
        is_exit, is_entry = code in exits_, code in entries
        role = "both" if is_exit and is_entry else "exporter" if is_exit else "importer"
        rows.append({"country_iso2": code, "role_pipe": role})
    return pd.DataFrame(rows, columns=["country_iso2", "role_pipe"])


def build_dim_country(
    iso_dim_country: pd.DataFrame,
    dissolved_geometry: pd.DataFrame,
    centroids: pd.DataFrame,
    is_landlocked: pd.DataFrame,
    role_lng: pd.DataFrame,
    role_pipe: pd.DataFrame,
    geo_lineage: dict,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Assemble the full plan 4.3 dim_country. ``iso_dim_country`` is session
    1's minimal table (country_iso2, country_name, region, is_real_country),
    read for its country list and pseudo codes; every column it does not
    carry is filled from the geometry-derived inputs for real countries and
    left null for pseudo codes, which have no geometry.

    Returns (dim_country, countries_missing_geometry, countries_missing_geometry_relevant).
    The second element is
    the real countries with no LNG/pipe role that the 1:50m admin0 layer
    does not carve out as a separate polygon, for the session report.
    """
    base = iso_dim_country[["country_iso2", "country_name", "is_real_country"]].copy()
    base = base.rename(columns={"country_name": "country_name_display"})
    base["country_name_slug"] = base["country_name_display"].map(slugify)

    geo = dissolved_geometry[
        ["country_iso2", "country_iso3_ne", "continent", "un_subregion"]
    ].rename(columns={"country_iso3_ne": "country_iso3"})
    out = base.merge(geo, on="country_iso2", how="left")
    out = out.merge(centroids, on="country_iso2", how="left")
    out = out.merge(is_landlocked, on="country_iso2", how="left")
    out = out.merge(role_lng, on="country_iso2", how="left")
    out = out.merge(role_pipe, on="country_iso2", how="left")

    out["role_lng"] = out["role_lng"].fillna("none")
    out["role_pipe"] = out["role_pipe"].fillna("none")
    real_mask = out["is_real_country"]
    missing_geometry = out.loc[real_mask & out["continent"].isnull(), "country_iso2"].tolist()
    missing_relevant = out.loc[
        out["country_iso2"].isin(missing_geometry)
        & ((out["role_lng"] != "none") | (out["role_pipe"] != "none")),
        "country_iso2",
    ].tolist()
    # Neither tier raises here: a country missing geometry at 1:50m is a
    # named, reported gap either way (see docs/session_02_geo_master.md).
    # The relevant tier (a country the model actually uses, e.g. Gibraltar
    # as a regas importer, absent from the 1:50m admin0 layer) is a real
    # blocker on 4.8 check 4 and is escalated there, as gate C, rather than
    # silently patched with a hand-entered polygon (which would be exactly
    # the kind of un-reviewed geocoding CLAUDE.md and the session 2 "do not"
    # list forbid) or a third, un-authorised network pull beyond the two
    # build plan 2.1/2.1b permits.

    out["lt_region"] = None
    out["geo_source"] = geo_lineage["geo_source"]
    out["geo_snapshot_date"] = geo_lineage["geo_snapshot_date"]
    out["geo_snapshot_sha256"] = geo_lineage["geo_snapshot_sha256"]
    # Pseudo codes, and real countries with no geometry match at 1:50m,
    # carry no geometry lineage.
    no_geometry_mask = ~real_mask | out["country_iso2"].isin(missing_geometry)
    out.loc[no_geometry_mask, ["geo_source", "geo_snapshot_date", "geo_snapshot_sha256"]] = None
    out.loc[no_geometry_mask, "is_landlocked"] = None

    landlocked_role_violation = out[
        real_mask
        & (out["is_landlocked"] == True)  # noqa: E712
        & out["role_lng"].isin(["exporter", "importer", "both"])
    ]
    if not landlocked_role_violation.empty:
        raise AssertionError(
            "build_dim_country: landlocked country appears as an LNG exporter or "
            f"importer: {sorted(landlocked_role_violation['country_iso2'])}"
        )

    result = out[PLAN_4_3_COLUMNS].sort_values("country_iso2").reset_index(drop=True)
    return result, sorted(missing_geometry), sorted(missing_relevant)
