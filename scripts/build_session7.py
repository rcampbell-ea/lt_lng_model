"""
build_session7.py
--------------------
Session 7: a net pipe flow timeseries per country, 2025-2050 (plus history
back to 2008 wherever IEA GTF measures it), from a documented set of
analyst assumptions (``config/pipeline_flows.yaml``, STEP 1-3 and STEP 5;
``config/pipeline_projects.yaml``, STEP 4). The assumptions file is the
input; ``fact_pipe_net_position`` is the deliverable. No LNG number is
computed this session -- that is session 8.

Run with the ``lt_lng_flows`` conda environment active, after sessions 1-3
and 6 have produced ``data/geo/dim_country.parquet``,
``data/geo/dim_country_adjacency.parquet``, the pinned IEA GTF export, and
``data/output/fact_net_gas_position.parquet``:

    python scripts/build_session7.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.ingest.provenance import write_manifest  # noqa: E402
from lt_lng_flows.output import duckdb_store, session7_outputs  # noqa: E402
from lt_lng_flows.pipe import gtf_flows  # noqa: E402
from lt_lng_flows.pipe import pipe_flow_forecast as pff  # noqa: E402

CONFIG_DIR = ROOT / "config"
DATA_RAW = ROOT / "data" / "raw"
DATA_GEO = ROOT / "data" / "geo"
DATA_OUTPUT = ROOT / "data" / "output"
DATA_INTERIM = ROOT / "data" / "interim"
CROSSWALKS_DIR = ROOT / "crosswalks"
DOCS_DIR = ROOT / "docs"

IEA_GTF_PATH = DATA_RAW / "iea_gtf" / "Export_GTF_IEA_202606.xlsx"
SESSION3_CONSTANTS_PATH = CONFIG_DIR / "session_03_constants.yaml"
SESSION7_CONSTANTS_PATH = CONFIG_DIR / "session_07_constants.yaml"
PIPELINE_FLOWS_PATH = CONFIG_DIR / "pipeline_flows.yaml"
PIPELINE_PROJECTS_PATH = CONFIG_DIR / "pipeline_projects.yaml"
XWALK_COUNTRY_ALIAS_PATH = CROSSWALKS_DIR / "xwalk_country_alias.csv"
XWALK_EA_API_COUNTRY_PATH = CROSSWALKS_DIR / "xwalk_ea_api_country.csv"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_applied_crosswalk() -> pd.DataFrame:
    """Same construction as build_session2/3/5/6.py's loader of the same
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
    """The 78 countries session 6 has both supply and demand for -- the
    scope named by the session 7 task, derived from session 6's own output
    rather than re-typed."""
    both = fact_net_gas_position[fact_net_gas_position["missing_side"].isnull()]
    return sorted(both["country_iso2"].unique().tolist())


def build_corridor_timeseries(
    dim_country: pd.DataFrame,
    dim_country_adjacency: pd.DataFrame,
    applied_crosswalk: pd.DataFrame,
    mm3_to_bcm: float,
    pipeline_flows_cfg: dict,
    session7_constants: dict,
    log,
) -> tuple[pd.DataFrame, dict]:
    horizon = session7_constants["horizon"]

    gtf_long = gtf_flows.read_gtf_border_flows(IEA_GTF_PATH)
    fact_pipe_flow_hist = gtf_flows.build_fact_pipe_flow_hist(
        gtf_long, applied_crosswalk, mm3_to_bcm
    )
    months_observed = pff.corridor_months_observed(gtf_long, applied_crosswalk)
    real_country_codes = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])

    n_all_corridors = fact_pipe_flow_hist[["origin_iso2", "destination_iso2"]].drop_duplicates()
    measured, stale = pff.project_measured_corridors(
        fact_pipe_flow_hist,
        months_observed,
        real_country_codes,
        pipeline_flows_cfg["measured_corridor_overrides"],
        pipeline_flows_cfg["measured_corridor_default_continuation"],
        horizon["end"],
        session7_constants["stale_year_threshold"],
    )
    n_measured_corridors = measured[["origin_iso2", "destination_iso2"]].drop_duplicates()
    log(
        f"STEP 1: {len(n_measured_corridors)} GTF corridors carried through as basis: measured "
        f"(of {len(n_all_corridors)} raw GTF corridors; "
        f"{len(n_all_corridors) - len(n_measured_corridors)} excluded for a pseudo-code endpoint "
        "-- 'Liquefied Natural Gas' or 'Not Elsewhere Specified' -- not a physical pipe corridor)."
    )
    log(
        f"STEP 3: {len(stale)} measured corridor(s) excluded from continuation as stale "
        f"(last observed before {session7_constants['stale_year_threshold']}): "
        f"{[(s['origin_iso2'], s['destination_iso2'], s['last_observed_year']) for s in stale]}."
    )

    assumed, undecided_assumed = pff.project_assumed_corridors(
        pipeline_flows_cfg["corridors_assumed"], horizon["start"], horizon["end"]
    )
    n_assumed_corridors = len(pipeline_flows_cfg["corridors_assumed"])
    n_undecided = len(undecided_assumed)
    log(
        f"STEP 2: {n_assumed_corridors} hand-listed corridors outside GTF coverage; "
        f"{n_assumed_corridors - n_undecided} carry an analyst current flow and continuation "
        f"(basis: assumed), {n_undecided} are undecided (null flow, named in this report)."
    )

    flagged_pairs = [
        (c["origin_iso2"], c["destination_iso2"]) for c in pipeline_flows_cfg["corridors_assumed"]
    ]
    non_adjacent = pff.check_corridor_adjacency(flagged_pairs, dim_country_adjacency)
    yaml_flagged = {
        (c["origin_iso2"], c["destination_iso2"])
        for c in pipeline_flows_cfg["corridors_assumed"]
        if c.get("adjacency_flag")
    }
    mismatch = set(non_adjacent) ^ yaml_flagged
    match_note = (
        "Matches pipeline_flows.yaml's adjacency_flag annotations exactly."
        if not mismatch
        else "MISMATCH vs pipeline_flows.yaml adjacency_flag annotations: " + str(sorted(mismatch))
    )
    log(
        f"STEP 2: adjacency check (dim_country_adjacency) -- {len(non_adjacent)} pair(s) with "
        f"neither geometric adjacency nor a signed-off override: {sorted(non_adjacent)}. "
        f"{match_note}"
    )

    combined = pd.concat([measured, assumed], ignore_index=True)
    diagnostics = {
        "stale_corridors": stale,
        "undecided_assumed_corridors": undecided_assumed,
        "non_adjacent_pairs": sorted(non_adjacent),
    }
    return combined, diagnostics


def main() -> None:
    report_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        report_lines.append(msg)

    session3_constants = load_yaml(SESSION3_CONSTANTS_PATH)
    session7_constants = load_yaml(SESSION7_CONSTANTS_PATH)
    pipeline_flows_cfg = load_yaml(PIPELINE_FLOWS_PATH)
    pipeline_projects_cfg = load_yaml(PIPELINE_PROJECTS_PATH)
    mm3_to_bcm = session3_constants["gtf_unit_conversion"]["mm3_to_bcm"]
    horizon = session7_constants["horizon"]

    dim_country = pd.read_parquet(DATA_GEO / "dim_country.parquet")
    dim_country_adjacency = pd.read_parquet(DATA_GEO / "dim_country_adjacency.parquet")
    applied_crosswalk = load_applied_crosswalk()
    fact_net_gas_position = pd.read_parquet(DATA_OUTPUT / "fact_net_gas_position.parquet")

    modelled_countries = modelled_countries_from_session6(fact_net_gas_position)
    log(
        f"Scope: {len(modelled_countries)} modelled countries (session 6's countries with both "
        "supply and demand in at least one year)."
    )

    corridor_timeseries, diagnostics = build_corridor_timeseries(
        dim_country,
        dim_country_adjacency,
        applied_crosswalk,
        mm3_to_bcm,
        pipeline_flows_cfg,
        session7_constants,
        log,
    )

    # ---- STEP 5: explicit zero, derived not hand-typed --------------------
    touched = set(
        corridor_timeseries["origin_iso2"].tolist()
        + corridor_timeseries["destination_iso2"].tolist()
    )
    zero_countries_derived = sorted(set(modelled_countries) - touched)
    expected = sorted(c["country_iso2"] for c in pipeline_flows_cfg["zero_countries_expected"])
    if zero_countries_derived != expected:
        log(
            "STEP 5: WARNING -- derived zero-coverage set differs from "
            f"pipeline_flows.yaml's zero_countries_expected. Derived: {zero_countries_derived}; "
            f"expected: {expected}."
        )
    else:
        log(
            f"STEP 5: {len(zero_countries_derived)} modelled countries have no cross-border pipe "
            f"in any measured or assumed corridor -- matches pipeline_flows.yaml's "
            f"zero_countries_expected exactly: {zero_countries_derived}."
        )

    # ---- STEP 6: net per country per year ----------------------------------
    net_position = pff.net_country_position(
        corridor_timeseries,
        modelled_countries,
        zero_countries_derived,
        horizon["start"],
        horizon["end"],
        horizon["history_start"],
    )
    net_position["year"] = net_position["year"].astype(int)
    log(
        f"STEP 6: fact_pipe_net_position built: {len(net_position)} (country_iso2, year) rows, "
        f"{net_position['country_iso2'].nunique()} countries, "
        f"{net_position['year'].min()}-{net_position['year'].max()}."
    )
    basis_counts = net_position["basis"].value_counts().to_dict()
    log(f"STEP 6: basis breakdown across all rows: {basis_counts}")

    horizon_rows = net_position[net_position["year"].between(horizon["start"], horizon["end"])]
    missing_years = set(range(horizon["start"], horizon["end"] + 1)) - set(horizon_rows["year"])
    n_expected = len(modelled_countries) * (horizon["end"] - horizon["start"] + 1)
    assert not missing_years, f"gate failure: missing horizon years {missing_years}"
    assert len(horizon_rows) == n_expected, (
        f"gate failure: expected {n_expected} horizon rows (78 countries x "
        f"{horizon['end'] - horizon['start'] + 1} years), got {len(horizon_rows)}"
    )
    assert set(horizon_rows["country_iso2"]) == set(modelled_countries), (
        "gate failure: country mismatch"
    )
    log(
        f"Gate: {n_expected} rows present for all {len(modelled_countries)} modelled countries, "
        f"every year {horizon['start']}-{horizon['end']}."
    )

    # ---- write parquet ------------------------------------------------------
    out_path = DATA_OUTPUT / "fact_pipe_net_position.parquet"
    net_position.to_parquet(out_path, index=False)
    log(f"Wrote data/output/{out_path.name}.")

    # ---- HTML report ----------------------------------------------------
    html_path = DATA_OUTPUT / "session_07_pipe_net_position.html"
    session7_outputs.build_html(net_position, dim_country, html_path)
    log(f"Wrote data/output/{html_path.name}.")

    # ---- FK/PK join check against fact_net_gas_position --------------------
    joined = horizon_rows.merge(
        fact_net_gas_position[["country_iso2", "year"]],
        on=["country_iso2", "year"],
        how="left",
        indicator=True,
    )
    unmatched = joined[joined["_merge"] == "left_only"]
    assert unmatched.empty, (
        f"gate failure: {len(unmatched)} unmatched keys against fact_net_gas_position"
    )
    log(
        "Gate: fact_pipe_net_position joins to fact_net_gas_position on (country_iso2, year) "
        "with no unmatched keys."
    )

    # ---- residual-at-stake ranking for undecided corridors -----------------
    ranking_year = session7_constants["residual_ranking_year"]
    surplus_at_year = fact_net_gas_position[
        fact_net_gas_position["year"] == ranking_year
    ].set_index("country_iso2")["surplus_deficit_bcm"]
    ranked_undecided = []
    for corridor in diagnostics["undecided_assumed_corridors"]:
        residuals = [
            abs(surplus_at_year[c])
            for c in (corridor["origin_iso2"], corridor["destination_iso2"])
            if c in surplus_at_year.index and pd.notna(surplus_at_year[c])
        ]
        ranked_undecided.append(
            {
                **corridor,
                "residual_at_stake_bcm": max(residuals) if residuals else None,
            }
        )
    ranked_undecided.sort(key=lambda c: c["residual_at_stake_bcm"] or 0, reverse=True)

    # ---- rebuild DuckDB store (fresh, session 6's own outputs) --------------
    con = duckdb_store.create_store(DATA_OUTPUT / "lt_lng_flows.duckdb")
    try:
        dim_country_adjacency_reload = dim_country_adjacency  # already loaded above
        duckdb_store.load_dim_country(con, dim_country)
        duckdb_store.load_dim_country_adjacency(con, dim_country_adjacency_reload)
        duckdb_store.load_xwalk_country_alias(con, applied_crosswalk)
        duckdb_store.load_fact_net_gas_position(con, fact_net_gas_position)
        duckdb_store.load_fact_pipe_net_position(con, net_position)
        log(
            "DuckDB store rebuilt: dim_country, dim_country_adjacency, xwalk_country_alias, "
            "fact_net_gas_position reloaded, plus the new fact_pipe_net_position table (PK "
            "country_iso2/year, FK to dim_country)."
        )
    finally:
        con.close()

    write_manifest(
        DATA_INTERIM / "session_07_pipe_assumptions_manifest.json",
        {
            "iea_gtf_path": str(IEA_GTF_PATH.relative_to(ROOT)),
            "pipeline_flows_config": str(PIPELINE_FLOWS_PATH.relative_to(ROOT)),
            "pipeline_projects_config": str(PIPELINE_PROJECTS_PATH.relative_to(ROOT)),
            "horizon": horizon,
            "modelled_countries": modelled_countries,
        },
    )
    log("Wrote data/interim/session_07_pipe_assumptions_manifest.json")

    write_report(
        report_lines,
        net_position,
        corridor_timeseries,
        diagnostics,
        ranked_undecided,
        pipeline_projects_cfg,
        modelled_countries,
        horizon,
    )
    log("Wrote docs/session_07_pipe_assumptions.md")

    print("\nbuild_session7: PASS")


def write_report(
    log_lines: list[str],
    net_position: pd.DataFrame,
    corridor_timeseries: pd.DataFrame,
    diagnostics: dict,
    ranked_undecided: list[dict],
    pipeline_projects_cfg: dict,
    modelled_countries: list[str],
    horizon: dict,
) -> None:
    corridor_basis = corridor_timeseries[
        ["origin_iso2", "destination_iso2", "basis"]
    ].drop_duplicates(subset=["origin_iso2", "destination_iso2"], keep="last")
    basis_counts = corridor_basis["basis"].value_counts().to_dict()

    horizon_rows = net_position[net_position["year"].between(horizon["start"], horizon["end"])]

    def _coverage_category(s: pd.Series) -> str:
        if (s == "measured").all():
            return "measured"
        if s.nunique() > 1:
            return "mixed"
        return s.iloc[0]

    coverage_by_basis = (
        horizon_rows.groupby("country_iso2")["basis"]
        .agg(_coverage_category)
        .value_counts()
        .to_dict()
    )

    def _table_for_year(year: int) -> str:
        rows = net_position[net_position["year"] == year].sort_values(
            "net_pipe_bcm", key=lambda s: s.abs(), ascending=False, na_position="last"
        )
        lines = ["| country_iso2 | net_pipe_bcm | basis |", "|---|---|---|"]
        for _, r in rows.iterrows():
            val = "null" if pd.isna(r["net_pipe_bcm"]) else f"{r['net_pipe_bcm']:.2f}"
            lines.append(f"| {r['country_iso2']} | {val} | {r['basis']} |")
        return "\n".join(lines)

    lines = [
        "# Session 7: net pipe flow timeseries per country, 2025-2050",
        "",
        "`fact_pipe_net_position` -- net pipe bcm per (`country_iso2`, `year`), same grain as "
        "`fact_net_gas_position` so the two join directly. Built from a documented set of "
        "analyst assumptions (`config/pipeline_flows.yaml` and `config/pipeline_projects.yaml`): "
        "IEA GTF's own 148 measured corridors, hand-listed corridors outside GTF coverage, and "
        "prospective new connections (documented, not yet netted). No LNG number is computed "
        "this session -- that is session 8.",
        "",
        "## Build log",
        "",
        *[f"- {line}" for line in log_lines],
        "",
        "## Corridor counts by basis",
        "",
        f"{len(corridor_basis)} corridors total (one row per (origin, destination) pair, its "
        "basis in the final horizon year it appears): "
        + ", ".join(f"{k}: {v}" for k, v in sorted(basis_counts.items())),
        "",
        "## Countries by coverage category (2025-2050)",
        "",
        "A country whose corridors are all `measured` for every horizon year is reported "
        "`measured`; one blending `measured` and `assumed` corridors in the same year is reported "
        "`mixed`; otherwise the single basis every horizon year shares.",
        "",
        *[f"- {k}: {v} countries" for k, v in sorted(coverage_by_basis.items())],
        "",
        "## Net pipe by country, 2030",
        "",
        _table_for_year(2030),
        "",
        "## Net pipe by country, 2050",
        "",
        _table_for_year(2050),
        "",
        "## Corridors awaiting an analyst number, ranked by residual at stake",
        "",
        "Residual at stake is `|surplus_deficit_bcm|` in "
        f"{2030} (session 6's `fact_net_gas_position`) for whichever endpoint of the corridor is "
        "itself a modelled country, taken as the larger of the two where both are modelled -- a "
        "stand-in for how much rides on this particular number, not a claim that the corridor "
        "explains that residual.",
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
        "## STEP 4: prospective new connections (documented, not netted)",
        "",
        "Origin and destination are stated as facts in `config/pipeline_projects.yaml`; flow, "
        "start year and source are left null for the analyst. None is netted into "
        "`fact_pipe_net_position` -- a project without a stated start year has no defensible year "
        "to begin contributing, so the central case does not include it yet.",
        "",
        "| project | origin | destination |",
        "|---|---|---|",
        *[
            f"| {p['name']} | {p['origin_iso2']} | {p['destination_iso2']} |"
            for p in pipeline_projects_cfg["projects"]
        ],
        "",
        "## STEP 5: explicit zero coverage",
        "",
        "Derived programmatically as (modelled countries) minus (every country appearing as an "
        "origin or destination in any measured or assumed corridor), not hand-typed -- see the "
        "build log line above for whether this matched `pipeline_flows.yaml`'s "
        "`zero_countries_expected` list.",
        "",
        "## Stale measured corridors (excluded from continuation)",
        "",
        (
            "None."
            if not diagnostics["stale_corridors"]
            else "\n".join(
                f"- {s['origin_iso2']}-{s['destination_iso2']}: last observed "
                f"{s['last_observed_year']}, no continuation assumed (see "
                "pipe_flow_forecast.py docstring on the RU-UA trap)."
                for s in diagnostics["stale_corridors"]
            )
        ),
        "",
        "## Adjacency check on hand-listed corridors",
        "",
        f"Pairs with neither geometric adjacency nor a signed-off override in "
        f"`dim_country_adjacency` (the check build plan session 3 already added, reused here): "
        f"{diagnostics['non_adjacent_pairs']}. These are real named links (subsea pipelines, "
        "multi-country transit corridors), not data errors -- flagged in "
        "`pipeline_flows.yaml`'s `adjacency_flag` field and, where a genuinely direct subsea link "
        "exists (Dolphin QA-AE, the MY-SG and ID-SG interconnections), noted as candidates for "
        "`crosswalks/adjacency_override.csv`, pending sign-off -- not added by this session.",
        "",
        "## What could not be resolved this session",
        "",
        '- The corridors listed above under "awaiting an analyst number" have no defensible '
        "current-flow figure from the sources checked (China stopped publishing per-country "
        "physical pipe volumes after 2022/2023 for several Central Asian corridors; several "
        "African and Southeast Asian corridors report throughput in units other than bcm, or not "
        "at a corridor-specific level at all). Left null, not estimated from a partial or "
        "aggregate proxy.",
        "- STEP 4's new connections carry no flow, start year or source -- none has reached FID, "
        "so none is netted into the central case this session.",
        "- No LNG number is computed this session, by the task's own instruction -- that is "
        "session 8.",
        "- A country's whole net_pipe_bcm cell is null for a year if *any* corridor touching it "
        "is undecided that year, even where its other corridors are well measured -- CN is the "
        "sharpest case: RU-CN, KZ-CN, MM-CN and TM-CN are all known (roughly 75-80 bcm combined "
        "by the 2030s), but CN's net position is reported null throughout because UZ-CN is "
        "undecided. Netting a partial figure and treating the unknown UZ-CN leg as zero would be "
        "exactly the zero-filled-to-look-complete failure mode this session's task warns "
        "against, so the null stands -- this is the corridor the residual-at-stake ranking above "
        "puts first.",
    ]

    (DOCS_DIR / "session_07_pipe_assumptions.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
