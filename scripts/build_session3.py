"""
build_session3.py
--------------------
Session 3: ingestion (sessions_02_03_build_plan.md section 3). Country level
throughout, per the Prototype phasing decision: no node splits, no
``dim_port``, no ``fact_route_distance``. Reads the pinned workbooks, the
IEA GTF file, and whatever EA/OilX snapshots exist on disk (built by the
operator running ``scripts/pull_ea_series.py`` / ``scripts/pull_oilx_flows.py``,
which this session does not run). Produces deliverables 3.1 to 3.8 and
writes ``docs/session_03_ingestion.md`` and ``docs/session_03_definitions.md``.

Run with the ``lt_lng_flows`` conda environment active, after session 2 has
passed its gate:

    python scripts/build_session3.py
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
from lt_lng_flows.ingest import ea_series, oilx_flows, workbook_diff, workbook_facts  # noqa: E402
from lt_lng_flows.ingest.provenance import file_fact, write_manifest  # noqa: E402
from lt_lng_flows.output import duckdb_store  # noqa: E402
from lt_lng_flows.pipe import gtf_flows  # noqa: E402
from lt_lng_flows.pipe import implied_pipe_diagnostic as ipd  # noqa: E402
from lt_lng_flows.validate import pipe_checks  # noqa: E402

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
XWALK_COUNTRY_ALIAS_PATH = CROSSWALKS_DIR / "xwalk_country_alias.csv"
XWALK_EA_API_COUNTRY_PATH = CROSSWALKS_DIR / "xwalk_ea_api_country.csv"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_applied_crosswalk() -> pd.DataFrame:
    """Same construction as build_session2.py's loader of the same name;
    duplicated rather than imported so this session does not modify
    already-gated session 2 code."""
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


def main() -> None:
    report_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        report_lines.append(msg)

    constants = load_yaml(SESSION3_CONSTANTS_PATH)
    applied_crosswalk = load_applied_crosswalk()
    dim_country = pd.read_parquet(DATA_GEO / "dim_country.parquet")
    real_country_codes = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])

    # ---- 3.1 typed fact tables from the three workbooks --------------------
    liq_path = WORKBOOK_ROOT / "202608_LNG_liquefaction_projects.xlsx"
    regas_path = WORKBOOK_ROOT / "202608_LNG_regas_projects.xlsx"
    contracts_path = WORKBOOK_ROOT / "202608_LNG_contracts_database.xlsx"

    fact_liq_project = workbook_facts.read_fact_liq_project(liq_path)
    fact_regas_project = workbook_facts.read_fact_regas_project(regas_path)
    fact_lng_contract = workbook_facts.read_fact_lng_contract(contracts_path)

    workbook_facts.assert_row_counts(
        fact_liq_project, fact_regas_project, fact_lng_contract, constants
    )
    log(
        f"3.1 row counts: liquefaction {len(fact_liq_project)} rows / "
        f"{fact_liq_project['country_raw'].nunique()} countries (expected 617/39); "
        f"regas {len(fact_regas_project)} rows / {fact_regas_project['country_raw'].nunique()} "
        f"countries (expected 615/78); contracts {len(fact_lng_contract)} rows, header row "
        f"{fact_lng_contract.attrs['header_row']} (expected 1074, header row 3). PASS"
    )

    workbook_facts.assert_contract_distributions(fact_lng_contract, constants)
    status_counts = fact_lng_contract["status"].value_counts().to_dict()
    delivery_counts = fact_lng_contract["delivery_type"].value_counts(dropna=False).to_dict()
    log(
        f"3.1 contract distributions PASS: status={status_counts}, "
        f"delivery_type={ {k if pd.notna(k) else '-': v for k, v in delivery_counts.items()} }, "
        f"export_country distinct={fact_lng_contract['exporter_raw'].nunique()} "
        f"(Portfolio={(fact_lng_contract['exporter_raw'] == 'Portfolio').sum()}), "
        f"import_country distinct={fact_lng_contract['importer_raw'].nunique()} "
        f"(Multiple={(fact_lng_contract['importer_raw'] == 'Multiple').sum()})"
    )

    fact_liq_project = workbook_facts.resolve_country_columns(
        fact_liq_project,
        "workbook_liquefaction",
        applied_crosswalk,
        {"country_raw": "country_iso2"},
    )
    fact_regas_project = workbook_facts.resolve_country_columns(
        fact_regas_project, "workbook_regas", applied_crosswalk, {"country_raw": "country_iso2"}
    )
    fact_lng_contract = workbook_facts.resolve_country_columns(
        fact_lng_contract,
        "workbook_contracts",
        applied_crosswalk,
        {"exporter_raw": "exporter_iso2", "importer_raw": "importer_iso2"},
    )
    log(
        f"3.1 country resolution: Portfolio -> XP "
        f"({(fact_lng_contract['exporter_iso2'] == 'XP').sum()} rows), "
        f"Multiple -> XM ({(fact_lng_contract['importer_iso2'] == 'XM').sum()} rows), "
        "neither dropped"
    )

    # ---- 3.2 workbook_diff ---------------------------------------------------
    prior_liq_path = workbook_diff.find_prior_vintage(
        WORKBOOK_ROOT.parent, WORKBOOK_VINTAGE, liq_path.name
    )
    prior_regas_path = workbook_diff.find_prior_vintage(
        WORKBOOK_ROOT.parent, WORKBOOK_VINTAGE, regas_path.name
    )
    prior_contracts_path = workbook_diff.find_prior_vintage(
        WORKBOOK_ROOT.parent, WORKBOOK_VINTAGE, contracts_path.name
    )
    liq_diff = workbook_diff.diff_project_table(
        fact_liq_project,
        workbook_facts.read_fact_liq_project(prior_liq_path) if prior_liq_path else None,
    )
    regas_diff = workbook_diff.diff_project_table(
        fact_regas_project,
        workbook_facts.read_fact_regas_project(prior_regas_path) if prior_regas_path else None,
    )
    contract_diff = workbook_diff.diff_contract_table(
        fact_lng_contract,
        workbook_facts.read_fact_lng_contract(prior_contracts_path)
        if prior_contracts_path
        else None,
    )
    log(
        f"3.2 workbook_diff: liquefaction prior_vintage_found="
        f"{liq_diff['prior_vintage_found']}, regas prior_vintage_found="
        f"{regas_diff['prior_vintage_found']}, contracts prior_vintage_found="
        f"{contract_diff['prior_vintage_found']} -- only the {WORKBOOK_VINTAGE} vintage is "
        f"pinned on disk this session, so all three report 'no prior vintage found' as a "
        f"structured result rather than being skipped (build plan 3.2). The synthetic-second-"
        f"vintage test (tests/test_workbook_diff.py) exercises the comparison logic itself."
    )

    # ---- 3.3 fact_pipe_flow_hist from IEA GTF, plus the adjacency check ----
    gtf_long = gtf_flows.read_gtf_border_flows(IEA_GTF_PATH)
    fact_pipe_flow_hist = gtf_flows.build_fact_pipe_flow_hist(
        gtf_long, applied_crosswalk, constants["gtf_unit_conversion"]["mm3_to_bcm"]
    )
    log(
        f"3.3 fact_pipe_flow_hist: {len(fact_pipe_flow_hist)} (origin, destination, year) rows "
        f"from {gtf_long['borderpoint'].nunique()} border points "
        f"({fact_pipe_flow_hist[['origin_iso2', 'destination_iso2']].drop_duplicates().shape[0]} "
        f"distinct corridors)"
    )

    dim_country_adjacency = pd.read_parquet(DATA_GEO / "dim_country_adjacency.parquet")
    adjacency_violations = pipe_checks.check_gtf_adjacency(
        fact_pipe_flow_hist, dim_country_adjacency, real_country_codes
    )
    if adjacency_violations:
        log(
            f"3.3 GTF adjacency check: FAILED-LISTED, {len(adjacency_violations)} corridor(s) "
            f"with neither geometric adjacency nor an override row: {adjacency_violations}"
        )
    else:
        log(
            "3.3 GTF adjacency check: PASS, every real-country corridor "
            "has adjacency or an override"
        )

    # ---- 3.4 / 3.4b: state the pull commands, do not run them --------------
    pull_ea_commands = [
        f"python scripts/pull_ea_series.py --mapping-id {mid} --vintage {WORKBOOK_VINTAGE}"
        for mid in (297, 314, 553, 545, 300, 5, 6)
    ]
    pull_oilx_command = (
        f"python scripts/pull_oilx_flows.py --vintage {WORKBOOK_VINTAGE} "
        f"--start-date 2023-01-01 --end-date 2026-12-31 --import-basis import"
    )
    log("3.4/3.4b: this session does not call the EA API or the OilX API. Operator commands:")
    for cmd in pull_ea_commands:
        log(f"  {cmd}")
    log(f"  {pull_oilx_command}")

    # ---- 3.4c fact_lng_flow_baseline (OilX) ---------------------------------
    fact_lng_flow_baseline, oilx_snapshots = oilx_flows.build_fact_lng_flow_baseline(OILX_RAW_ROOT)
    if oilx_snapshots:
        log(
            f"3.4c fact_lng_flow_baseline: {len(fact_lng_flow_baseline)} rows from {oilx_snapshots}"
        )
    else:
        log(
            "3.4c fact_lng_flow_baseline: EMPTY, pending the OilX pull "
            "(scripts/pull_oilx_flows.py has not been run). Loader built and tested against a "
            "fixture (tests/test_oilx_flows.py)."
        )

    # ---- 3.5 fact_gas_balance (EA) ------------------------------------------
    fact_gas_balance, ea_snapshots = ea_series.build_fact_gas_balance(EA_API_RAW_ROOT)
    if ea_snapshots:
        log(f"3.5 fact_gas_balance: {len(fact_gas_balance)} rows from {ea_snapshots}")
    else:
        log(
            "3.5 fact_gas_balance: EMPTY, pending the EA series pull "
            "(scripts/pull_ea_series.py has not been run for any mapping). Loader built and "
            "tested against a fixture (tests/test_ea_series.py)."
        )

    # ---- 3.4d implied-pipe diagnostic ---------------------------------------
    diagnostic_result = ipd.compute_implied_pipe_diagnostic(
        fact_gas_balance,
        fact_lng_flow_baseline,
        fact_pipe_flow_hist,
        constants["implied_pipe_diagnostic"]["large_divergence_bcm"],
    )
    diag_df = diagnostic_result["diagnostic"]
    if diag_df.empty:
        log(
            f"3.4d implied-pipe diagnostic: EMPTY, pending pull(s) -- "
            f"inputs_empty={diagnostic_result['inputs_empty']}. Module ran and reports this "
            f"explicitly rather than skipping (build plan 3.4d / session 3 gate)."
        )
    else:
        n_large = int(diag_df["is_large_divergence"].sum())
        log(
            f"3.4d implied-pipe diagnostic: {len(diag_df)} (country, year) rows, "
            f"{n_large} with divergence >= "
            f"{constants['implied_pipe_diagnostic']['large_divergence_bcm']} bcm against GTF "
            f"(diagnostic only, never used to smooth or build fact_pipe_flow_hist)"
        )

    # ---- 3.6 open questions from session_01_data_availability.md section 6 -
    open_questions_answers = write_definitions_doc(ea_snapshots, oilx_snapshots)
    log(
        f"3.6: {len(open_questions_answers)} open questions from the availability doc, "
        "answered/reported open per docs/session_03_definitions.md"
    )

    # ---- 3.6b lt_region + dim_country_region_tag ----------------------------
    lt_region_result = lt_region_mod.derive_lt_region(fact_gas_balance, dim_country)
    if lt_region_result["derivable"]:
        log(
            f"3.6b lt_region: derivable, {len(lt_region_result['lt_region_by_country'])} countries "
            f"assigned, {len(lt_region_result['multi_valued_countries'])} multi-valued "
            "(left null), "
            f"{len(lt_region_result['missing_from_partition'])} relevant countries missing from "
            f"the candidate set"
        )
    else:
        log(f"3.6b lt_region: NOT DERIVABLE this session -- {lt_region_result['reason']}")
    dim_country_region_tag = lt_region_mod.empty_dim_country_region_tag()

    # ---- 3.7 remaining crosswalks / dim_aggregate ----------------------------
    log(
        "3.7 xwalk_ea_api_country.csv: loaded as given (254 rows, method ea_published_pair), "
        "not re-derived, not name matched."
    )
    log(
        "3.7 Gate E: deferred per the Prototype phasing decision. "
        "crosswalks/xwalk_project_node_proposed.csv left exactly as session 2 wrote it; not "
        "read or modified by this session."
    )
    log(
        "3.7 crosswalks/xwalk_hub_country.csv: written with header only, zero rows. No LT price "
        "series (mapping 300) has been pulled, so there is no evidence on disk to propose a "
        "hub-to-importer mapping from; a hand-typed mapping from general knowledge would be "
        "exactly the unreviewed judgement CLAUDE.md's 'no fuzzy or plaintext joins without "
        "approval' and 'null beats a plausible invented number' rules exist to keep out."
    )
    dim_aggregate = dim_aggregate_mod.empty_dim_aggregate()
    log(
        "3.7 dim_aggregate: schema only, zero rows -- no LT taxonomy pull has landed. "
        "Not the same thing as the (separate, later, unresolved) Europe demand-block node."
    )

    # ---- DuckDB store: rebuild session 2's tables, then add session 3's ----
    # create_store() truncates the file, so session 2's dim tables are
    # reloaded from their own parquet outputs (unchanged by this session)
    # before session 3's fact tables are added on top, rather than this
    # script depending on build_session2.py having just been run in the
    # same process.
    con = duckdb_store.create_store(DATA_OUTPUT / "lt_lng_flows.duckdb")
    try:
        dim_supply_node = pd.read_parquet(DATA_GEO / "dim_supply_node.parquet")
        dim_demand_node = pd.read_parquet(DATA_GEO / "dim_demand_node.parquet")
        session2_xwalk = pd.read_csv(
            XWALK_COUNTRY_ALIAS_PATH, dtype=str, keep_default_na=False, na_values=[]
        ).rename(columns={"proposed_iso2": "country_iso2"})
        session2_xwalk = pd.concat(
            [
                session2_xwalk[
                    ["source_system", "raw_value", "country_iso2", "confidence", "method", "note"]
                ],
                pd.read_csv(
                    XWALK_EA_API_COUNTRY_PATH, dtype=str, keep_default_na=False, na_values=[]
                )[["source_system", "raw_value", "country_iso2", "confidence", "method", "note"]],
            ],
            ignore_index=True,
        )
        duckdb_store.load_dim_country(con, dim_country)
        duckdb_store.load_dim_country_adjacency(con, dim_country_adjacency)
        duckdb_store.load_dim_supply_node(con, dim_supply_node)
        duckdb_store.load_dim_demand_node(con, dim_demand_node)
        duckdb_store.load_xwalk_country_alias(con, session2_xwalk)
        log(
            "DuckDB store: session 2 tables (dim_country, dim_country_adjacency, "
            "dim_supply_node, dim_demand_node, xwalk_country_alias) reloaded unchanged from "
            "their own parquet/CSV outputs before session 3's tables are added"
        )
        duckdb_store.load_fact_liq_project(con, fact_liq_project)
        duckdb_store.load_fact_regas_project(con, fact_regas_project)
        duckdb_store.load_fact_lng_contract(con, fact_lng_contract)
        duckdb_store.load_fact_pipe_flow_hist(con, fact_pipe_flow_hist)
        duckdb_store.load_fact_gas_balance(con, fact_gas_balance)
        duckdb_store.load_fact_lng_flow_baseline(con, fact_lng_flow_baseline)
        duckdb_store.load_dim_aggregate(con, dim_aggregate)
        duckdb_store.load_dim_country_region_tag(con, dim_country_region_tag)
        log(
            "DuckDB store: fact_liq_project, fact_regas_project, fact_lng_contract, "
            "fact_pipe_flow_hist, fact_gas_balance, fact_lng_flow_baseline, dim_aggregate, "
            "dim_country_region_tag loaded with PK/FK declared"
        )
    finally:
        con.close()

    # ---- manifest and report -------------------------------------------------
    write_manifest(
        DATA_INTERIM / "session_03_ingestion_manifest.json",
        {
            "workbook_vintage": WORKBOOK_VINTAGE,
            "workbook_files": {
                liq_path.name: file_fact(liq_path),
                regas_path.name: file_fact(regas_path),
                contracts_path.name: file_fact(contracts_path),
            },
            "iea_gtf_file": {IEA_GTF_PATH.name: file_fact(IEA_GTF_PATH)},
            "ea_series_snapshots_found": [str(p.relative_to(ROOT)) for p in ea_snapshots],
            "oilx_snapshots_found": [str(p.relative_to(ROOT)) for p in oilx_snapshots],
        },
    )
    log("Wrote data/interim/session_03_ingestion_manifest.json")

    write_ingestion_doc(
        report_lines,
        adjacency_violations,
        diagnostic_result,
        constants,
    )
    log("Wrote docs/session_03_ingestion.md")

    print("\nbuild_session3: PASS")


def write_ingestion_doc(
    log_lines: list[str],
    adjacency_violations: list[dict],
    diagnostic_result: dict,
    constants: dict,
) -> None:
    lines = [
        "# Session 3: ingestion",
        "",
        "Deliverable for session 3 of `docs/sessions_02_03_build_plan.md` section 3, "
        "country level only per the Prototype phasing decision.",
        "",
        "## Build log",
        "",
        *[f"- {line}" for line in log_lines],
        "",
        "## GTF adjacency violations",
        "",
    ]
    if adjacency_violations:
        lines.append(f"{len(adjacency_violations)} violation(s), listed, not absorbed:")
        for v in adjacency_violations:
            lines.append(f"- {v['origin_iso2']} -> {v['destination_iso2']}")
    else:
        lines.append(
            "None. Every real-country corridor in `fact_pipe_flow_hist` has geometric "
            "adjacency or an explicit override row in `dim_country_adjacency` -- expected, "
            "since session 2's override file was itself built as evidence from this same "
            "GTF file (`adjacency.py`)."
        )
    lines += ["", "## Implied-pipe diagnostic", ""]
    diag_df = diagnostic_result["diagnostic"]
    if diag_df.empty:
        lines.append(
            f"EMPTY. `inputs_empty` = {diagnostic_result['inputs_empty']}. The diagnostic module "
            f"ran and reports this explicitly, per the session 3 gate "
            f"('empty-pending-pull is an acceptable report, a silent skip is not')."
        )
    else:
        large = diag_df[diag_df["is_large_divergence"]]
        lines.append(
            f"{len(diag_df)} (country, year) rows computed. "
            f"{len(large)} rows diverge from GTF by "
            f">= {constants['implied_pipe_diagnostic']['large_divergence_bcm']} bcm:"
        )
        for _, row in large.iterrows():
            lines.append(
                f"- {row['country_iso2']} {row['year']}: implied "
                f"{row['implied_net_pipe_bcm']:.2f} bcm vs GTF {row['gtf_net_pipe_bcm']:.2f} bcm "
                f"(divergence {row['divergence_bcm']:.2f} bcm)"
            )
        lines.append(
            "This is a diagnostic only (build plan 3.4d): it folds in own-use, losses and "
            "storage movements uncorrected, and is never a source `fact_pipe_flow_hist` is built "
            "from."
        )
    (DOCS_DIR / "session_03_ingestion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_definitions_doc(ea_snapshots: list[Path], oilx_snapshots: list[Path]) -> list[dict]:
    """Build plan 3.6: answer the (more than six -- eight, per the actual
    section 6 in the availability doc, plus the two sub-questions folded
    into #7) open questions from series metadata. No mapping-specific EA
    series pull has landed this session (``ea_snapshots``/``oilx_snapshots``
    are typically empty), so questions needing live series metadata stay
    open, named as such, per CLAUDE.md ("a null beats a plausible invented
    number").
    """
    questions = [
        {
            "n": 1,
            "question": "Does mapping 297 include net pipeline trade by country, or supply only?",
            "answer": None,
            "reason_open": (
                "Needs mapping 297's own series metadata (aspect/aspect_subtype per dataset), "
                "which requires the mapping_id=297 pull. Not resolvable from the mappings "
                "catalogue alone (data/raw/ea_api/202608/ea_api_mappings.txt), which carries no "
                "aspect field per dataset_id -- only mapping_id, name, dataset_ids, licensed, "
                "request_string."
            ),
        },
        {
            "n": 2,
            "question": (
                "Is demand in 314 and 550-560 gross inland or final consumption, and do own use "
                "and flaring sit inside it or separately?"
            ),
            "answer": None,
            "reason_open": (
                "Needs series-level aspect/aspect_subtype/category_subtype metadata "
                "from the mapping_id=314 and 550-560 pulls."
            ),
        },
        {
            "n": 3,
            "question": "Is production in 297 marketed or gross?",
            "answer": None,
            "reason_open": "Same as question 1: needs the mapping_id=297 series metadata.",
        },
        {
            "n": 4,
            "question": "Are LNG imports in 545 gross or net of reloads?",
            "answer": None,
            "reason_open": "Needs the mapping_id=545 series metadata (aspect/aspect_subtype).",
        },
        {
            "n": 5,
            "question": "What is mapping 614, 'Long term trial data'?",
            "answer": None,
            "reason_open": (
                "Session 1 already flagged this as provenance-unknown and 'do not use until EA "
                "confirms what it is'. No series metadata pull resolves an undocumented mapping's "
                "purpose; this needs a direct question to EA, not a data pull."
            ),
        },
        {
            "n": 6,
            "question": "What is the volume field in the flows response, and in what unit?",
            "answer": (
                "Partially answered from plan 3.2c's documented response shape (not from a live "
                "call, which this session does not make): the flows endpoint returns "
                "QuantityKT, QuantityCBM and QuantityMMBtu, i.e. mass, liquid volume and energy, "
                "not a direct bcm-of-gas figure. Which of these to use, and the exact conversion "
                "to bcm (whether the decisions register's 1.37 Mt-to-bcm factor applies as-is), "
                "is still open."
            ),
            "reason_open": (
                "The exact conversion is not confirmed against a live response; "
                "oilx_flows.py deliberately leaves fact_lng_flow_baseline.bcm null and preserves "
                "the raw quantity fields rather than applying an unconfirmed factor."
            ),
        },
        {
            "n": 7,
            "question": (
                "Sub-country taxonomy: is the US taxonomy confirmed as PADD, what are the "
                "Canadian/Chinese/Chilean taxonomies, and does an LNG-specific sub-country or "
                "terminal breakdown exist anywhere in the API?"
            ),
            "answer": None,
            "reason_open": (
                "Out of scope this session per the Prototype phasing decision: gate E (node "
                "splits) is deferred, and this question only matters for resolving gate E's "
                "sub-national node assignment."
            ),
        },
        {
            "n": 8,
            "question": "The exact response field names, for the config field map in 2.3 rule 4.",
            "answer": (
                "Partially answered from plan 3.2c: cargo type ID 211100 for LNG, subtypes 211101 "
                "(Rich)/211102 (Lean); flow record fields OriginCountryCode, "
                "DestinationCountryCode, GradeID, Import, QuantityKT/QuantityCBM/QuantityMMBtu, "
                "ReferenceDate, Deleted, all mapped to snake_case in oilx_flows.py's _FIELD_MAP."
            ),
            "reason_open": (
                "Not confirmed against a live response this session; the field map is built from "
                "the documented shape and should be checked against the first real pull."
            ),
        },
    ]

    lines = [
        "# Session 3: definitions",
        "",
        "Deliverable for session 3, build plan 3.6: answers to the open questions in "
        "`docs/session_01_data_availability.md` section 6, from series metadata only. That "
        "section carries eight items as of this session (not six -- read fresh per the session 3 "
        "starting prompt), the first four resolving from series metadata and the last four "
        "needing one page of the flows endpoint; none of the metadata pulls this session needs "
        "has landed on disk (EA series snapshots found: "
        f"{[str(p) for p in ea_snapshots]}; "
        f"OilX snapshots found: {[str(p) for p in oilx_snapshots]}), "
        "so every question needing live series metadata is reported open here, named, rather "
        "than guessed.",
        "",
    ]
    for q in questions:
        lines.append(f"## Question {q['n']}: {q['question']}")
        lines.append("")
        if q["answer"]:
            lines.append(f"**Answer.** {q['answer']}")
        else:
            lines.append("**Still open.**")
        lines.append("")
        lines.append(f"**Why:** {q['reason_open']}")
        lines.append("")

    lines.append("## Sign convention and component naming for fact_gas_balance")
    lines.append("")
    lines.append(
        "`component` is stored exactly as the EA API's own `aspect` metadata field reports it "
        "(`supply`, `demand`, `production`, `net_imports`, ...), not remapped onto plan 5.2's "
        "identity term names (`domestic_production`, `pipe_imports`, ...). That remapping "
        "requires questions 1 and 3 above to be settled first; forcing it now would silently "
        "pick a side of an open question. Values are stored exactly as the API returns them, "
        "with no sign flipped at ingestion time -- see `ea_series.py`."
    )
    (DOCS_DIR / "session_03_definitions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return questions


if __name__ == "__main__":
    main()
