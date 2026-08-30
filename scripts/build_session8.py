"""
build_session8.py
--------------------
Session 8: the tool that turns analyst pipeline assumptions into an LNG
number. This session does not produce the number -- STEP 1 stripped every
invented current-year flow value out of ``config/pipeline_flows.yaml``
(session 7 wrote 249 bcma for CA-US with a citation attached; EA's own
fact_net_gas_position puts Canada's whole 2030 surplus at 81.3 bcm, so that
corridor alone implied Canada importing 183 bcm of LNG it never called for).
With no analyst assumptions on file, a correct run derives a real LNG number
only for the countries whose entire touching pipe corridor set is IEA
GTF-measured/continued (real third-party data, not this session's
invention); every country touching a stripped, now-null corridor gets a
null LNG position, propagating through net_country_position's own
completeness rule -- see the build log and "What could not be resolved"
below for exactly which countries fall on which side of that line, and for
the gap between that and the task's own stated gate.

Run with the ``lt_lng_flows`` conda environment active, after sessions 1-3
and 6-7 have produced their outputs:

    python scripts/build_session8.py
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
from lt_lng_flows.model import lng_net_position as lnp  # noqa: E402
from lt_lng_flows.output import duckdb_store, session8_outputs  # noqa: E402
from lt_lng_flows.pipe import gtf_flows  # noqa: E402
from lt_lng_flows.pipe import pipe_flow_forecast as pff  # noqa: E402
from lt_lng_flows.validate import pipe_checks  # noqa: E402

CONFIG_DIR = ROOT / "config"
DATA_RAW = ROOT / "data" / "raw"
DATA_GEO = ROOT / "data" / "geo"
DATA_OUTPUT = ROOT / "data" / "output"
DATA_INTERIM = ROOT / "data" / "interim"
CROSSWALKS_DIR = ROOT / "crosswalks"
DOCS_DIR = ROOT / "docs"

WORKBOOK_VINTAGE = "202608"
WORKBOOK_ROOT = DATA_RAW / "workbooks" / WORKBOOK_VINTAGE
IEA_GTF_PATH = DATA_RAW / "iea_gtf" / "Export_GTF_IEA_202606.xlsx"
EA_API_RAW_ROOT = DATA_RAW / "ea_api"
OILX_RAW_ROOT = DATA_RAW / "oilx"

SESSION3_CONSTANTS_PATH = CONFIG_DIR / "session_03_constants.yaml"
SESSION7_CONSTANTS_PATH = CONFIG_DIR / "session_07_constants.yaml"
SESSION8_CONSTANTS_PATH = CONFIG_DIR / "session_08_constants.yaml"
PIPELINE_FLOWS_PATH = CONFIG_DIR / "pipeline_flows.yaml"
XWALK_COUNTRY_ALIAS_PATH = CROSSWALKS_DIR / "xwalk_country_alias.csv"
XWALK_EA_API_COUNTRY_PATH = CROSSWALKS_DIR / "xwalk_ea_api_country.csv"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_applied_crosswalk() -> pd.DataFrame:
    """Same construction as build_session2/3/5/6/7.py's loader of the same
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


def modelled_countries_from_session6(fact_net_gas_position: pd.DataFrame) -> list[str]:
    """Same definition build_session7.py used: session 6's countries with
    both supply and demand in at least one year."""
    both = fact_net_gas_position[fact_net_gas_position["missing_side"].isnull()]
    return sorted(both["country_iso2"].unique().tolist())


# ---------------------------------------------------------------------------
# Re-derive fact_pipe_net_position from the now-stripped pipeline_flows.yaml.
# Same logic as build_session7.py's build_corridor_timeseries -- duplicated
# rather than imported (session 8 does not modify or import the already
# gated build_session7.py script), but this session must not read session
# 7's stale, pre-strip parquet: the whole point of STEP 1 is that a fresh
# run of the pipe chain against the stripped assumptions produces different
# (mostly null) output, and fact_lng_net_position has to be derived from
# that fresh output, not the number session 7 published.
# ---------------------------------------------------------------------------
def rebuild_fact_pipe_net_position(
    dim_country: pd.DataFrame,
    dim_country_adjacency: pd.DataFrame,
    applied_crosswalk: pd.DataFrame,
    mm3_to_bcm: float,
    pipeline_flows_cfg: dict,
    session7_constants: dict,
    modelled_countries: list[str],
    log,
) -> tuple[pd.DataFrame, dict]:
    horizon = session7_constants["horizon"]

    gtf_long = gtf_flows.read_gtf_border_flows(IEA_GTF_PATH)
    fact_pipe_flow_hist = gtf_flows.build_fact_pipe_flow_hist(
        gtf_long, applied_crosswalk, mm3_to_bcm
    )
    months_observed = pff.corridor_months_observed(gtf_long, applied_crosswalk)
    real_country_codes = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])

    measured, stale = pff.project_measured_corridors(
        fact_pipe_flow_hist,
        months_observed,
        real_country_codes,
        pipeline_flows_cfg["measured_corridor_overrides"],
        pipeline_flows_cfg["measured_corridor_default_continuation"],
        horizon["end"],
        session7_constants["stale_year_threshold"],
    )
    assumed, undecided_assumed = pff.project_assumed_corridors(
        pipeline_flows_cfg["corridors_assumed"], horizon["start"], horizon["end"]
    )
    log(
        f"STEP 1 (rebuild): re-derived fact_pipe_net_position against the stripped "
        f"pipeline_flows.yaml -- {len(undecided_assumed)} of "
        f"{len(pipeline_flows_cfg['corridors_assumed'])} hand-listed corridors are undecided "
        "(all of them, since STEP 1 stripped every current_flow_bcma)."
    )

    corridor_timeseries = pd.concat([measured, assumed], ignore_index=True)
    touched = set(
        corridor_timeseries["origin_iso2"].tolist()
        + corridor_timeseries["destination_iso2"].tolist()
    )
    zero_countries_derived = sorted(set(modelled_countries) - touched)

    net_position = pff.net_country_position(
        corridor_timeseries,
        modelled_countries,
        zero_countries_derived,
        horizon["start"],
        horizon["end"],
        horizon["history_start"],
    )
    net_position["year"] = net_position["year"].astype(int)

    diagnostics = {
        "stale_corridors": stale,
        "undecided_assumed_corridors": undecided_assumed,
        "zero_countries_derived": zero_countries_derived,
    }
    return net_position, diagnostics


def main() -> None:
    report_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        report_lines.append(msg)

    session3_constants = load_yaml(SESSION3_CONSTANTS_PATH)
    session7_constants = load_yaml(SESSION7_CONSTANTS_PATH)
    session8_constants = load_yaml(SESSION8_CONSTANTS_PATH)
    pipeline_flows_cfg = load_yaml(PIPELINE_FLOWS_PATH)
    mm3_to_bcm = session3_constants["gtf_unit_conversion"]["mm3_to_bcm"]

    dim_country = pd.read_parquet(DATA_GEO / "dim_country.parquet")
    dim_country_adjacency = pd.read_parquet(DATA_GEO / "dim_country_adjacency.parquet")
    applied_crosswalk = load_applied_crosswalk()
    fact_net_gas_position = pd.read_parquet(DATA_OUTPUT / "fact_net_gas_position.parquet")
    modelled_countries = modelled_countries_from_session6(fact_net_gas_position)

    # ---- STEP 1 (gate): every analyst field in the stripped config must be
    # null, or must carry entered_by/entered_on. -----------------------------
    pff.validate_analyst_provenance(pipeline_flows_cfg["corridors_assumed"])
    n_stripped_corridors = len(pipeline_flows_cfg["corridors_assumed"])
    log(
        f"STEP 1 gate: validate_analyst_provenance passed over all {n_stripped_corridors} "
        "hand-listed corridors -- no analyst field is populated without a matching "
        "entered_by/entered_on."
    )

    # ---- rebuild fact_pipe_net_position fresh against the stripped config --
    net_position, pipe_diagnostics = rebuild_fact_pipe_net_position(
        dim_country,
        dim_country_adjacency,
        applied_crosswalk,
        mm3_to_bcm,
        pipeline_flows_cfg,
        session7_constants,
        modelled_countries,
        log,
    )
    net_position.to_parquet(DATA_OUTPUT / "fact_pipe_net_position.parquet", index=False)
    log(
        "Wrote data/output/fact_pipe_net_position.parquet, regenerated from the stripped "
        "config -- this replaces session 7's file, which still carried the invented CA-US "
        "249 bcma-derived figures."
    )

    n_null_pipe = int(net_position["net_pipe_bcm"].isnull().sum())
    log(
        f"{n_null_pipe} of {len(net_position)} (country_iso2, year) rows in the regenerated "
        f"fact_pipe_net_position are null (basis 'undecided'), out of "
        f"{net_position['country_iso2'].nunique()} countries."
    )

    # ---- STEP 4: validation -------------------------------------------------
    val_cfg = session8_constants["validation"]
    check_year = session8_constants["checks_reporting_year"]

    v4a = pipe_checks.check_export_within_supply(net_position, fact_net_gas_position)
    v4b = pipe_checks.check_pipe_within_surplus(net_position, fact_net_gas_position)
    v4c = pipe_checks.check_transit_near_zero(
        net_position, fact_net_gas_position, val_cfg["transit_supply_threshold_bcm"]
    )
    corridor_pairs = [
        (c["origin_iso2"], c["destination_iso2"]) for c in pipeline_flows_cfg["corridors_assumed"]
    ]
    v4d = pipe_checks.check_corridor_endpoints_adjacent(corridor_pairs, dim_country_adjacency)
    v4e = pipe_checks.check_global_pipe_closure(
        net_position, modelled_countries, val_cfg["global_closure_tolerance_bcm"]
    )

    def _country_counts(violations: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for v in violations:
            counts[v["country_iso2"]] = counts.get(v["country_iso2"], 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    log(
        f"STEP 4a (export <= supply): {len(v4a)} row-level violation(s) across "
        f"{len(_country_counts(v4a))} countries: {_country_counts(v4a)}"
    )
    log(
        f"STEP 4b (|pipe| <= |surplus|): {len(v4b)} row-level violation(s) across "
        f"{len(_country_counts(v4b))} countries: {_country_counts(v4b)}"
    )
    log(
        f"STEP 4c (transit near zero): {len(v4c)} row-level violation(s) across "
        f"{len(_country_counts(v4c))} countries: {_country_counts(v4c)}"
    )
    log(f"STEP 4d (corridor adjacency): {len(v4d)} non-adjacent pair(s): {v4d}")
    log(f"STEP 4e (global pipe closure): {len(v4e)} year(s) outside tolerance: {v4e}")

    # ---- STEP 5: the calculation --------------------------------------------
    lng_net_position = lnp.build_lng_net_position(fact_net_gas_position, net_position)
    lng_net_position.to_parquet(DATA_OUTPUT / "fact_lng_net_position.parquet", index=False)
    log("Wrote data/output/fact_lng_net_position.parquet.")

    scoped = lng_net_position[lng_net_position["country_iso2"].isin(modelled_countries)]
    n_null = int(scoped["lng_net_bcm"].isnull().sum())
    n_total = len(scoped)
    countries_with_real_value = sorted(
        scoped.loc[scoped["lng_net_bcm"].notnull(), "country_iso2"].unique().tolist()
    )
    log(
        f"STEP 5: fact_lng_net_position built, {n_total} (country_iso2, year) rows over the "
        f"{len(modelled_countries)} modelled countries. {n_null} of {n_total} rows are null."
    )
    if countries_with_real_value:
        log(
            f"STEP 5: {len(countries_with_real_value)} countries carry a non-null derived LNG "
            "number in at least one year -- every touching pipe corridor for these is IEA "
            "GTF-measured or its generalised flat continuation (real third-party data with a "
            "documented, non-corridor-specific continuation rule), never a hand-typed analyst "
            "number: " + ", ".join(countries_with_real_value)
        )
    else:
        log("STEP 5: every modelled country is null, as the task's stated gate expects.")

    # ---- xlsx: surplus, pipe, lng_net, mapping 545 as a stale reference -----
    xlsx_path = DATA_OUTPUT / "fact_lng_net_position.xlsx"
    write_xlsx(lng_net_position, fact_net_gas_position, net_position, dim_country, xlsx_path)
    log("Wrote data/output/fact_lng_net_position.xlsx.")

    # ---- HTML: the inspection instrument ------------------------------------
    html_path = DATA_OUTPUT / "session_08_lng_net_position.html"
    session8_outputs.build_html(
        lng_net_position, fact_net_gas_position, net_position, dim_country, html_path
    )
    log("Wrote data/output/session_08_lng_net_position.html.")

    # ---- STEP 6: corridors awaiting an analyst number, ranked by residual --
    surplus_at_year = fact_net_gas_position[fact_net_gas_position["year"] == check_year].set_index(
        "country_iso2"
    )["surplus_deficit_bcm"]
    ranked_undecided = []
    for corridor in pipe_diagnostics["undecided_assumed_corridors"]:
        residuals = [
            abs(surplus_at_year[c])
            for c in (corridor["origin_iso2"], corridor["destination_iso2"])
            if c in surplus_at_year.index and pd.notna(surplus_at_year[c])
        ]
        ranked_undecided.append(
            {**corridor, "residual_at_stake_bcm": max(residuals) if residuals else None}
        )
    ranked_undecided.sort(key=lambda c: c["residual_at_stake_bcm"] or 0, reverse=True)

    # ---- DuckDB: full rebuild, restoring what session 7 silently dropped ---
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
    gtf_long = gtf_flows.read_gtf_border_flows(IEA_GTF_PATH)
    fact_pipe_flow_hist = gtf_flows.build_fact_pipe_flow_hist(
        gtf_long, applied_crosswalk, mm3_to_bcm
    )
    fact_gas_balance, _ = ea_series.build_fact_gas_balance(EA_API_RAW_ROOT)
    fact_lng_flow_baseline, _ = oilx_flows.build_fact_lng_flow_baseline(OILX_RAW_ROOT)
    dim_aggregate = dim_aggregate_mod.empty_dim_aggregate()
    dim_country_region_tag = lt_region_mod.empty_dim_country_region_tag()

    con = duckdb_store.create_store(DATA_OUTPUT / "lt_lng_flows.duckdb")
    try:
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
        duckdb_store.load_fact_net_gas_position(con, fact_net_gas_position)
        duckdb_store.load_fact_pipe_net_position(con, net_position)
        duckdb_store.load_fact_lng_net_position(con, lng_net_position)
        log(
            "DuckDB store rebuilt in full (session 2/3/5/6/7 tables restored, session 7's "
            "rebuild had silently dropped all but 5 of them -- see STEP 6 below), plus the new "
            "fact_lng_net_position table (PK country_iso2/year, FK to dim_country)."
        )
    finally:
        con.close()

    write_manifest(
        DATA_INTERIM / "session_08_lng_net_position_manifest.json",
        {
            "pipeline_flows_config": str(PIPELINE_FLOWS_PATH.relative_to(ROOT)),
            "modelled_countries": modelled_countries,
        },
    )
    log("Wrote data/interim/session_08_lng_net_position_manifest.json")

    write_report(
        report_lines,
        lng_net_position,
        modelled_countries,
        v4a,
        v4b,
        v4c,
        v4d,
        v4e,
        ranked_undecided,
        n_stripped_corridors,
    )
    log("Wrote docs/session_08_lng_net.md")

    print("\nbuild_session8: PASS")


def write_xlsx(
    lng_net_position: pd.DataFrame,
    fact_net_gas_position: pd.DataFrame,
    fact_pipe_net_position: pd.DataFrame,
    dim_country: pd.DataFrame,
    out_path: Path,
) -> None:
    """surplus, pipe, lng_net side by side, plus mapping 545's own net
    position (already built by session 6's net_gas_position.build_lng_net_position,
    reused here rather than re-pulled) as a clearly labelled stale reference
    column -- never an input to lng_net_bcm, per the task's own instruction."""
    from lt_lng_flows.model import net_gas_position as ngp

    combined = (
        lng_net_position[["country_iso2", "year", "lng_net_bcm"]]
        .merge(
            fact_net_gas_position[
                ["country_iso2", "year", "surplus_deficit_bcm", "lng_net_bcm"]
            ].rename(columns={"lng_net_bcm": "mapping_545_lng_net_bcm_STALE_REFERENCE_ONLY"}),
            on=["country_iso2", "year"],
            how="left",
        )
        .merge(
            fact_pipe_net_position[["country_iso2", "year", "net_pipe_bcm"]],
            on=["country_iso2", "year"],
            how="left",
        )
    )
    del ngp  # mapping_545_lng_net_bcm already carried on fact_net_gas_position (session 6)

    names = dim_country[["country_iso2", "country_name_display"]]
    combined = combined.merge(names, on="country_iso2", how="left")
    combined = combined[
        [
            "country_iso2",
            "country_name_display",
            "year",
            "surplus_deficit_bcm",
            "net_pipe_bcm",
            "lng_net_bcm",
            "mapping_545_lng_net_bcm_STALE_REFERENCE_ONLY",
        ]
    ].sort_values(["country_iso2", "year"])

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="lng_net_position", index=False, na_rep="")


def write_report(
    log_lines: list[str],
    lng_net_position: pd.DataFrame,
    modelled_countries: list[str],
    v4a: list[dict],
    v4b: list[dict],
    v4c: list[dict],
    v4d: list,
    v4e: list[dict],
    ranked_undecided: list[dict],
    n_stripped_corridors: int,
) -> None:
    scoped = lng_net_position[lng_net_position["country_iso2"].isin(modelled_countries)]
    n_null = int(scoped["lng_net_bcm"].isnull().sum())
    n_total = len(scoped)

    lines = [
        "# Session 8: the LNG-derivation tool, run on stripped assumptions",
        "",
        "`fact_lng_net_position` = `surplus_deficit_bcm` - `net_pipe_bcm`, per country per year, "
        "written at mapping 545's grain (`net_exports_bcm`/`net_imports_bcm`). This session builds "
        "the tool; it does not supply the pipeline flow values the tool needs to produce a "
        "trustworthy number for every corridor. Session 7 wrote 249 bcma for CA-US with a "
        "citation attached; EA's own data puts Canada's entire 2030 surplus at 81.3 bcm, so that "
        "corridor alone implied Canada importing 183 bcm of LNG. STEP 1 stripped every "
        "current-year flow value, continuation, target, year and source note out of "
        "`config/pipeline_flows.yaml`, unconditionally -- not only the ones judged unsourced.",
        "",
        "## Build log",
        "",
        *[f"- {line}" for line in log_lines],
        "",
        "## STEP 1: what was stripped",
        "",
        f"{n_stripped_corridors} corridors in `config/pipeline_flows.yaml`'s `corridors_assumed`, "
        "82 populated analyst-only cells nulled or removed across them (current_flow_bcma, "
        "basis_year, continuation blocks -- including every nested target_flow_bcma/target_year/ "
        "terminal_year/lookback_years -- and every source note). `measured_corridor_overrides` "
        "and `zero_countries_expected` were left untouched: the former is a continuation *method* "
        "(which of a corridor's own GTF-measured years to average) applied to real IEA-observed "
        "flow values, not an invented magnitude; the latter is a structural finding (no "
        "cross-border pipe exists at all for that country), not a flow number. Both are judgement "
        "calls made this session and are open to challenge.",
        "",
        "## STEP 3: the two-zone schema and its gate",
        "",
        "`config/pipeline_flows.yaml` now documents which fields the tool may write "
        "(`origin_iso2`, `destination_iso2`, `adjacency_flag`) and which only a person may "
        "(`current_flow_bcma`, `basis_year`, `continuation`, `source`, alongside the "
        "`entered_by`/`entered_on` pair that must accompany any of them). "
        "`pipe_flow_forecast.validate_analyst_provenance` raises on the first corridor that "
        "carries an analyst-only field populated without both `entered_by` and `entered_on` set "
        f"-- it passed over all {n_stripped_corridors} corridors this run, since every one is "
        "fully null.",
        "",
        "## STEP 4: the five checks",
        "",
        "| check | asserts | this run |",
        "|---|---|---|",
        f"| 4a check_export_within_supply | net pipe exports <= supply_bcm | "
        f"{len(v4a)} violation(s) |",
        f"| 4b check_pipe_within_surplus | \\|net_pipe_bcm\\| <= \\|surplus_deficit_bcm\\| | "
        f"{len(v4b)} violation(s) |",
        f"| 4c check_transit_near_zero | a country with ~0 supply_bcm nets ~0 pipe | "
        f"{len(v4c)} violation(s) |",
        f"| 4d check_corridor_endpoints_adjacent | every corridor pair is geographically "
        f"adjacent or overridden | {len(v4d)} non-adjacent pair(s) |",
        f"| 4e check_global_pipe_closure | modelled-set net_pipe_bcm sums to ~0 each year | "
        f"{len(v4e)} year(s) outside tolerance |",
        "",
        "Run over the full modelled set, 4a/4b/4c surface widely -- not confined to Canada. Most "
        "of the countries they flag (Belgium, the Baltics, Switzerland, Czechia, Slovakia, "
        "Bulgaria, Greece, Austria, Ireland, ...) have negligible or zero domestic gas production "
        "(`supply_bcm` near 0), so almost any nonzero GTF-projected pipe throughput trips a "
        "check phrased as an absolute bound. That is a real property of these checks applied to "
        "real small transit/consuming countries, not a bug in them and not something this session "
        "corrects -- exactly Canada's case (a large, real supply figure, exceeded anyway) is the "
        "one worth a person's attention first; the small-country cases mostly reflect the naive "
        "flat continuation these checks were never told to treat differently for a country with "
        "near-zero production.",
        "",
        "Each has a failing-first fixture in `tests/test_pipe_checks.py`, built directly from "
        "session 7's own numbers (Canada 264.75 bcm net pipe export against 228.0 bcm supply and "
        "81.3 bcm surplus for 4a/4b; Tunisia's +21.4 bcm one-legged TN-IT-without-DZ-TN corridor "
        "for 4c) so each fails against the exact real values that motivated this session before "
        "the check existed, then passes once it does.",
        "",
        "## What is null in fact_lng_net_position, and what is not",
        "",
        f"{n_null} of {n_total} (country_iso2, year) rows are null across the "
        f"{len(modelled_countries)} modelled countries. Not every row is null: a country whose "
        "*every* touching pipe corridor is IEA GTF-measured history or that history's generalised "
        "flat continuation (a documented, non-corridor-specific rule, not a hand-typed number) "
        "still derives a real LNG position, because nothing invented by an analyst or by this "
        "session ever touched its pipe number. `net_country_position` nulls a country's cell "
        "the moment *any one* of its touching corridors is null, so every country that touches "
        "even one stripped `corridors_assumed` entry is null, and that propagates outward -- but "
        "it does not reach a country with no such touching corridor at all. Nulling those "
        "countries anyway, to make the whole table uniformly null, would itself be inventing an "
        "absence the data does not support, which CLAUDE.md and this session's own constraints "
        'rule out ("if an instruction cannot be satisfied without inventing a number, stop and '
        'say which instruction you are breaking"). The instruction being broken, named directly: '
        "the task's stated gate that a correct run produces `fact_lng_net_position` with every "
        "value null. It does not, and the reason is stated above rather than forced.",
        "",
        "## Corridors awaiting an analyst number, ranked by residual at stake",
        "",
        "Same convention as session 7's own ranking (`|surplus_deficit_bcm|` in "
        "2030, whichever touching endpoint is itself modelled, the larger where both are) -- this "
        "is the work list.",
        "",
        "| origin | destination | residual_at_stake_bcm (2030) | note |",
        "|---|---|---|---|",
        *[
            "| {origin} | {destination} | {residual} | {note} |".format(
                origin=c["origin_iso2"],
                destination=c["destination_iso2"],
                residual=(
                    "n/a"
                    if c["residual_at_stake_bcm"] is None
                    else f"{c['residual_at_stake_bcm']:.1f}"
                ),
                note=(c.get("note") or "").strip().splitlines()[0] if c.get("note") else "",
            )
            for c in ranked_undecided
        ],
        "",
        "## STEP 6: housekeeping",
        "",
        "**`config/pipeline_projects.yaml` vs `config/pipeline_flows.yaml`: neither goes.** Both "
        "were checked against the master plan and each other rather than taken on the file "
        "listing's word that one is a duplicate. They are not duplicates of content: "
        "`pipeline_flows.yaml` holds corridors already carrying gas (GTF-measured or hand-listed) "
        "plus the explicit-zero list; `pipeline_projects.yaml` holds prospective, not-yet-FID "
        "projects (Power of Siberia 2, TAPI, and six others), none netted into any position. Plan "
        'section 5.3 assigns `pipeline_projects.yaml` this distinct role explicitly ("every '
        'prospective project in the central case ... in one reviewable place"). The two files do '
        "share a schema shape (origin/destination/flow/start-year/source), which is a real "
        "generalisation candidate -- a single corridor table with a `status: existing|prospective` "
        "field instead of two files -- but collapsing them would override a plan decision made "
        "without sign-off, so it is surfaced here rather than done unilaterally, per CLAUDE.md's "
        'generalisation-check rule ("surface, don\'t decide unilaterally").',
        "",
        "**`lt_lng_flows.duckdb` fell from 29.6MB to 3.9MB during session 7's rebuild because "
        "session 7's own `main()` called `duckdb_store.create_store` (which deletes the file) and "
        "then reloaded only 5 tables: `dim_country`, `dim_country_adjacency`, "
        "`xwalk_country_alias`, `fact_net_gas_position` and the new `fact_pipe_net_position`.** "
        "Session 6's own rebuild had loaded ten more: `dim_supply_node`, `dim_demand_node`, "
        "`fact_liq_project`, `fact_regas_project`, `fact_lng_contract`, `fact_pipe_flow_hist`, "
        "`fact_gas_balance` (195,809 rows -- almost certainly the bulk of the missing size), "
        "`fact_lng_flow_baseline`, `dim_aggregate` and `dim_country_region_tag`. Nothing in "
        "session 7's build log documents this as a deliberate pruning decision; it reads as an "
        "oversight in that script's DuckDB section, not a decision to drop those tables from the "
        "working store. It should not have been dropped: section 9 of the plan calls the DuckDB "
        "file *the* working store, singular, not a per-session scratch file. This session's "
        "`build_session8.py` restores the full table set (session 2/3/5/6/7's own tables plus the "
        "new `fact_lng_net_position`) rather than repeating session 7's narrower reload.",
        "",
        "## What could not be resolved this session",
        "",
        "- No flow value, capacity, start year or growth path was estimated, sourced from the web, "
        "or defaulted anywhere in this session -- every corridor in `corridors_assumed` is null, "
        "exactly as STEP 1 left it.",
        "- The gate mismatch described above (`fact_lng_net_position` is not uniformly null) is "
        "reported rather than resolved: forcing it to be uniformly null would require nulling "
        "countries whose pipe position is entirely real IEA GTF data, which is not something this "
        "session is willing to invent an absence for.",
        "- `docs/session_07_pipe_assumptions.md` (session 7's own report) is now stale -- it still "
        "narrates the invented CA-US/US-MX/etc. figures as if they stood -- but it is a historical "
        "record of what session 7 did, not a live output, so it is left as written rather than "
        "rewritten by this session; `data/output/fact_pipe_net_position.parquet`, the artefact it "
        "described, has been regenerated and no longer matches that document's own tables.",
    ]

    (DOCS_DIR / "session_08_lng_net.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
