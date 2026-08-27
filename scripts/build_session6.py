"""
build_session6.py
--------------------
Session 6: the surplus/deficit table (EA supply minus EA demand, per country
per year, over the full span mappings 297 and 314 actually carry data),
finished and made visible. Session 5 built ``fact_net_gas_position`` for the
2025-2050 model horizon only; this session extends it to the full pinned
span, adds the known-split components beside it (net_pipe_bcm from the IEA
GTF file, lng_net_bcm from mapping 545), and renders it as an xlsx workbook
and a self-contained Plotly HTML page. No value here is interpreted,
attributed to pipe or LNG causally, or checked against outside knowledge --
the task is to produce the table and report what is in it.

Run with the ``lt_lng_flows`` conda environment active, after sessions 1-3
and 5 have produced ``data/geo/dim_country.parquet``, the pinned EA API
snapshots under ``data/raw/ea_api/`` and the IEA GTF export under
``data/raw/iea_gtf/``:

    python scripts/build_session6.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.geo import dim_aggregate as dim_aggregate_mod  # noqa: E402
from lt_lng_flows.geo import lt_region as lt_region_mod  # noqa: E402
from lt_lng_flows.ingest import ea_series, oilx_flows, workbook_facts  # noqa: E402
from lt_lng_flows.ingest.provenance import write_manifest  # noqa: E402
from lt_lng_flows.model import net_gas_position as ngp  # noqa: E402
from lt_lng_flows.output import duckdb_store, session6_outputs  # noqa: E402
from lt_lng_flows.pipe import gtf_flows, net_pipe_position  # noqa: E402
from lt_lng_flows.validate import session6_checks  # noqa: E402

CONFIG_DIR = ROOT / "config"
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_GEO = ROOT / "data" / "geo"
DATA_OUTPUT = ROOT / "data" / "output"
CROSSWALKS_DIR = ROOT / "crosswalks"
DOCS_DIR = ROOT / "docs"

WORKBOOK_VINTAGE = "202608"
WORKBOOK_ROOT = DATA_RAW / "workbooks" / WORKBOOK_VINTAGE
IEA_GTF_PATH = DATA_RAW / "iea_gtf" / "Export_GTF_IEA_202606.xlsx"
EA_API_RAW_ROOT = DATA_RAW / "ea_api"
OILX_RAW_ROOT = DATA_RAW / "oilx"

SESSION3_CONSTANTS_PATH = CONFIG_DIR / "session_03_constants.yaml"
SESSION6_CONSTANTS_PATH = CONFIG_DIR / "session_06_constants.yaml"
XWALK_COUNTRY_ALIAS_PATH = CROSSWALKS_DIR / "xwalk_country_alias.csv"
XWALK_EA_API_COUNTRY_PATH = CROSSWALKS_DIR / "xwalk_ea_api_country.csv"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_applied_crosswalk() -> pd.DataFrame:
    """Same construction as build_session2.py/3.py/5.py's loader of the same
    name; duplicated rather than imported so this session does not modify
    already-gated code."""
    alias = pd.read_csv(XWALK_COUNTRY_ALIAS_PATH, dtype=str, keep_default_na=False, na_values=[])
    alias = alias.rename(columns={"proposed_iso2": "country_iso2"})
    ea_api = pd.read_csv(XWALK_EA_API_COUNTRY_PATH, dtype=str, keep_default_na=False, na_values=[])
    return pd.concat(
        [
            alias[["source_system", "raw_value", "country_iso2", "confidence", "method", "note"]],
            ea_api[["source_system", "raw_value", "country_iso2", "confidence", "method", "note"]],
        ],
        ignore_index=True,
    )


# ---------------------------------------------------------------------------
# STEP 1 + STEP 2: fact_net_gas_position, full span, components beside it.
# ---------------------------------------------------------------------------


def step1_and_2_build_combined(
    fact_gas_balance: pd.DataFrame,
    dim_country: pd.DataFrame,
    gtf_long: pd.DataFrame,
    applied_crosswalk: pd.DataFrame,
    mm3_to_bcm: float,
    session6_constants: dict,
    log,
) -> pd.DataFrame:
    base = ngp.build_fact_net_gas_position(fact_gas_balance, dim_country)
    year_min, year_max = int(base["year"].min()), int(base["year"].max())
    n_countries = base["country_iso2"].nunique()
    both = int((base["missing_side"].isnull()).sum())
    log(
        f"STEP 1: fact_net_gas_position rebuilt over the full span mappings 297/314 actually "
        f"carry data: {year_min}-{year_max} (mapping 297 supply and/or mapping 314 total "
        f"natural_gas demand), {len(base)} (country_iso2, year) rows, {n_countries} countries. "
        f"{both} rows carry both supply and demand; the rest have missing_side set to 'supply', "
        "'demand' or 'both', never zero-filled."
    )

    pipe_cfg = session6_constants["net_pipe_position"]
    pipe = net_pipe_position.build_net_pipe_position(
        gtf_long,
        applied_crosswalk,
        mm3_to_bcm,
        dim_country,
        pipe_cfg["min_months_observed"],
        pipe_cfg["netherlands_iso2"],
        pipe_cfg["netherlands_excluded_from_year"],
    )
    n_pipe_countries = pipe["country_iso2"].nunique()
    n_pipe_excluded = int(pipe["net_pipe_bcm"].isnull().sum())
    log(
        f"STEP 2: net_pipe_bcm built from the raw IEA GTF monthly file, European coverage only "
        f"(dim_country.continent == 'Europe'): {n_pipe_countries} countries, "
        f"{pipe['year'].min()}-{pipe['year'].max()}. {n_pipe_excluded} of {len(pipe)} "
        f"country-year rows have net_pipe_bcm excluded (null) for fewer than "
        f"{pipe_cfg['min_months_observed']} months observed and/or the Netherlands from "
        f"{pipe_cfg['netherlands_excluded_from_year']} onward; months_observed is kept on every "
        "row regardless, so the incompleteness stays visible."
    )

    lng = ngp.build_lng_net_position(fact_gas_balance, dim_country)
    n_lng_countries = lng["country_iso2"].nunique()
    log(
        f"STEP 2: lng_net_bcm built from mapping 545 (net_exports minus net_imports), the North "
        f"West Europe aggregate row excluded: {n_lng_countries} countries, "
        f"{lng['year'].min()}-{lng['year'].max()}."
    )

    combined = base.merge(pipe, on=["country_iso2", "year"], how="left").merge(
        lng, on=["country_iso2", "year"], how="left"
    )
    combined = (
        combined[
            [
                "country_iso2",
                "year",
                "supply_bcm",
                "demand_bcm",
                "surplus_deficit_bcm",
                "missing_side",
                "net_pipe_bcm",
                "months_observed",
                "lng_net_bcm",
                "source",
            ]
        ]
        .sort_values(["country_iso2", "year"])
        .reset_index(drop=True)
    )
    return combined


# ---------------------------------------------------------------------------
# STEP 5: the units data check.
# ---------------------------------------------------------------------------


def step5_units_check(fact_gas_balance: pd.DataFrame, log) -> list[dict]:
    demand_non_bcm = session6_checks.find_non_bcm_datasets(
        fact_gas_balance, mapping_id=314, category="natural_gas", aspect_subtype="total"
    )
    supply_non_bcm = session6_checks.find_non_bcm_datasets(
        fact_gas_balance, mapping_id=297, category="natural_gas"
    )

    findings = []
    for label, frame, mapping_id in (
        ("demand (mapping 314, natural_gas, aspect_subtype=total)", demand_non_bcm, 314),
        ("supply (mapping 297, natural_gas)", supply_non_bcm, 297),
    ):
        if frame.empty:
            log(f"STEP 5: {label} -- no non-bcm datasets found. Every contributing row is bcm.")
            continue
        for row in frame.to_dict("records"):
            country_missing = pd.isna(row["country_iso2"])
            country = "(no country)" if country_missing else row["country_iso2"]
            log(
                f"STEP 5: {label} -- dataset {row['dataset_id']} is unit '{row['unit']}' "
                f"for country {country} ('{row['description']}')."
            )
            resolution = (
                "EXCLUDED from the demand/supply figure: country_iso2 is null on this dataset "
                "(it is a WORLD-level aggregate, '" + row["description"] + "', not a country at "
                "all -- the country_iso2.notnull() filter drops it on its own, and the unit=='bcm' "
                "filter in extract_demand/extract_supply drops it a second, independent way), so "
                "it was never a candidate to be converted or summed in."
                if country_missing
                else "NEEDS MANUAL REVIEW -- a real country carries a non-bcm dataset in this "
                "scope."
            )
            log(f"STEP 5: resolution -- {resolution}")
            findings.append({**row, "mapping_id": mapping_id, "resolution": resolution})

    return findings


def main() -> None:
    report_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        report_lines.append(msg)

    session3_constants = load_yaml(SESSION3_CONSTANTS_PATH)
    session6_constants = load_yaml(SESSION6_CONSTANTS_PATH)
    mm3_to_bcm = session3_constants["gtf_unit_conversion"]["mm3_to_bcm"]

    dim_country = pd.read_parquet(DATA_GEO / "dim_country.parquet")
    applied_crosswalk = load_applied_crosswalk()

    fact_gas_balance, ea_snapshots = ea_series.build_fact_gas_balance(EA_API_RAW_ROOT)
    gtf_long = gtf_flows.read_gtf_border_flows(IEA_GTF_PATH)

    # ---- STEP 1 + STEP 2 -------------------------------------------------
    combined = step1_and_2_build_combined(
        fact_gas_balance,
        dim_country,
        gtf_long,
        applied_crosswalk,
        mm3_to_bcm,
        session6_constants,
        log,
    )

    # ---- STEP 3: xlsx ------------------------------------------------------
    combined.to_parquet(DATA_OUTPUT / "fact_net_gas_position.parquet", index=False)
    xlsx_path = DATA_OUTPUT / "fact_net_gas_position.xlsx"
    session6_outputs.write_xlsx(combined, dim_country, xlsx_path)
    log(
        "Wrote data/output/fact_net_gas_position.parquet and "
        "data/output/fact_net_gas_position.xlsx (sheets: surplus_deficit, components)."
    )

    # ---- STEP 4: HTML --------------------------------------------------
    html_path = DATA_OUTPUT / "session_06_surplus_deficit.html"
    session6_outputs.build_html(combined, dim_country, html_path)
    log("Wrote data/output/session_06_surplus_deficit.html.")

    # ---- STEP 5 ----------------------------------------------------------
    units_findings = step5_units_check(fact_gas_balance, log)

    # ---- DuckDB: rebuild the whole store from each session's own outputs,
    # same pattern build_session5.py used on top of build_session3.py's. ----
    fact_liq_project = workbook_facts.resolve_country_columns(
        workbook_facts.read_fact_liq_project(
            WORKBOOK_ROOT / "202608_LNG_liquefaction_projects.xlsx"
        ),
        "workbook_liquefaction",
        applied_crosswalk,
        {"country_raw": "country_iso2"},
    )
    fact_regas_project = workbook_facts.resolve_country_columns(
        workbook_facts.read_fact_regas_project(WORKBOOK_ROOT / "202608_LNG_regas_projects.xlsx"),
        "workbook_regas",
        applied_crosswalk,
        {"country_raw": "country_iso2"},
    )
    fact_lng_contract = workbook_facts.resolve_country_columns(
        workbook_facts.read_fact_lng_contract(WORKBOOK_ROOT / "202608_LNG_contracts_database.xlsx"),
        "workbook_contracts",
        applied_crosswalk,
        {"exporter_raw": "exporter_iso2", "importer_raw": "importer_iso2"},
    )
    fact_pipe_flow_hist = gtf_flows.build_fact_pipe_flow_hist(
        gtf_long, applied_crosswalk, mm3_to_bcm
    )
    fact_lng_flow_baseline, oilx_snapshots = oilx_flows.build_fact_lng_flow_baseline(OILX_RAW_ROOT)
    dim_aggregate = dim_aggregate_mod.empty_dim_aggregate()
    dim_country_region_tag = lt_region_mod.empty_dim_country_region_tag()

    con = duckdb_store.create_store(DATA_OUTPUT / "lt_lng_flows.duckdb")
    try:
        dim_country_adjacency = pd.read_parquet(DATA_GEO / "dim_country_adjacency.parquet")
        dim_supply_node = pd.read_parquet(DATA_GEO / "dim_supply_node.parquet")
        dim_demand_node = pd.read_parquet(DATA_GEO / "dim_demand_node.parquet")
        duckdb_store.load_dim_country(con, dim_country)
        duckdb_store.load_dim_country_adjacency(con, dim_country_adjacency)
        duckdb_store.load_dim_supply_node(con, dim_supply_node)
        duckdb_store.load_dim_demand_node(con, dim_demand_node)
        duckdb_store.load_xwalk_country_alias(con, applied_crosswalk)
        duckdb_store.load_fact_liq_project(con, fact_liq_project)
        duckdb_store.load_fact_regas_project(con, fact_regas_project)
        duckdb_store.load_fact_lng_contract(con, fact_lng_contract)
        duckdb_store.load_fact_pipe_flow_hist(con, fact_pipe_flow_hist)
        duckdb_store.load_fact_gas_balance(con, fact_gas_balance)
        duckdb_store.load_fact_lng_flow_baseline(con, fact_lng_flow_baseline)
        duckdb_store.load_dim_aggregate(con, dim_aggregate)
        duckdb_store.load_dim_country_region_tag(con, dim_country_region_tag)
        duckdb_store.load_fact_net_gas_position(con, combined)
        log(
            "DuckDB store rebuilt: session 2/3/5 tables reloaded from their own outputs, plus "
            "the widened fact_net_gas_position table (PK country_iso2/year, FK to dim_country, "
            "full span, net_pipe_bcm/lng_net_bcm beside surplus_deficit_bcm)."
        )
    finally:
        con.close()

    write_manifest(
        DATA_INTERIM / "session_06_surplus_deficit_manifest.json",
        {
            "ea_series_snapshots_used": [str(p.relative_to(ROOT)) for p in ea_snapshots],
            "oilx_snapshots_used": [str(p.relative_to(ROOT)) for p in oilx_snapshots],
            "iea_gtf_path": str(IEA_GTF_PATH.relative_to(ROOT)),
            "span": {
                "year_min": int(combined["year"].min()),
                "year_max": int(combined["year"].max()),
            },
        },
    )
    log("Wrote data/interim/session_06_surplus_deficit_manifest.json")

    write_catchup_doc(report_lines, combined, dim_country, units_findings)
    log("Wrote docs/session_06_surplus_deficit.md")

    print("\nbuild_session6: PASS")


def write_catchup_doc(
    log_lines: list[str],
    combined: pd.DataFrame,
    dim_country: pd.DataFrame,
    units_findings: list[dict],
) -> None:
    year_min, year_max = int(combined["year"].min()), int(combined["year"].max())
    has_both = combined[combined["missing_side"].isnull()]
    countries_with_both = sorted(has_both["country_iso2"].unique())
    all_countries = sorted(combined["country_iso2"].unique())
    countries_without_both = sorted(set(all_countries) - set(countries_with_both))

    pivot_rows = combined["country_iso2"].nunique()
    pivot_cols = combined["year"].nunique()
    components_rows = len(combined)
    # country_iso2, country_name_display, year, plus the 7 value/flag columns
    components_cols = 10

    ktoe_rows = [f for f in units_findings if f["unit"] != "bcm"]

    lines = [
        "# Session 6: surplus and deficit table, EA supply minus EA demand",
        "",
        "`fact_net_gas_position` extended from session 5's 2025-2050 slice to the full span "
        "mappings 297 (supply) and 314 (total natural_gas demand) actually carry data, with "
        "`net_pipe_bcm` (IEA GTF, European coverage) and `lng_net_bcm` (mapping 545) placed "
        "beside it as separately-sourced columns -- never subtracted from it, never reconciled. "
        "No number here is interpreted, attributed to pipe or LNG causally, or checked against "
        "outside knowledge.",
        "",
        "## Build log",
        "",
        *[f"- {line}" for line in log_lines],
        "",
        "## Span",
        "",
        f"{year_min}-{year_max}, established from the pinned data itself (mapping 297's earliest "
        f"year and mapping 314's earliest year, whichever is earlier; likewise the latest).",
        "",
        "## Country coverage",
        "",
        f"{len(all_countries)} countries appear in the table at all (mapping 297 supply and/or "
        f"mapping 314 total natural_gas demand, at any year in the span). "
        f"{len(countries_with_both)} have at least one (country, year) row with both supply and "
        f"demand present. {len(countries_without_both)} never have both sides present in the "
        f"same year: {countries_without_both}",
        "",
        "## xlsx sheets",
        "",
        f"- `surplus_deficit`: {pivot_rows} rows (one per country) x {pivot_cols + 2} columns "
        f"(country_iso2, country_name_display, then one column per year {year_min}-{year_max}), "
        f"sorted by |surplus_deficit_bcm| in {year_max} descending, blank where there is no "
        "number.",
        f"- `components`: {components_rows} rows (one per country-year) x {components_cols} "
        "columns (country_iso2, country_name_display, year, supply_bcm, demand_bcm, "
        "surplus_deficit_bcm, net_pipe_bcm, lng_net_bcm, months_observed, missing_side).",
        "",
        "## Step 5: units check",
        "",
    ]

    if not ktoe_rows:
        lines.append(
            "No non-bcm dataset found in mapping 314's natural_gas total-demand scope or "
            "mapping 297's natural_gas supply scope."
        )
    else:
        for f in ktoe_rows:
            country = "(no country)" if pd.isna(f["country_iso2"]) else f["country_iso2"]
            lines.append(
                f"- mapping {f['mapping_id']}, dataset {f['dataset_id']}, unit '{f['unit']}', "
                f"country {country} ('{f['description']}'). {f['resolution']}"
            )
    lines += [
        "",
        "## What could not be resolved this session",
        "",
        "- No interpretation of the surplus/deficit table, or of its divergence from net_pipe_bcm "
        "or lng_net_bcm, was attempted -- out of scope for this session by the task's own "
        "instruction.",
        "- months_observed for the pipe component reflects the union of months observed across "
        "every corridor touching a country that year (as either origin or destination); it does "
        "not distinguish a country whose every corridor reports the same complete twelve months "
        "from one whose corridors report different, only-collectively-complete months. Reported "
        "as the definition used, not resolved further this session.",
    ]

    (DOCS_DIR / "session_06_surplus_deficit.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
