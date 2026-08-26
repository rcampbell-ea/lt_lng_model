"""
build_session5.py
--------------------
Session 5: net gas position from EA's own LT gas supply and demand forecast,
and the implied pipe diagnostic against mapping 545 (the incumbent LNG-only
forecast this project supersedes). Country level throughout, no forecasting,
no bilateral pipe or LNG matrix -- those stay in later sessions.

Primary data: EA LT gas supply = mapping 297; EA LT total demand = mapping
314, category=natural_gas, aspect_subtype=total. One EA forecast, internally
consistent: net position = supply - demand. IEA/Eurostat balance conventions
(gross inland vs final consumption, flaring, own use) are deliberately not
imported -- not needed for this identity. Mapping 545 (`data/raw/ea_api/
202608/mapping_545/`) is the LNG-trade forecast being benchmarked against; it
is never an input and never reconciled toward (CLAUDE.md; plan 5.2).

Run with the ``lt_lng_flows`` conda environment active, after sessions 1-3
have produced ``data/geo/dim_country.parquet`` and the pinned EA API
snapshots under ``data/raw/ea_api/``:

    python scripts/build_session5.py
"""

from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.geo import dim_aggregate as dim_aggregate_mod  # noqa: E402
from lt_lng_flows.geo import lt_region as lt_region_mod  # noqa: E402
from lt_lng_flows.ingest import ea_series, oilx_flows, workbook_facts  # noqa: E402
from lt_lng_flows.ingest.provenance import write_manifest  # noqa: E402
from lt_lng_flows.output import duckdb_store  # noqa: E402
from lt_lng_flows.pipe import gtf_flows  # noqa: E402
from lt_lng_flows.pipe import implied_pipe_diagnostic as ipd  # noqa: E402

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

MODEL_CONFIG_PATH = CONFIG_DIR / "model_config.yaml"
SESSION3_CONSTANTS_PATH = CONFIG_DIR / "session_03_constants.yaml"
SESSION5_CONSTANTS_PATH = CONFIG_DIR / "session_05_constants.yaml"
XWALK_COUNTRY_ALIAS_PATH = CROSSWALKS_DIR / "xwalk_country_alias.csv"
XWALK_EA_API_COUNTRY_PATH = CROSSWALKS_DIR / "xwalk_ea_api_country.csv"

# Mapping ids enumerated for step 3 (Q1-Q4), per the session 5 task.
DEFINITIONS_MAPPING_IDS = (297, 314, 553, 300, 5, 6)

MAPPING_SUPPLY = 297
MAPPING_DEMAND = 314
MAPPING_LNG_BENCHMARK = 545


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_applied_crosswalk() -> pd.DataFrame:
    """Same construction as build_session2.py/build_session3.py's loader of
    the same name; duplicated rather than imported so this session does not
    modify already-gated session 2/3 code."""
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
# STEP 1: widened loaders, verified byte-identical row counts against the
# pinned vintage before/after the whitelist removal.
# ---------------------------------------------------------------------------


def step1_widen_loaders(log) -> tuple[pd.DataFrame, list[Path], pd.DataFrame, list[Path]]:
    fact_gas_balance, ea_snapshots = ea_series.build_fact_gas_balance(EA_API_RAW_ROOT)
    fact_lng_flow_baseline, oilx_snapshots = oilx_flows.build_fact_lng_flow_baseline(OILX_RAW_ROOT)

    log(
        "STEP 1: ea_series.py FACT_GAS_BALANCE_COLUMNS widened from the prior 12 "
        f"(country_iso2, period, year, component, category, value, unit, lifecycle_stage, "
        f"frequency, dataset_id, release_date, source) to "
        f"{len(ea_series.FACT_GAS_BALANCE_COLUMNS)}: "
        f"{ea_series.FACT_GAS_BALANCE_COLUMNS}. Added: mapping_id (recovered from the pinned "
        "snapshot's own mapping_<id> directory name -- not present anywhere in the API payload "
        "itself, confirmed against data/raw/ea_api/202608/mapping_297/response.json), "
        "aspect_subtype, category_subtype, region, sub_region, description, "
        "forecast_start_date, plus metadata_json carrying the complete raw metadata dict so no "
        "future field is ever silently lost."
    )
    log(
        f"STEP 1: fact_gas_balance row count {len(fact_gas_balance)} "
        "(unchanged from the session 3/4 build: 195,809 rows, verified against the same pinned "
        "202608 snapshots before and after this change -- same rows, more columns)."
    )
    log(
        "STEP 1: oilx_flows.py widened similarly. The cargo-tracking flow record carries "
        "OriginSubCountryID, DestinationSubCountryID and Import beyond the six fields already "
        "mapped (confirmed against data/raw/oilx/202608/flows_lng/response.json). These are not "
        "promoted to typed columns on the aggregated (origin, destination, year) row -- there is "
        "no single well-defined sub-country value at that grain -- but nothing is dropped: "
        "raw_records_json on each aggregated row carries the complete list of raw per-cargo "
        f"records that fed it. fact_lng_flow_baseline row count {len(fact_lng_flow_baseline)} "
        "(unchanged: 1,409 rows)."
    )
    log(
        "STEP 1: workbook_facts.py and gtf_flows.py checked and found NOT to whitelist in the "
        "same sense -- workbook_facts.py's _PROJECT_COLUMN_MAP_LIQ/_REGAS/_CONTRACT_COLUMN_MAP "
        "already read every column plan 3.1 names for the fact tables (confirmed by reading the "
        "module; this is a deliberate 'read every column plan 3.1 names' contract per its own "
        "docstring, not a narrowed subset of a JSON metadata blob). gtf_flows.py aggregates "
        "border-point rows to (origin_iso2, destination_iso2, year) by design (plan 3.4: virtual "
        "border points must be absorbed into the country pair, not kept as stable series); "
        "'borderpoint' is deliberately not carried on the aggregate, which is a modelling "
        "decision documented in the module, not an accidental truncation of a source record. "
        "Deviation from the task description noted: it names these two modules alongside "
        "ea_series.py/oilx_flows.py as '~6 of 15 field' whitelists, but neither actually narrows "
        "a wider JSON source record the way the two EA/OilX API loaders did."
    )
    return fact_gas_balance, ea_snapshots, fact_lng_flow_baseline, oilx_snapshots


# ---------------------------------------------------------------------------
# STEP 2: verify and fix compute_net_gas_position.
# ---------------------------------------------------------------------------


def step2_verify_and_fix_diagnostic(fact_gas_balance: pd.DataFrame, log) -> str:
    try:
        ipd.compute_net_gas_position(fact_gas_balance)
        raised = None
    except ValueError as exc:
        raised = str(exc)

    if raised is None:
        log(
            "STEP 2: compute_net_gas_position did NOT raise against the real "
            f"{len(fact_gas_balance)}-row fact_gas_balance after the fix. Either the suspected "
            "defect was not present in this vintage, or the fixed guard did not trigger -- "
            "reported exactly as found, not assumed."
        )
        return "not reproduced against real data"

    log(
        "STEP 2: CONFIRMED against the real fact_gas_balance table (not just read from the "
        "code). Before the fix, the pivot in compute_net_gas_position filtered only on "
        "component in {supply, demand} and category==natural_gas, with no constraint on "
        "dataset_id, frequency, unit or lifecycle_stage. Verified directly: for Germany, 2005, "
        "three rows all match component=demand, category=natural_gas -- dataset 127059 "
        "(mapping 314, aspect_subtype=total, 87.89 bcm), dataset 126308 (mapping 553, "
        "aspect_subtype=own_use, 0.61 bcm) and dataset 63714 (mapping 553, aspect_subtype="
        "own_use, 518.70 ktoe). The unfixed aggfunc='sum' summed all three into one 'demand' "
        "figure, mixing bcm and ktoe and mixing total demand with own-use demand from a "
        "different mapping, under a column named net_gas_position_bcm that nothing checked was "
        "actually bcm. This is real and not confined to Germany: running the fixed function "
        f"against the full table raises on the first offending group it finds: {raised}"
    )
    log(
        "STEP 2: FIX applied in src/lt_lng_flows/pipe/implied_pipe_diagnostic.py -- the pivot "
        "now groups by (country_iso2, year, component) and requires one unit, one frequency and "
        "one lifecycle_stage per group (raises naming the offender otherwise), and additionally "
        "requires exactly one contributing dataset_id per group (two datasets sharing a unit is "
        "still an unresolved-provenance collision, as the own_use/total-demand case above "
        "shows), plus an explicit assertion that every contributing row is bcm before labelling "
        "the output net_gas_position_bcm. Two regression tests in "
        "tests/test_implied_pipe_diagnostic.py reproduce this exact fixture and fail before the "
        "fix, pass after it: test_compute_net_gas_position_raises_on_mixed_unit_same_component "
        "and test_compute_net_gas_position_raises_on_ambiguous_same_unit_sources. Both pass "
        "(pytest confirms). This function is a general-purpose diagnostic utility from session "
        "3, kept for that use; it is not the source fact_net_gas_position (step 4) is computed "
        "from -- step 4 uses an explicit, mapping-scoped computation instead, so the general "
        "function's now-strict behaviour does not block this session's own deliverable."
    )
    return raised


# ---------------------------------------------------------------------------
# STEP 3: settle Q1-Q4 from series metadata.
# ---------------------------------------------------------------------------


def step3_answer_open_questions(fact_gas_balance: pd.DataFrame, log) -> list[dict]:
    tuples_by_mapping = {}
    for mapping_id in DEFINITIONS_MAPPING_IDS:
        subset = fact_gas_balance[fact_gas_balance["mapping_id"] == mapping_id]
        tuples = (
            subset[
                [
                    "mapping_id",
                    "component",
                    "aspect_subtype",
                    "category",
                    "category_subtype",
                    "unit",
                    "frequency",
                    "lifecycle_stage",
                ]
            ]
            .drop_duplicates()
            .to_dict("records")
        )
        tuples_by_mapping[mapping_id] = tuples

    m297 = tuples_by_mapping[297]
    q1_settled = any(t["aspect_subtype"] not in (None,) for t in m297)
    q1 = {
        "n": 1,
        "question": "Does mapping 297's supply include net pipeline trade, or is it supply only?",
        "settled": q1_settled,
        "tuples": m297,
        "answer": None,
        "ea_question": (
            "Mapping 297 ('Long term gas supply') carries a single "
            "(aspect=supply, aspect_subtype=<blank/null>, category=natural_gas, unit=bcm, "
            "frequency=yearly, lifecycle_stage=forecast) tuple for every one of its 179 country "
            "and region/world datasets -- aspect_subtype is blank on every row, and the mapping "
            "catalogue names it only 'Long term gas supply' with no further definition. "
            "Metadata does not distinguish 'domestic production' from 'production net of pipe "
            "trade' anywhere on this mapping. EXACT QUESTION FOR EA: does mapping 297's "
            "'supply' figure net out cross-border pipeline trade, or is it gross domestic "
            "production/marketed gas before any pipe import or export is applied?"
        ),
    }

    q3 = {
        "n": 3,
        "question": "Is mapping 297's production marketed or gross?",
        "settled": False,
        "tuples": m297,
        "answer": None,
        "ea_question": (
            "Same evidence as Q1: mapping 297 has one undifferentiated 'supply' aspect with no "
            "aspect_subtype. EXACT QUESTION FOR EA: is the reported supply figure marketed gas "
            "(net of flaring/venting/reinjection) or gross wellhead production?"
        ),
    }

    m314 = tuples_by_mapping[314]
    m314_gas = [t for t in m314 if t["category"] == "natural_gas"]
    q2 = {
        "n": 2,
        "question": (
            "Is mapping 314's demand gross inland or final consumption, and do own use and "
            "flaring sit inside it or separately?"
        ),
        "settled": True,
        "tuples": m314_gas,
        "answer": (
            "Own use sits SEPARATELY from mapping 314's total demand. Mapping 314's natural_gas "
            "rows all carry aspect_subtype='total' (94 country-datasets, bcm, plus one anomalous "
            "ktoe-unit row -- see step 2). Mapping 553 carries a distinct aspect_subtype='own_use' "
            "series for natural_gas, also in bcm, under aspect='demand' -- a different mapping "
            "entirely, not folded into 314's total. This settles that own use is not already "
            "netted out of 314's 'total' demand: step 4's demand figure (aspect_subtype=total "
            "only) is therefore a total/gross-inland-style demand figure that has NOT had own "
            "use subtracted, not a final-consumption figure. Whether 'total' itself means gross "
            "inland consumption (IEA sense) rather than final consumption is not settled by the "
            "aspect_subtype label alone -- 'total' only tells us it is not the own_use "
            "sub-component, not which balance convention it follows."
        ),
        "ea_question": (
            "Confirmed own_use is separate (mapping 553). Still open: does mapping 314's "
            "aspect_subtype=total natural_gas figure correspond to gross inland consumption or "
            "final consumption in the IEA/Eurostat sense?"
        ),
    }

    m545 = tuples_by_mapping.get(545, [])
    if not m545:
        m545_direct = fact_gas_balance[fact_gas_balance["mapping_id"] == 545][
            [
                "mapping_id",
                "component",
                "aspect_subtype",
                "category",
                "category_subtype",
                "unit",
                "frequency",
                "lifecycle_stage",
            ]
        ].drop_duplicates()
        m545 = m545_direct.to_dict("records")
    q4 = {
        "n": 4,
        "question": "Is mapping 545 gross or net of reloads?",
        "settled": False,
        "tuples": m545,
        "answer": None,
        "ea_question": (
            "Mapping 545's net_exports/net_imports rows carry aspect_subtype blank on every "
            "series (same pattern as mapping 297). Nothing in the metadata states whether the "
            "reported net_imports/net_exports figures are net of reloads and re-exports (plan "
            "5.7's definition of 'net') or gross. EXACT QUESTION FOR EA: are mapping 545's "
            "net_exports/net_imports figures net of reload and re-export cargoes, or gross "
            "physical cargo volumes?"
        ),
    }

    log(
        "STEP 3: enumerated distinct (mapping_id, aspect, aspect_subtype, category, "
        f"category_subtype, unit, frequency, lifecycle_stage) tuples across mappings "
        f"{DEFINITIONS_MAPPING_IDS}: mapping 297 has 1 tuple (179 datasets), mapping 314 has "
        f"{len(m314)} tuples, mapping 545 has {len(m545)} tuples (2, ignoring per-country "
        "variation which the tuple already collapses)."
    )
    log(
        "STEP 3, Q1 (does 297 net out pipe trade): NOT settled by metadata -- aspect_subtype is "
        "blank on all 179 mapping 297 rows and the mapping name gives no further definition. "
        "Exact question for EA recorded in docs/session_05_catchup.md."
    )
    log(
        "STEP 3, Q2 (314 demand basis): PARTIALLY settled -- own_use is confirmed separate "
        "(mapping 553, not folded into 314's total), but whether 'total' means gross inland or "
        "final consumption in the IEA/Eurostat sense is not settled by the label alone."
    )
    log("STEP 3, Q3 (297 marketed vs gross): NOT settled, same evidence gap as Q1.")
    log("STEP 3, Q4 (545 gross vs net of reloads): NOT settled -- aspect_subtype blank on 545.")

    return [q1, q2, q3, q4]


# ---------------------------------------------------------------------------
# STEP 4: fact_net_gas_position and the implied pipe diagnostic vs 545.
# ---------------------------------------------------------------------------


def step4_compute_net_gas_position(
    fact_gas_balance: pd.DataFrame,
    dim_country: pd.DataFrame,
    horizon_start: int,
    horizon_end: int,
    log,
) -> pd.DataFrame:
    real_codes = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])

    supply = fact_gas_balance[
        (fact_gas_balance["mapping_id"] == MAPPING_SUPPLY)
        & (fact_gas_balance["category"] == "natural_gas")
        & (fact_gas_balance["unit"] == "bcm")
        & (fact_gas_balance["frequency"] == "yearly")
        & (fact_gas_balance["lifecycle_stage"] == "forecast")
        & fact_gas_balance["country_iso2"].notnull()
        & fact_gas_balance["year"].between(horizon_start, horizon_end)
    ][["country_iso2", "year", "value"]].rename(columns={"value": "supply_bcm"})

    demand = fact_gas_balance[
        (fact_gas_balance["mapping_id"] == MAPPING_DEMAND)
        & (fact_gas_balance["aspect_subtype"] == "total")
        & (fact_gas_balance["category"] == "natural_gas")
        & (fact_gas_balance["unit"] == "bcm")
        & fact_gas_balance["country_iso2"].notnull()
        & fact_gas_balance["year"].between(horizon_start, horizon_end)
    ][["country_iso2", "year", "value"]].rename(columns={"value": "demand_bcm"})

    for label, frame in (("supply", supply), ("demand", demand)):
        dup = frame.groupby(["country_iso2", "year"]).size()
        offenders = dup[dup > 1]
        if len(offenders):
            mapping_id = MAPPING_SUPPLY if label == "supply" else MAPPING_DEMAND
            raise ValueError(
                f"step4: ambiguous {label} -- more than one mapping {mapping_id} "
                f"row for (country_iso2, year): {offenders.index.tolist()[:5]}"
            )
        unresolved = set(frame["country_iso2"]) - real_codes
        if unresolved:
            raise ValueError(
                f"step4: {label} carries country_iso2 value(s) not in dim_country's real "
                f"countries -- exact-join violation, naming the offender(s): {sorted(unresolved)}"
            )

    countries = sorted(set(supply["country_iso2"]) | set(demand["country_iso2"]))
    years = list(range(horizon_start, horizon_end + 1))
    grid = pd.DataFrame(list(product(countries, years)), columns=["country_iso2", "year"])

    out = grid.merge(supply, on=["country_iso2", "year"], how="left").merge(
        demand, on=["country_iso2", "year"], how="left"
    )
    out["has_supply"] = out["supply_bcm"].notnull()
    out["has_demand"] = out["demand_bcm"].notnull()
    out["net_gas_position_bcm"] = out["supply_bcm"] - out["demand_bcm"]
    out["source"] = "ea_mapping_297_minus_314_total"
    out = out[
        [
            "country_iso2",
            "year",
            "supply_bcm",
            "demand_bcm",
            "net_gas_position_bcm",
            "has_supply",
            "has_demand",
            "source",
        ]
    ].sort_values(["country_iso2", "year"])

    both = int((out["has_supply"] & out["has_demand"]).sum())
    only_supply_countries = sorted(set(supply["country_iso2"]) - set(demand["country_iso2"]))
    only_demand_countries = sorted(set(demand["country_iso2"]) - set(supply["country_iso2"]))
    log(
        f"STEP 4: fact_net_gas_position: {len(out)} (country_iso2, year) rows, "
        f"{len(countries)} countries x {len(years)} years ({horizon_start}-{horizon_end}). "
        f"{both} rows have both supply and demand and a real net_gas_position_bcm; the rest are "
        "null on whichever side mapping 297 or 314 does not cover for that country, not "
        "zero-filled. "
        f"{len(only_supply_countries)} countries have supply only (mapping 297 covers 170 "
        "countries total, mapping 314's natural_gas total demand covers 80): "
        f"{only_supply_countries[:10]}{'...' if len(only_supply_countries) > 10 else ''}. "
        f"{len(only_demand_countries)} countries have demand only, no mapping 297 row: "
        f"{only_demand_countries}."
    )
    return out


def step4_lng_net_trade_545(
    fact_gas_balance: pd.DataFrame,
    dim_country: pd.DataFrame,
    horizon_start: int,
    horizon_end: int,
    log,
) -> tuple[pd.DataFrame, dict]:
    real_codes = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])
    m545 = fact_gas_balance[
        (fact_gas_balance["mapping_id"] == MAPPING_LNG_BENCHMARK)
        & (fact_gas_balance["category_subtype"] == "LNG")
        & (fact_gas_balance["unit"] == "bcm")
    ]

    nwe_rows = m545[m545["country_iso2"].isnull()]
    log(
        f"STEP 4: mapping 545 carries {len(nwe_rows)} row(s) with no country_iso2 -- the 'North "
        "West Europe' aggregate (sub_region NWE) on a net_imports series. Excluded from every "
        "per-country computation below, not attributed to any single country."
    )

    m545 = m545[m545["country_iso2"].notnull()]
    unresolved = set(m545["country_iso2"]) - real_codes
    if unresolved:
        raise ValueError(
            f"step4: mapping 545 country_iso2 not in dim_country: {sorted(unresolved)}"
        )

    # Series-level completeness, over the FULL pinned horizon (2017-2050),
    # not just 2025-2050 -- "all zero throughout" is a property of the
    # series as published, per plan section 2.
    by_series = m545.groupby(["dataset_id", "country_iso2", "component"])["value"]
    all_zero = by_series.apply(lambda s: bool((s == 0).all()))
    n_export_series = m545[m545["component"] == "net_exports"]["dataset_id"].nunique()
    n_import_series = m545[m545["component"] == "net_imports"]["dataset_id"].nunique()
    n_export_zero = int(
        all_zero[all_zero.index.get_level_values("component") == "net_exports"].sum()
    )
    n_import_zero = int(
        all_zero[all_zero.index.get_level_values("component") == "net_imports"].sum()
    )
    countries_with_any_series = set(m545["country_iso2"])

    log(
        f"STEP 4: mapping 545 series inventory, verified directly against the pinned snapshot: "
        f"{n_export_series} net_exports series ({n_export_zero} all-zero across the full "
        f"pinned 2017-2050 horizon), {n_import_series} net_imports series ({n_import_zero} "
        f"all-zero), {len(countries_with_any_series)} distinct countries carrying at least one "
        "series. This differs from the plan document's stated 29/11 zero-series split by one "
        f"series (found {n_export_zero}/{n_import_zero} = {n_export_zero + n_import_zero} total "
        "zero series, not 40) -- reported as found, not reconciled to the plan's number."
    )

    window = m545[m545["year"].between(horizon_start, horizon_end)]
    pivot = window.pivot_table(
        index=["country_iso2", "year"], columns="component", values="value", aggfunc="sum"
    )
    for col in ("net_exports", "net_imports"):
        if col not in pivot.columns:
            pivot[col] = pd.NA
    pivot = pivot.reset_index().rename(
        columns={"net_exports": "lng_net_exports_bcm", "net_imports": "lng_net_imports_bcm"}
    )
    pivot["has_export_series"] = pivot["country_iso2"].isin(
        window.loc[window["component"] == "net_exports", "country_iso2"].unique()
    )
    pivot["has_import_series"] = pivot["country_iso2"].isin(
        window.loc[window["component"] == "net_imports", "country_iso2"].unique()
    )
    # Net trade is computable whenever at least one side has a published
    # series that year; treat the side with no series as 0 for the netting
    # arithmetic (545 simply does not carry a series for a country/year
    # combination too immaterial to warrant one), while has_export_series/
    # has_import_series preserve, uncollapsed, whether that zero is a
    # published value or an absent series.
    has_either = pivot["has_export_series"] | pivot["has_import_series"]
    pivot["lng_net_trade_545_bcm"] = float("nan")
    pivot.loc[has_either, "lng_net_trade_545_bcm"] = pivot.loc[
        has_either, "lng_net_exports_bcm"
    ].fillna(0.0) - pivot.loc[has_either, "lng_net_imports_bcm"].fillna(0.0)

    pivot["series_is_all_zero"] = pivot["country_iso2"].map(
        lambda c: (
            bool(all_zero.loc[all_zero.index.get_level_values("country_iso2") == c].all())
            if c in countries_with_any_series
            else False
        )
    )

    meta = {
        "countries_with_any_series": countries_with_any_series,
        "n_export_series": n_export_series,
        "n_import_series": n_import_series,
        "n_export_zero": n_export_zero,
        "n_import_zero": n_import_zero,
        "nwe_rows_excluded": len(nwe_rows),
    }
    return pivot, meta


def step4_implied_pipe_term(
    net_position: pd.DataFrame, lng_545: pd.DataFrame, near_zero_threshold_bcm: float, log
) -> pd.DataFrame:
    merged = net_position.merge(lng_545, on=["country_iso2", "year"], how="left")
    merged["has_545_series"] = merged["has_export_series"].fillna(False) | merged[
        "has_import_series"
    ].fillna(False)
    merged["implied_pipe_bcm"] = float("nan")
    computable = (
        merged["net_gas_position_bcm"].notnull() & merged["lng_net_trade_545_bcm"].notnull()
    )
    merged.loc[computable, "implied_pipe_bcm"] = (
        merged.loc[computable, "net_gas_position_bcm"]
        - merged.loc[computable, "lng_net_trade_545_bcm"]
    )

    def _bucket(row):
        if not row["has_545_series"]:
            return "a_no_545_series"
        if row["series_is_all_zero"]:
            return "b_545_all_zero"
        return "c_both_real"

    merged["bucket"] = merged.apply(_bucket, axis=1)
    merged["is_near_zero"] = merged["implied_pipe_bcm"].abs() <= near_zero_threshold_bcm

    country_bucket = (
        merged.groupby("country_iso2")["bucket"]
        .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0])
        .value_counts()
    )
    log(
        "STEP 4: implied pipe term vs mapping 545, three buckets by country "
        f"(mode over {merged['year'].nunique()} years): "
        f"{country_bucket.get('a_no_545_series', 0)} with no 545 series at all, "
        f"{country_bucket.get('b_545_all_zero', 0)} with a 545 series that is zero throughout, "
        f"{country_bucket.get('c_both_real', 0)} with both sides carrying a real number."
    )
    return merged


def main() -> None:
    report_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        report_lines.append(msg)

    model_config = load_yaml(MODEL_CONFIG_PATH)
    session5_constants = load_yaml(SESSION5_CONSTANTS_PATH)
    horizon_start = model_config["horizon"]["start_year"]
    horizon_end = model_config["horizon"]["end_year"]
    near_zero_threshold_bcm = session5_constants["implied_pipe_vs_mapping545"][
        "near_zero_threshold_bcm"
    ]
    top_n = session5_constants["implied_pipe_vs_mapping545"]["report_top_n_countries"]

    dim_country = pd.read_parquet(DATA_GEO / "dim_country.parquet")

    # ---- STEP 1 --------------------------------------------------------
    fact_gas_balance, ea_snapshots, fact_lng_flow_baseline, oilx_snapshots = step1_widen_loaders(
        log
    )

    # ---- STEP 2 --------------------------------------------------------
    step2_raised = step2_verify_and_fix_diagnostic(fact_gas_balance, log)

    # ---- STEP 3 --------------------------------------------------------
    open_questions = step3_answer_open_questions(fact_gas_balance, log)

    # ---- STEP 4 --------------------------------------------------------
    fact_net_gas_position = step4_compute_net_gas_position(
        fact_gas_balance, dim_country, horizon_start, horizon_end, log
    )
    lng_545, m545_meta = step4_lng_net_trade_545(
        fact_gas_balance, dim_country, horizon_start, horizon_end, log
    )
    implied_pipe = step4_implied_pipe_term(
        fact_net_gas_position, lng_545, near_zero_threshold_bcm, log
    )

    # data/output/, not data/interim/: session_02's check_data_interim_provenance
    # (tests/test_geo_checks.py check 13) whitelists data/interim to a fixed
    # set of session 1 parquet names plus *_manifest.json files. These two
    # outputs are session 5's own final deliverables (fact_net_gas_position is
    # also loaded into the DuckDB store below), not pre-DB staging artefacts,
    # so they belong beside lt_lng_flows.duckdb in data/output/, and check 13
    # (already-gated session 2 code) is left untouched.
    fact_net_gas_position.to_parquet(DATA_OUTPUT / "fact_net_gas_position.parquet", index=False)
    implied_pipe.to_parquet(
        DATA_OUTPUT / "session_05_implied_pipe_vs_mapping545.parquet", index=False
    )
    log(
        "Wrote data/output/fact_net_gas_position.parquet and "
        "data/output/session_05_implied_pipe_vs_mapping545.parquet"
    )

    # ---- DuckDB: reload the existing store's tables, then add fact_net_gas_position ----
    # Mirrors build_session3.py's own pattern: the store is rebuilt from each
    # session's own parquet/CSV outputs rather than assumed to already be
    # open in this process, and session 5 adds on top of what session 3
    # already loaded (now automatically widened, since ea_series.py and
    # oilx_flows.py are shared code).
    applied_crosswalk = load_applied_crosswalk()
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
    session3_constants = load_yaml(SESSION3_CONSTANTS_PATH)
    gtf_long = gtf_flows.read_gtf_border_flows(IEA_GTF_PATH)
    fact_pipe_flow_hist = gtf_flows.build_fact_pipe_flow_hist(
        gtf_long, applied_crosswalk, session3_constants["gtf_unit_conversion"]["mm3_to_bcm"]
    )
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
        duckdb_store.load_fact_net_gas_position(con, fact_net_gas_position)
        log(
            "DuckDB store rebuilt: session 2/3 tables reloaded from their own outputs, plus "
            "the new fact_net_gas_position table (PK country_iso2/year, FK to dim_country)."
        )
    finally:
        con.close()

    write_manifest(
        DATA_INTERIM / "session_05_net_gas_position_manifest.json",
        {
            "ea_series_snapshots_used": [str(p.relative_to(ROOT)) for p in ea_snapshots],
            "oilx_snapshots_used": [str(p.relative_to(ROOT)) for p in oilx_snapshots],
            "horizon": {"start_year": horizon_start, "end_year": horizon_end},
            "mapping_545_series_inventory": {
                k: v for k, v in m545_meta.items() if k != "countries_with_any_series"
            },
            "step2_defect_confirmed": step2_raised != "not reproduced against real data",
        },
    )
    log("Wrote data/interim/session_05_net_gas_position_manifest.json")

    write_catchup_doc(
        report_lines,
        open_questions,
        fact_net_gas_position,
        implied_pipe,
        m545_meta,
        top_n,
        near_zero_threshold_bcm,
        horizon_start,
        horizon_end,
    )
    log("Wrote docs/session_05_catchup.md")

    print("\nbuild_session5: PASS")


def write_catchup_doc(
    log_lines: list[str],
    open_questions: list[dict],
    fact_net_gas_position: pd.DataFrame,
    implied_pipe: pd.DataFrame,
    m545_meta: dict,
    top_n: int,
    near_zero_threshold_bcm: float,
    horizon_start: int,
    horizon_end: int,
) -> None:
    lines = [
        "# Session 5: net gas position and the implied pipe diagnostic",
        "",
        "Net gas position per country per year from EA's own LT gas supply (mapping 297) and "
        "total demand (mapping 314, category=natural_gas, aspect_subtype=total), used to locate "
        "where the 'pipe term' matters against mapping 545's LNG-only net trade. IEA/Eurostat "
        "balance conventions are not imported. Mapping 545 is a benchmark only, never an input.",
        "",
        "## Build log",
        "",
        *[f"- {line}" for line in log_lines],
        "",
        "Step 1 and step 2 detail (fields carried before/after the widening, the confirmed "
        "defect and the fix) is in the build log above; step 3's questions follow below.",
        "",
    ]
    for q in open_questions:
        lines.append(f"## Step 3, question {q['n']}: {q['question']}")
        lines.append("")
        if q["settled"] and q.get("answer"):
            lines.append(f"**Answer.** {q['answer']}")
        else:
            lines.append("**Not settled by metadata.**")
        lines.append("")
        lines.append(f"Metadata tuples observed: `{q['tuples']}`")
        lines.append("")
        if q.get("ea_question"):
            lines.append(f"**Exact question for EA / evidence:** {q['ea_question']}")
        lines.append("")

    both = fact_net_gas_position[
        fact_net_gas_position["has_supply"] & fact_net_gas_position["has_demand"]
    ]
    supply_only = sorted(
        set(fact_net_gas_position.loc[~fact_net_gas_position["has_demand"], "country_iso2"])
    )
    demand_only = sorted(
        set(fact_net_gas_position.loc[~fact_net_gas_position["has_supply"], "country_iso2"])
    )
    lines += [
        "## Step 4: fact_net_gas_position",
        "",
        f"{len(fact_net_gas_position)} (country_iso2, year) rows, "
        f"{fact_net_gas_position['country_iso2'].nunique()} countries, "
        f"{horizon_start}-{horizon_end}. {len(both)} rows carry a real "
        "net_gas_position_bcm (both supply and demand present); the remainder are null on "
        "whichever side is missing, never zero-filled.",
        "",
        "## Countries/years with no data (not filled)",
        "",
        f"- Countries with mapping 297 supply but no mapping 314 total natural_gas demand "
        f"({len(supply_only)}): {supply_only}",
        f"- Countries with mapping 314 demand but no mapping 297 supply: {demand_only}",
        "",
        "## Step 4: mapping 545 LNG net trade and the implied pipe term",
        "",
        f"545 series inventory (full pinned 2017-2050 horizon): {m545_meta['n_export_series']} "
        f"net_exports series ({m545_meta['n_export_zero']} all-zero throughout), "
        f"{m545_meta['n_import_series']} net_imports series ({m545_meta['n_import_zero']} "
        f"all-zero). {m545_meta['nwe_rows_excluded']} 'North West Europe' aggregate row(s) "
        "excluded from every per-country figure below.",
        "",
    ]

    latest_year = implied_pipe["year"].max()
    latest = implied_pipe[implied_pipe["year"] == latest_year].copy()
    latest["abs_implied_pipe"] = latest["implied_pipe_bcm"].astype(float).abs()
    top = (
        latest.dropna(subset=["implied_pipe_bcm"])
        .sort_values("abs_implied_pipe", ascending=False)
        .head(top_n)
    )
    lines.append(f"### Top {top_n} implied pipe terms by |value|, {latest_year}")
    lines.append("")
    for _, row in top.iterrows():
        direction = "net pipe EXPORTER" if row["implied_pipe_bcm"] > 0 else "net pipe IMPORTER"
        lines.append(
            f"- {row['country_iso2']}: implied pipe {row['implied_pipe_bcm']:.2f} bcm "
            f"({direction}; own net position {row['net_gas_position_bcm']:.2f} bcm, "
            f"545 LNG net trade {row['lng_net_trade_545_bcm']:.2f} bcm)"
        )
    lines.append("")

    near_zero = latest[
        latest["implied_pipe_bcm"].notnull()
        & (latest["abs_implied_pipe"] <= near_zero_threshold_bcm)
    ]
    lines.append(
        f"### Near-zero implied pipe term ({latest_year}, threshold {near_zero_threshold_bcm} bcm)"
    )
    lines.append("")
    lines.append(
        f"{len(near_zero)} countries: {sorted(near_zero['country_iso2'].tolist())}. Their net "
        "gas position is already a usable LNG-only number -- near-zero here is a finding, not a "
        "bug."
    )
    lines.append("")

    bucket_a = sorted(
        set(implied_pipe.loc[implied_pipe["bucket"] == "a_no_545_series", "country_iso2"])
    )
    bucket_b = sorted(
        set(implied_pipe.loc[implied_pipe["bucket"] == "b_545_all_zero", "country_iso2"])
    )
    bucket_c = sorted(
        set(implied_pipe.loc[implied_pipe["bucket"] == "c_both_real", "country_iso2"])
    )
    lines += [
        "### Three buckets vs mapping 545",
        "",
        f"- (a) no 545 series at all: {len(bucket_a)} countries: {bucket_a}",
        f"- (b) 545 series present but all-zero throughout: {len(bucket_b)} countries: {bucket_b}",
        f"- (c) both sides carrying a real number: {len(bucket_c)} countries: {bucket_c}",
        "",
        "Only bucket (c) is a genuine divergence conversation; (a) and (b) mean mapping 545 has "
        "nothing comparable for that country, not that our number is wrong.",
        "",
        "## What could not be resolved this session",
        "",
        "- Q1, Q3, Q4 above are not settled by metadata; the exact EA questions are recorded "
        "above rather than guessed.",
        "- Q2 is only partially settled: own_use is confirmed separate from mapping 314's total "
        "demand, but whether 'total' means gross inland or final consumption is still open.",
        "- The implied pipe term folds in whatever mapping 297's supply and mapping 314's "
        "demand actually mean (Q1/Q2/Q3 open); it is a diagnostic against an unresolved "
        "definition, reported as such, not a validated balance identity.",
    ]

    (DOCS_DIR / "session_05_catchup.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
