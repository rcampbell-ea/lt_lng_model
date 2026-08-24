"""
build_session2.py
--------------------
Session 2: geo master (sessions_02_03_build_plan.md section 2, build plan
section 4). Reads the two network-pulled geo snapshots (already fetched by
``scripts/pull_geo_snapshots.py``), the signed-off alias crosswalk from gate
A, and the pinned workbooks and IEA GTF file. Produces deliverables 2.2 to
2.10, running build plan 4.8 checks 1-5 and 8-11 as each one lands, and
writes ``docs/session_02_geo_master.md``.

Checks 6 and 7 (port coordinates, route distances) cannot run until gate B
closes: they are reported skipped with a reason, not implemented as
pass/fail (build plan 2.9).

Run with the ``lt_lng_flows`` conda environment active, after
``python scripts/pull_geo_snapshots.py``:

    python scripts/build_session2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.geo import adjacency as adjacency_mod  # noqa: E402
from lt_lng_flows.geo import dim_country_v2, node_master, port_candidate  # noqa: E402
from lt_lng_flows.geo import natural_earth as ne  # noqa: E402
from lt_lng_flows.geo.country_master import build_dim_country as build_dim_country_v1  # noqa: E402
from lt_lng_flows.ingest import workbook_reader  # noqa: E402
from lt_lng_flows.ingest.provenance import file_fact, write_manifest  # noqa: E402
from lt_lng_flows.output import duckdb_store  # noqa: E402
from lt_lng_flows.validate import geo_checks  # noqa: E402

CONFIG_DIR = ROOT / "config"
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_GEO = ROOT / "data" / "geo"
DATA_OUTPUT = ROOT / "data" / "output"
CROSSWALKS_DIR = ROOT / "crosswalks"
DOCS_DIR = ROOT / "docs"

WORKBOOK_ROOT = DATA_RAW / "workbooks" / "202608"
IEA_GTF_PATH = DATA_RAW / "iea_gtf" / "Export_GTF_IEA_202606.xlsx"

ISO_CSV_PATH = DATA_GEO / "raw" / "iso3166_1_countries.csv"
PSEUDO_CODES_CONFIG = CONFIG_DIR / "pseudo_country_codes.yaml"
LNG_NODES_CONFIG = CONFIG_DIR / "lng_nodes.yaml"
SESSION2_CONSTANTS_PATH = CONFIG_DIR / "session_02_constants.yaml"

ADMIN0_SHP = DATA_GEO / "raw" / "ne_50m_admin_0" / "ne_50m_admin_0_countries.shp"
ADMIN0_MANIFEST = DATA_GEO / "raw" / "ne_50m_admin_0" / "natural_earth_admin0_50m_manifest.json"
PORTS_SHP = DATA_GEO / "raw" / "ports" / "ne_10m_ports.shp"

XWALK_COUNTRY_ALIAS_PATH = CROSSWALKS_DIR / "xwalk_country_alias.csv"
XWALK_EA_API_COUNTRY_PATH = CROSSWALKS_DIR / "xwalk_ea_api_country.csv"

PORT_ROLE_BY_SOURCE_SYSTEM = {"workbook_liquefaction": "load", "workbook_regas": "discharge"}


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_applied_crosswalk() -> pd.DataFrame:
    alias = pd.read_csv(XWALK_COUNTRY_ALIAS_PATH, dtype=str, keep_default_na=False, na_values=[])
    alias = alias.rename(columns={"proposed_iso2": "country_iso2"})
    ea_api = pd.read_csv(XWALK_EA_API_COUNTRY_PATH, dtype=str, keep_default_na=False, na_values=[])
    combined = pd.concat(
        [
            alias[["source_system", "raw_value", "country_iso2", "confidence", "method", "note"]],
            ea_api[["source_system", "raw_value", "country_iso2", "confidence", "method", "note"]],
        ],
        ignore_index=True,
    )
    return combined


def main() -> None:
    report_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        report_lines.append(msg)

    constants = load_yaml(SESSION2_CONSTANTS_PATH)
    lng_nodes_cfg = load_yaml(LNG_NODES_CONFIG)
    split_country_nodes = lng_nodes_cfg["split_country_nodes"]
    split_country_codes = set(split_country_nodes.keys())

    # ---- 2.2 applied alias crosswalk, EA API source system merged in -----
    applied_crosswalk = load_applied_crosswalk()
    geo_checks.session2_check_2_all_raw_values_resolved(applied_crosswalk)
    geo_checks.session2_check_3_alias_many_to_one(applied_crosswalk)
    log(f"4.8 check 2 (all raw values resolved): PASS ({len(applied_crosswalk)} rows)")
    log("4.8 check 3 (alias many-to-one per source system): PASS")

    # ---- iso-only dim_country base (session 1 shape, now with XX) --------
    iso_dim_country = build_dim_country_v1(ISO_CSV_PATH, PSEUDO_CODES_CONFIG)
    real_country_codes = set(
        iso_dim_country.loc[iso_dim_country["is_real_country"], "country_iso2"]
    )

    # ---- Natural Earth admin0: dissolve, centroid, adjacency, landlocked -
    log("Reading Natural Earth Admin 0 Countries, 1:50m...")
    admin0 = ne.read_admin0(ADMIN0_SHP)
    ne_cfg = constants["natural_earth_admin0"]
    if len(admin0) != ne_cfg["expected_row_count"]:
        raise AssertionError(
            f"ne_50m_admin_0_countries: expected {ne_cfg['expected_row_count']} rows, "
            f"found {len(admin0)}. Snapshot vintage has moved; re-verify before proceeding."
        )
    dissolved, continent_inconsistencies = ne.dissolve_by_country_iso2(
        admin0, ne_cfg["type_preference_order"]
    )
    for item in continent_inconsistencies:
        log(
            f"Natural Earth continent/subregion inconsistency for {item['country_iso2']}: "
            f"continent values {item['continent_values']}, resolved to "
            f"{item['resolved_continent']!r} from row {item['resolved_from_row']!r}"
        )

    centroids = ne.compute_centroids(dissolved)
    adjacency_cfg = constants["adjacency"]
    geometric_adjacency_raw = ne.compute_adjacency(
        dissolved, adjacency_cfg["shared_border_buffer_degrees"]
    )
    is_landlocked = ne.compute_is_landlocked(dissolved, adjacency_cfg["landlocked_buffer_degrees"])
    log(
        f"Natural Earth: {len(dissolved)} real countries dissolved, "
        f"{is_landlocked['is_landlocked'].sum()} landlocked"
    )

    # ---- role_lng / role_pipe ---------------------------------------------
    raw_country_strings = pd.read_parquet(DATA_INTERIM / "raw_country_strings.parquet")
    role_lng = dim_country_v2.derive_role_lng(raw_country_strings, applied_crosswalk)
    role_pipe = dim_country_v2.derive_role_pipe(raw_country_strings, applied_crosswalk)
    log(
        f"role_lng derived for {len(role_lng)} countries; role_pipe derived for "
        f"{len(role_pipe)} countries (see report note on 'transit' scoping)"
    )

    # ---- 2.3 dim_country, replacing session 1's interim version ----------
    import json

    admin0_manifest_data = json.loads(ADMIN0_MANIFEST.read_text(encoding="utf-8"))
    geo_lineage = {
        "geo_source": "natural_earth_admin0_50m",
        "geo_snapshot_date": admin0_manifest_data["retrieved_at"],
        "geo_snapshot_sha256": admin0_manifest_data["files"]["ne_50m_admin_0_countries.zip"][
            "sha256"
        ],
    }

    old_dim_country_path = DATA_GEO / "dim_country.parquet"
    old_codes: set[str] = set()
    if old_dim_country_path.is_file():
        old_dim_country = pd.read_parquet(old_dim_country_path)
        old_codes = set(old_dim_country["country_iso2"])

    dim_country, missing_geometry, missing_geometry_relevant = dim_country_v2.build_dim_country(
        iso_dim_country, dissolved, centroids, is_landlocked, role_lng, role_pipe, geo_lineage
    )
    non_relevant_gap = sorted(set(missing_geometry) - set(missing_geometry_relevant))
    if non_relevant_gap:
        log(
            f"Real countries with no Natural Earth geometry at 1:50m (no LNG or pipe role): "
            f"{non_relevant_gap}. continent/un_subregion/centroid/is_landlocked and geo "
            f"lineage are null for these; not a build blocker."
        )
    if missing_geometry_relevant:
        log(
            f"GATE C (sessions_02_03_build_plan.md section 0): {missing_geometry_relevant} "
            f"appear with a non-none role_lng or role_pipe but have no polygon in the 1:50m "
            f"admin0 layer. Not resolved this run; see gate C for the two closing paths."
        )
    new_codes = set(dim_country["country_iso2"])
    added, removed = sorted(new_codes - old_codes), sorted(old_codes - new_codes)
    log(f"dim_country country list diff vs session 1: added={added}, removed={removed}")

    geo_checks.session2_check_1_country_iso2_shape(dim_country, iso_dim_country)
    log("4.8 check 1 (country_iso2 shape and ISO coverage): PASS")

    dim_country.to_parquet(DATA_GEO / "dim_country.parquet", index=False)
    log(f"Wrote data/geo/dim_country.parquet ({len(dim_country)} rows)")

    # ---- 2.4 geo_country_geometry.parquet ---------------------------------
    check4_gap = geo_checks.session2_check_4_geometry_and_containment(
        dim_country, dissolved, centroids
    )
    if check4_gap:
        log(f"4.8 check 4 (geometry, centroid contained): FAILED for {check4_gap}, see gate C")
    else:
        log("4.8 check 4 (geometry present, centroid contained): PASS")
    geometry_out = dissolved[["country_iso2", "geometry"]].copy()
    geometry_out = gpd.GeoDataFrame(geometry_out, geometry="geometry", crs=admin0.crs)
    geometry_out.to_parquet(DATA_GEO / "geo_country_geometry.parquet", index=False)
    log(f"Wrote data/geo/geo_country_geometry.parquet ({len(geometry_out)} rows)")

    # ---- Gate D: Natural Earth geometry exists for entities dim_country --
    # does not carry (Kosovo, ISO_A2_EH='XK'). Plan 4.4 reserves XK for
    # Kosovo ("avoid XK, already used de facto for Kosovo") but never
    # formally adds a dim_country row for it, and Kosovo is not in the
    # session 1 ISO 3166-1 snapshot (it has no official ISO code). Kosovo
    # appears in none of the pinned LNG/GTF sources, so it carries no LNG or
    # pipe role either. Rather than invent a real/pseudo classification for
    # it unilaterally, geometry-only codes with no dim_country row are
    # dropped from the adjacency outputs (which declare a foreign key to
    # dim_country) and the gap is named here for a session 3+ decision.
    dissolved_only_codes = sorted(set(dissolved["country_iso2"]) - new_codes)
    if dissolved_only_codes:
        log(
            f"GATE D (sessions_02_03_build_plan.md section 0): Natural Earth geometry exists "
            f"for {dissolved_only_codes} with no corresponding dim_country row. Excluded from "
            f"dim_country_adjacency, which has a foreign key to dim_country. Not resolved "
            f"this run; see gate D."
        )
    geometric_adjacency = geometric_adjacency_raw[
        geometric_adjacency_raw["country_iso2_a"].isin(new_codes)
        & geometric_adjacency_raw["country_iso2_b"].isin(new_codes)
    ].reset_index(drop=True)

    # ---- 2.5 dim_country_adjacency + adjacency_override -------------------
    gtf_border_pairs = workbook_reader.read_iea_gtf_border_pairs(IEA_GTF_PATH)
    override = adjacency_mod.build_adjacency_override(
        gtf_border_pairs, applied_crosswalk, geometric_adjacency, real_country_codes
    )
    override.to_csv(CROSSWALKS_DIR / "adjacency_override.csv", index=False)
    log(f"Wrote crosswalks/adjacency_override.csv ({len(override)} evidenced rows)")
    applied_adjacency = adjacency_mod.apply_adjacency_override(geometric_adjacency, override)
    geo_checks.session2_check_9_adjacency_symmetric_and_pipe_corridors(
        applied_adjacency, gtf_border_pairs, applied_crosswalk, real_country_codes
    )
    log("4.8 check 9 (adjacency symmetric, GTF corridors covered): PASS")
    applied_adjacency.to_parquet(DATA_GEO / "dim_country_adjacency.parquet", index=False)
    log(f"Wrote data/geo/dim_country_adjacency.parquet ({len(applied_adjacency)} rows)")

    # ---- 4.8 check 8: no landlocked LNG role ------------------------------
    geo_checks.session2_check_8_no_landlocked_lng_role(dim_country)
    log("4.8 check 8 (no landlocked LNG exporter/importer): PASS")

    # ---- 2.6 dim_supply_node / dim_demand_node ----------------------------
    supply_node = node_master.build_supply_node(dim_country, split_country_nodes)
    demand_node = node_master.build_demand_node(dim_country, split_country_nodes)
    supply_node.to_parquet(DATA_GEO / "dim_supply_node.parquet", index=False)
    demand_node.to_parquet(DATA_GEO / "dim_demand_node.parquet", index=False)
    log(
        f"Wrote dim_supply_node.parquet ({len(supply_node)} nodes) and "
        f"dim_demand_node.parquet ({len(demand_node)} nodes)"
    )

    xwalk_area_node = pd.read_csv(CROSSWALKS_DIR / "xwalk_area_node_proposed.csv")
    node_discrepancy = xwalk_area_node[
        (xwalk_area_node["proposed_node_id"] == "")
        & xwalk_area_node["note"].str.contains("EA's taxonomy is finer", na=False)
    ]
    log(
        f"xwalk_area_node_proposed.csv node discrepancy (EA finer taxonomy than plan 4.3): "
        f"{len(node_discrepancy)} area(s), e.g. {node_discrepancy['area_name'].tolist()[:5]}"
    )

    liquefaction_rows = workbook_reader.read_project_capacity(
        WORKBOOK_ROOT / "202608_LNG_liquefaction_projects.xlsx",
        workbook_reader.WORKBOOK_SPECS[0],
    )
    regas_rows = workbook_reader.read_project_capacity(
        WORKBOOK_ROOT / "202608_LNG_regas_projects.xlsx",
        workbook_reader.WORKBOOK_SPECS[1],
    )
    all_project_rows = liquefaction_rows + regas_rows

    # ---- trap 6: workbook 'ISO 2-letter code' vs alias resolution of 'Country' ----
    trap6_conflicts = find_workbook_iso2_conflicts(all_project_rows, applied_crosswalk)
    if trap6_conflicts:
        log(f"Trap 6 workbook ISO2 conflicts found and reported, not resolved: {trap6_conflicts}")
    else:
        log("Trap 6: no workbook ISO2 / alias-resolution conflicts found")

    xwalk_project_node = node_master.build_xwalk_project_node_proposed(
        all_project_rows, applied_crosswalk, split_country_codes
    )
    xwalk_project_node = node_master.resolve_node_id_for_single_node_countries(
        xwalk_project_node, dim_country
    )
    xwalk_project_node.to_csv(CROSSWALKS_DIR / "xwalk_project_node_proposed.csv", index=False)
    log(
        f"Wrote crosswalks/xwalk_project_node_proposed.csv ({len(xwalk_project_node)} project rows)"
    )

    supply_and_demand_nodes = pd.concat(
        [supply_node, demand_node], ignore_index=True
    ).drop_duplicates(subset="node_id")
    aggregation_report = node_master.check_node_country_capacity_aggregation(
        xwalk_project_node, supply_and_demand_nodes
    )
    log(
        f"4.8 check 5 (node-to-country capacity aggregation): PASS for "
        f"{len(aggregation_report['countries_proven'])} single-node countries; "
        f"SKIPPED for split countries {aggregation_report['countries_skipped_split']} "
        f"pending xwalk_project_node sign-off "
        f"({aggregation_report['skipped_capacity_share']:.1%} of total capacity untested)"
    )

    # ---- 2.7 dim_port_candidate.csv ---------------------------------------
    ports_gdf = gpd.read_file(PORTS_SHP)
    port_gazetteer = port_candidate.load_port_gazetteer_with_country(ports_gdf, dissolved)

    node_by_country = dim_country.loc[
        ~dim_country["country_iso2"].isin(split_country_codes),
        ["country_iso2", "country_name_slug"],
    ].rename(columns={"country_name_slug": "node_id"})

    port_role_rows = [
        {
            "source_system": r["source_system"],
            "project": r["project"],
            "country_raw": r["country_raw"],
        }
        for r in all_project_rows
    ]
    dim_port_candidate = port_candidate.build_dim_port_candidate(
        port_role_rows,
        PORT_ROLE_BY_SOURCE_SYSTEM,
        applied_crosswalk,
        node_by_country,
        port_gazetteer,
    )
    dim_port_candidate.to_csv(CROSSWALKS_DIR / "dim_port_candidate.csv", index=False)
    geo_checks.session2_check_port_candidate_confidence(dim_port_candidate)
    log("2.9 (port candidate confidence/coordinate consistency): PASS")

    n_load = (dim_port_candidate["port_role"] == "load").sum()
    n_discharge = (dim_port_candidate["port_role"] == "discharge").sum()
    n_exact = (dim_port_candidate["method"] == "exact_name").sum()
    log(
        f"Wrote crosswalks/dim_port_candidate.csv: {n_load} load rows, {n_discharge} discharge "
        f"rows, {n_exact} exact_name matches ({n_exact / len(dim_port_candidate):.1%} of "
        f"{len(dim_port_candidate)}). Checks 6 and 7 SKIPPED: reason gate B (port coordinate "
        f"sign off) is not closed, so no reviewed coordinate set exists yet."
    )

    # ---- 4.8 check 10: no ZZ anywhere in actually-classified output -------
    # dim_country itself is excluded: it is the code registry, and ZZ's own
    # definitional row ("unknown, error trapping only") belongs there by
    # design (build plan 4.4). The check is about ZZ appearing as a value
    # some raw string actually got classified into, which is a bug.
    geo_checks.session2_check_10_no_zz(
        {
            "applied_crosswalk": applied_crosswalk,
            "dim_supply_node": supply_node,
            "dim_demand_node": demand_node,
            "dim_country_adjacency": applied_adjacency,
            "dim_port_candidate": dim_port_candidate,
        },
        {
            "applied_crosswalk": ["country_iso2"],
            "dim_supply_node": ["country_iso2", "node_id"],
            "dim_demand_node": ["country_iso2", "node_id"],
            "dim_country_adjacency": ["country_iso2_a", "country_iso2_b"],
            "dim_port_candidate": ["country_iso2"],
        },
    )
    log("4.8 check 10 (no ZZ in any classified output): PASS")

    # ---- 4.8 check 11: snapshot hashes match manifest -----------------------
    geo_checks.session2_check_11_snapshot_hashes_match_manifest(
        admin0_manifest_data["files"], ADMIN0_MANIFEST.parent
    )
    log("4.8 check 11 (snapshot hash matches manifest): PASS")

    # ---- 2.8 DuckDB store ---------------------------------------------------
    con = duckdb_store.create_store(DATA_OUTPUT / "lt_lng_flows.duckdb")
    try:
        duckdb_store.load_dim_country(con, dim_country)
        duckdb_store.load_dim_country_adjacency(con, applied_adjacency)
        duckdb_store.load_dim_supply_node(con, supply_node)
        duckdb_store.load_dim_demand_node(con, demand_node)
        duckdb_store.load_xwalk_country_alias(con, applied_crosswalk)
        duckdb_store.assert_foreign_key_enforced(con)
        log(
            "2.8 DuckDB store: dim_country, dim_country_adjacency, dim_supply_node, "
            "dim_demand_node, xwalk_country_alias loaded with PK/FK; unmapped-code "
            "insert correctly raised ConstraintException"
        )
    finally:
        con.close()

    write_manifest(
        DATA_INTERIM / "session_02_geo_manifest.json",
        {
            "source_directory": "data/geo",
            "files": {
                "dim_country.parquet": file_fact(DATA_GEO / "dim_country.parquet"),
                "geo_country_geometry.parquet": file_fact(
                    DATA_GEO / "geo_country_geometry.parquet"
                ),
                "dim_country_adjacency.parquet": file_fact(
                    DATA_GEO / "dim_country_adjacency.parquet"
                ),
                "dim_supply_node.parquet": file_fact(DATA_GEO / "dim_supply_node.parquet"),
                "dim_demand_node.parquet": file_fact(DATA_GEO / "dim_demand_node.parquet"),
            },
        },
    )
    log("Wrote data/interim/session_02_geo_manifest.json")

    write_report(report_lines, dim_country, dim_port_candidate, n_exact, len(dim_port_candidate))
    log("Wrote docs/session_02_geo_master.md")

    print("\nbuild_session2: PASS")


def find_workbook_iso2_conflicts(
    project_rows: list[dict], applied_crosswalk: pd.DataFrame
) -> list[dict]:
    """Build plan 4.5 trap 6: where the workbook's own 'ISO 2-letter code'
    for a project row and the alias resolution of that same row's 'Country'
    string disagree, report it, do not resolve it in favour of either side.

    ``project_rows`` (from ``workbook_reader.read_project_capacity``) pairs
    ``country_raw`` and ``iso2_raw`` from the same sheet row, which
    ``raw_country_strings.parquet`` cannot do -- it is deduplicated raw
    values with no row alignment between columns.
    """
    xwalk_by_system = {
        source_system: group.set_index("raw_value")["country_iso2"]
        for source_system, group in applied_crosswalk.groupby("source_system")
    }
    conflicts = []
    for record in project_rows:
        xwalk = xwalk_by_system.get(record["source_system"])
        if xwalk is None or record["country_raw"] not in xwalk.index:
            continue
        resolved_from_name = xwalk.loc[record["country_raw"]]
        iso2_raw_normalised = str(record["iso2_raw"]).strip().upper()
        if resolved_from_name != iso2_raw_normalised:
            conflicts.append(
                {
                    "source_system": record["source_system"],
                    "project": record["project"],
                    "country_raw": record["country_raw"],
                    "resolved_from_country_name": resolved_from_name,
                    "workbook_iso2_column": iso2_raw_normalised,
                }
            )
    return conflicts


def write_report(
    log_lines: list[str],
    dim_country: pd.DataFrame,
    dim_port_candidate: pd.DataFrame,
    n_exact: int,
    n_total: int,
) -> None:
    lines = [
        "# Session 2: geo master",
        "",
        "Deliverable for session 2 of `docs/sessions_02_03_build_plan.md` "
        "section 2, plan section 4 in full.",
        "",
        "## Build log",
        "",
        *[f"- {line}" for line in log_lines],
        "",
        "## Coverage by source system",
        "",
    ]
    coverage = dim_country.groupby("role_lng")["country_iso2"].count()
    lines.append("role_lng counts: " + ", ".join(f"{k}={v}" for k, v in coverage.items()))
    coverage_pipe = dim_country.groupby("role_pipe")["country_iso2"].count()
    lines.append("role_pipe counts: " + ", ".join(f"{k}={v}" for k, v in coverage_pipe.items()))
    lines.append("")
    lines.append(
        f"Port candidate exact-match rate: {n_exact}/{n_total} "
        f"({n_exact / n_total:.1%}), gazetteer source `natural_earth_10m_ports` "
        f"(World Port Index pull failed with HTTP 403; see "
        f"data/geo/raw/ports/port_gazetteer_manifest.json)."
    )
    lines.append("")
    lines.append("## Skipped checks")
    lines.append("")
    lines.append(
        "- 4.8 check 6 (every node has a port with a valid coordinate near the "
        "coastline): SKIPPED. Reason: gate B (port coordinate sign off, "
        "sessions_02_03_build_plan.md section 0) is not closed."
    )
    lines.append(
        "- 4.8 check 7 (fact_route_distance has no nulls, symmetric routings agree): "
        "SKIPPED. Reason: out of scope for session 2 (needs port coordinates); "
        "fact_route_distance is not built this session."
    )
    lines.append("")
    lines.append("## Known open items handed to session 3 or to sign-off")
    lines.append("")
    lines.append(
        "Gates C, D and E are recorded in full in `docs/sessions_02_03_build_plan.md` "
        "section 0, alongside gates A and B, not only here: that file is what session 3 "
        "reads before starting, and this report is regenerated (overwritten) on every "
        "`build_session2.py` run, so it is not the durable record."
    )
    lines.append(
        "- **Gate C.** Gibraltar (GI) is a real regas importer per the pinned workbook, "
        "but has no polygon in the pinned Natural Earth Admin 0 Countries 1:50m snapshot "
        "(absorbed into Spain's outline at that resolution); 4.8 check 4 fails for it. "
        "Not resolved this run."
    )
    lines.append(
        "- **Gate D.** Kosovo (Natural Earth `ISO_A2_EH='XK'`) has geometry but no "
        "dim_country row (not in the pinned ISO 3166-1 snapshot; plan 4.4 reserves XK for "
        "it without formally adding it). Excluded from dim_country_adjacency rather than "
        "given an invented classification. Not resolved this run."
    )
    lines.append(
        "- **Gate E.** `crosswalks/xwalk_project_node_proposed.csv` leaves every project "
        "in the four split countries (US, Canada, Russia, Australia; 31.6% of total "
        "capacity) unresolved: no sub-national field exists in the pinned workbooks to "
        "assign a project to us_gulf vs us_east, etc. Not resolved this run."
    )
    lines.append(
        "- `role_pipe` classifies a country seen as both GTF Exit and Entry as "
        "`both`, not `transit`: no flow-direction or volume data is pulled this "
        "session to distinguish the two. Revisit once session 3 pulls series data."
    )
    (DOCS_DIR / "session_02_geo_master.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
