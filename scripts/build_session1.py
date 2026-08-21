"""
build_session1.py
-------------------
Session 1: pinned raw inputs and the country key (build plan section 4).
Reads only ``data/raw``, no network call of any kind. Produces the eleven
deliverables of section 4, running the thirteen 4.7 checks as each one lands,
and writes ``docs/session_01_country_key.md``.

Run with the ``lt_lng_flows`` conda environment active:

    python scripts/build_session1.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.geo.area_node_proposal import (  # noqa: E402
    build_area_node_proposal,
    load_area_node_candidates,
    load_valid_node_ids,
)
from lt_lng_flows.geo.country_master import (  # noqa: E402
    build_alias_crosswalk_proposed,
    build_dim_country,
    load_pseudo_codes,
)
from lt_lng_flows.ingest import (  # noqa: E402
    ea_cargo_tracking,
    ea_dataset_catalogue,
    workbook_reader,
)
from lt_lng_flows.ingest.provenance import file_fact, write_manifest  # noqa: E402
from lt_lng_flows.validate import geo_checks  # noqa: E402

CONFIG_DIR = ROOT / "config"
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_GEO = ROOT / "data" / "geo"
CROSSWALKS_DIR = ROOT / "crosswalks"
DOCS_DIR = ROOT / "docs"

WORKBOOK_ROOT = DATA_RAW / "workbooks" / "202608"
IEA_GTF_PATH = DATA_RAW / "iea_gtf" / "Export_GTF_IEA_202606.xlsx"
EA_API_DIR = DATA_RAW / "ea_api" / "202608"
EA_API_MAPPINGS_PATH = EA_API_DIR / "ea_api_mappings.txt"
EA_CT_AREAS_PATH = EA_API_DIR / "ea_ct_areas_metadata.txt"
EA_CT_PORTS_PATH = EA_API_DIR / "ea_ct_country_ports.txt"

ISO_CSV_PATH = DATA_GEO / "raw" / "iso3166_1_countries.csv"
PSEUDO_CODES_CONFIG = CONFIG_DIR / "pseudo_country_codes.yaml"
LNG_NODES_CONFIG = CONFIG_DIR / "lng_nodes.yaml"
AREA_NODE_CANDIDATES_CONFIG = CONFIG_DIR / "area_node_candidates.yaml"
KNOWN_NAME_VARIANT_NOTES_CONFIG = CONFIG_DIR / "known_name_variant_notes.yaml"
SESSION_CONSTANTS_PATH = CONFIG_DIR / "session_01_constants.yaml"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    constants = load_yaml(SESSION_CONSTANTS_PATH)
    pseudo_cfg = load_pseudo_codes(PSEUDO_CODES_CONFIG)
    pseudo_codes = pseudo_cfg["pseudo_codes"]
    pseudo_code_aliases = pseudo_cfg["pseudo_code_aliases"]
    known_name_variant_notes = load_yaml(KNOWN_NAME_VARIANT_NOTES_CONFIG)[
        "known_name_variant_notes"
    ]

    # ---- pinned ISO 3166-1 source manifest (build plan 4.3) --------------
    # No offline ISO package is installed and no network call is permitted
    # this session (see the deviation note in the report). The pinned
    # snapshot is an authored static CSV; this manifest is its provenance.
    iso_df_preview = pd.read_csv(ISO_CSV_PATH, dtype=str, keep_default_na=False, na_values=[])
    write_manifest(
        DATA_GEO / "iso3166_1_manifest.json",
        {
            "source_directory": "data/geo/raw",
            "note": (
                "Authored static snapshot of the ISO 3166-1 alpha-2 list "
                "(country_iso2, country_name, region), not pulled from a live "
                "service: no offline ISO package (pycountry, babel, iso3166, "
                "country_converter) is installed in the lt_lng_flows "
                "environment, and session 1 permits no network call. Recommend "
                "human sanity check before session 2 sign-off."
            ),
            "files": {
                "iso3166_1_countries.csv": {
                    **file_fact(ISO_CSV_PATH),
                    "row_count": len(iso_df_preview),
                }
            },
        },
    )
    print("Wrote data/geo/iso3166_1_manifest.json")

    # ---- 4.1 workbook readers + manifests -------------------------------
    print("Reading the three LNG workbooks...")
    per_workbook = workbook_reader.read_all_workbooks(WORKBOOK_ROOT)
    print(f"Reading IEA GTF export from {IEA_GTF_PATH.name}...")
    iea_gtf_result = workbook_reader.read_iea_gtf(IEA_GTF_PATH)

    all_country_records: list[dict] = []
    workbook_manifest_files = {}
    for spec in workbook_reader.WORKBOOK_SPECS:
        result = per_workbook[spec.filename]
        all_country_records.extend(result["country_records"])
        path = WORKBOOK_ROOT / spec.filename
        workbook_manifest_files[spec.filename] = {
            **file_fact(path),
            "sheets": result["sheets"],
        }
    all_country_records.extend(iea_gtf_result["country_records"])

    write_manifest(
        DATA_INTERIM / "workbooks_202608_manifest.json",
        {
            "source_directory": "data/raw/workbooks/202608",
            "files": workbook_manifest_files,
        },
    )
    print("Wrote data/interim/workbooks_202608_manifest.json")

    # ---- 4.5 EA dataset catalogue ----------------------------------------
    print("Reading ea_api_mappings.txt...")
    catalogue, dedup_report = ea_dataset_catalogue.read_ea_dataset_catalogue(EA_API_MAPPINGS_PATH)
    geo_checks.check_ea_dataset_catalogue_counts(catalogue, dedup_report, constants)
    print("check 7 (ea_dataset_catalogue counts): PASS")
    catalogue.to_parquet(DATA_INTERIM / "ea_dataset_catalogue.parquet", index=False)
    print("Wrote data/interim/ea_dataset_catalogue.parquet")

    # Confirm programmatically, rather than assuming, that the pinned mappings
    # snapshot has no discrete country field (see the report note below).
    keys_seen: set[str] = set()
    import json as _json

    with EA_API_MAPPINGS_PATH.open(encoding="utf-8") as f:
        _raw_mappings = _json.load(f)
    for _mappings in _raw_mappings.values():
        for _m in _mappings:
            keys_seen.update(_m.keys())

    # ---- 4.6 EA cargo tracking taxonomy ----------------------------------
    print("Reading ea_ct_areas_metadata.txt...")
    ea_ct_area, ea_ct_area_country = ea_cargo_tracking.read_ea_ct_areas(EA_CT_AREAS_PATH)
    print("Reading ea_ct_country_ports.txt...")
    ea_ct_country_port, country_port_report = ea_cargo_tracking.read_ea_ct_country_ports(
        EA_CT_PORTS_PATH
    )

    ct_cfg = constants["ea_cargo_tracking"]
    if len(ea_ct_area) != ct_cfg["expected_area_count"]:
        raise AssertionError(
            f"ea_ct_area: expected {ct_cfg['expected_area_count']} areas, found {len(ea_ct_area)}"
        )
    distinct_area_country_codes = ea_ct_area_country["country_iso2"].nunique()
    if distinct_area_country_codes != ct_cfg["expected_distinct_country_codes"]:
        raise AssertionError(
            f"ea_ct_area_country: expected {ct_cfg['expected_distinct_country_codes']} distinct "
            f"country codes, found {distinct_area_country_codes}"
        )
    distinct_area_port_ids = ea_ct_area_country["port_id"].nunique()
    if distinct_area_port_ids != ct_cfg["expected_distinct_port_ids_areas_file"]:
        raise AssertionError(
            f"ea_ct_area_country: expected {ct_cfg['expected_distinct_port_ids_areas_file']} "
            f"distinct port ids, found {distinct_area_port_ids}"
        )
    if country_port_report["distinct_country_codes"] != ct_cfg["expected_distinct_country_codes"]:
        raise AssertionError(
            f"ea_ct_country_port: expected {ct_cfg['expected_distinct_country_codes']} distinct "
            f"country codes, found {country_port_report['distinct_country_codes']}"
        )
    if country_port_report["raw_port_list_entries"] != ct_cfg["expected_port_entries_ports_file"]:
        raise AssertionError(
            f"ea_ct_country_port: expected {ct_cfg['expected_port_entries_ports_file']} raw port "
            f"entries, found {country_port_report['raw_port_list_entries']}"
        )
    if country_port_report["sub_country_objects"] != ct_cfg["expected_sub_country_objects"]:
        raise AssertionError(
            f"ea_ct_country_port: expected {ct_cfg['expected_sub_country_objects']} sub-country "
            f"objects, found {country_port_report['sub_country_objects']}"
        )
    print("ea_ct magnitude assertions: PASS")

    for _, row in ea_ct_area_country.iterrows():
        all_country_records.append(
            {
                "source_system": "ea_ct_area_country",
                "column_name": "country_iso2",
                "raw_value": row["country_iso2"],
                "sheet_name": None,
            }
        )
    for _, row in ea_ct_country_port.iterrows():
        all_country_records.append(
            {
                "source_system": "ea_ct_country_port",
                "column_name": "country_iso2",
                "raw_value": row["country_iso2"],
                "sheet_name": None,
            }
        )

    ea_ct_area.to_parquet(DATA_INTERIM / "ea_ct_area.parquet", index=False)
    ea_ct_area_country.to_parquet(DATA_INTERIM / "ea_ct_area_country.parquet", index=False)
    ea_ct_country_port.to_parquet(DATA_INTERIM / "ea_ct_country_port.parquet", index=False)
    print("Wrote ea_ct_area.parquet, ea_ct_area_country.parquet, ea_ct_country_port.parquet")

    # ea_api manifest, covering all three files in data/raw/ea_api/202608
    write_manifest(
        DATA_INTERIM / "ea_api_202608_manifest.json",
        {
            "source_directory": "data/raw/ea_api/202608",
            "files": {
                "ea_api_mappings.txt": {
                    **file_fact(EA_API_MAPPINGS_PATH),
                    "asserted_total_mappings": int(dedup_report["mapping_id"].nunique()),
                    "asserted_total_references": int(dedup_report["raw_count"].sum()),
                    "asserted_total_distinct_ids": int(catalogue["dataset_id"].nunique()),
                },
                "ea_ct_areas_metadata.txt": {
                    **file_fact(EA_CT_AREAS_PATH),
                    "asserted_area_count": len(ea_ct_area),
                    "asserted_distinct_country_codes": distinct_area_country_codes,
                    "asserted_distinct_port_ids": distinct_area_port_ids,
                },
                "ea_ct_country_ports.txt": {
                    **file_fact(EA_CT_PORTS_PATH),
                    **country_port_report,
                },
            },
        },
    )
    print("Wrote data/interim/ea_api_202608_manifest.json")

    # ---- 4.2 raw_country_strings.parquet ---------------------------------
    records_df = pd.DataFrame(all_country_records)
    raw_country_strings = (
        records_df.groupby(["source_system", "column_name", "raw_value"], dropna=False)
        .agg(occurrence_count=("raw_value", "size"), first_seen_sheet=("sheet_name", "first"))
        .reset_index()
    )
    raw_country_strings.to_parquet(DATA_INTERIM / "raw_country_strings.parquet", index=False)
    print(
        f"Wrote data/interim/raw_country_strings.parquet ({len(raw_country_strings)} distinct rows)"
    )

    # ---- 4.3 dim_country ---------------------------------------------------
    dim_country = build_dim_country(ISO_CSV_PATH, PSEUDO_CODES_CONFIG)
    geo_checks.check_dim_country_pk_unique(dim_country)
    print("check 1 (dim_country pk unique/non null): PASS")
    geo_checks.check_pseudo_codes_present(dim_country, pseudo_codes)
    print("check 2 (pseudo codes present): PASS")
    dim_country.to_parquet(DATA_GEO / "dim_country.parquet", index=False)
    print(f"Wrote data/geo/dim_country.parquet ({len(dim_country)} rows)")

    # ---- 4.4 xwalk_country_alias_proposed.csv ------------------------------
    crosswalk = build_alias_crosswalk_proposed(
        raw_country_strings, dim_country, pseudo_code_aliases, known_name_variant_notes
    )
    geo_checks.check_raw_strings_covered_exactly_once(raw_country_strings, crosswalk)
    print("check 3 (every raw pair covered exactly once): PASS")
    geo_checks.check_proposed_iso2_known(crosswalk, dim_country)
    print("check 4 (proposed_iso2 known to dim_country): PASS")
    geo_checks.check_no_zz_proposed(crosswalk)
    print("check 5 (no ZZ proposed): PASS")
    geo_checks.check_confidence_method_consistency(crosswalk)
    print("check 6 (confidence/method consistency): PASS")
    CROSSWALKS_DIR.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(CROSSWALKS_DIR / "xwalk_country_alias_proposed.csv", index=False)
    print(f"Wrote crosswalks/xwalk_country_alias_proposed.csv ({len(crosswalk)} rows)")

    # ---- 4.6b xwalk_area_node_proposed.csv ---------------------------------
    valid_node_ids = load_valid_node_ids(LNG_NODES_CONFIG)
    candidates_by_area_name = load_area_node_candidates(AREA_NODE_CANDIDATES_CONFIG)
    area_node_proposal = build_area_node_proposal(
        ea_ct_area, ea_ct_area_country, candidates_by_area_name, valid_node_ids
    )
    geo_checks.check_ea_ct_area_shape(ea_ct_area, constants)
    print("check 9 (ea_ct_area shape): PASS")
    geo_checks.check_ea_ct_country_codes_valid(ea_ct_area_country, ea_ct_country_port, dim_country)
    print("check 10 (ea_ct country codes valid): PASS")
    geo_checks.check_ea_ct_uniqueness_and_subcountry(
        ea_ct_area_country, ea_ct_country_port, country_port_report, constants
    )
    print("check 11 (ea_ct uniqueness + sub-country rows): PASS")
    geo_checks.check_area_node_proposal(area_node_proposal, ea_ct_area, valid_node_ids)
    print("check 12 (area-node proposal coverage/validity): PASS")
    area_node_proposal.to_csv(CROSSWALKS_DIR / "xwalk_area_node_proposed.csv", index=False)
    print(f"Wrote crosswalks/xwalk_area_node_proposed.csv ({len(area_node_proposal)} rows)")

    # ---- check 8: ascii lower snake case names -----------------------------
    names_to_check: dict[str, str] = {}
    for col in raw_country_strings.columns:
        names_to_check[f"raw_country_strings.{col}"] = col
    for col in dim_country.columns:
        names_to_check[f"dim_country.{col}"] = col
    for col in crosswalk.columns:
        names_to_check[f"xwalk_country_alias_proposed.{col}"] = col
    for col in area_node_proposal.columns:
        names_to_check[f"xwalk_area_node_proposed.{col}"] = col
    for col in catalogue.columns:
        names_to_check[f"ea_dataset_catalogue.{col}"] = col
    for col in ea_ct_area.columns:
        names_to_check[f"ea_ct_area.{col}"] = col
    for col in ea_ct_area_country.columns:
        names_to_check[f"ea_ct_area_country.{col}"] = col
    for col in ea_ct_country_port.columns:
        names_to_check[f"ea_ct_country_port.{col}"] = col
    for path in (
        DATA_INTERIM / "workbooks_202608_manifest.json",
        DATA_INTERIM / "ea_api_202608_manifest.json",
        DATA_INTERIM / "raw_country_strings.parquet",
        DATA_INTERIM / "ea_dataset_catalogue.parquet",
        DATA_INTERIM / "ea_ct_area.parquet",
        DATA_INTERIM / "ea_ct_area_country.parquet",
        DATA_INTERIM / "ea_ct_country_port.parquet",
        DATA_GEO / "dim_country.parquet",
        CROSSWALKS_DIR / "xwalk_country_alias_proposed.csv",
        CROSSWALKS_DIR / "xwalk_area_node_proposed.csv",
    ):
        names_to_check[f"filename:{path.name}"] = path.name
    geo_checks.check_ascii_lower_snake_case(names_to_check)
    print("check 8 (ascii lower snake case): PASS")

    # ---- check 13: data/interim provenance ---------------------------------
    expected_parquet_names = {
        "raw_country_strings.parquet",
        "ea_dataset_catalogue.parquet",
        "ea_ct_area.parquet",
        "ea_ct_area_country.parquet",
        "ea_ct_country_port.parquet",
    }
    geo_checks.check_data_interim_provenance(DATA_INTERIM, ROOT, expected_parquet_names)
    print("check 13 (data/interim provenance tracked/ignored correctly): PASS")

    # ---- 4.8 session note ---------------------------------------------------
    unresolved = crosswalk[crosswalk["method"] == "unresolved"]
    high = crosswalk[crosswalk["confidence"] == "high"]
    by_source_total = crosswalk.groupby("source_system").size().sort_index()
    by_source_unresolved = (
        unresolved.groupby("source_system").size().reindex(by_source_total.index, fill_value=0)
    )
    by_source_high = (
        high.groupby("source_system").size().reindex(by_source_total.index, fill_value=0)
    )

    lines = []
    lines.append("# Session 1: pinned raw inputs and the country key\n")
    lines.append(
        "Deliverable for build plan section 4. Built by `scripts/build_session1.py` "
        "from `data/raw` only; no network call of any kind.\n"
    )
    lines.append("## What was read\n")
    for spec in workbook_reader.WORKBOOK_SPECS:
        info = per_workbook[spec.filename]["sheets"][spec.data_sheet.sheet_name]
        lines.append(
            f"- `{spec.filename}`, sheet `{spec.data_sheet.sheet_name}`: "
            f"{info['row_count']} data rows, header at row {info['header_row']}, "
            f"{len(info['column_names'])} columns."
        )
    gtf_info = iea_gtf_result["sheets"][workbook_reader.IEA_GTF_DATA_SHEET]
    lines.append(
        f"- `Export_GTF_IEA_202606.xlsx`, sheet `{workbook_reader.IEA_GTF_DATA_SHEET}`: "
        f"{gtf_info['row_count']} data rows, header at row {gtf_info['header_row']}, "
        f"{len(gtf_info['column_names'])} columns. The `NOTES` sheet was read for the "
        f"manifest but excluded from country-string extraction: its `Country` column "
        f"holds annotation labels (`General`, `None`, and slash-joined pairs such as "
        f"`Austria / Germany`), not atomic country values."
    )
    lines.append(
        f"- `ea_api_mappings.txt`: {int(dedup_report['mapping_id'].nunique())} mappings, "
        f"{int(dedup_report['raw_count'].sum())} dataset_id references, "
        f"{int(catalogue['dataset_id'].nunique())} distinct dataset ids."
    )
    lines.append(
        f"- `ea_ct_areas_metadata.txt`: {len(ea_ct_area)} areas, "
        f"{distinct_area_country_codes} distinct country codes, "
        f"{distinct_area_port_ids} distinct port ids."
    )
    lines.append(
        f"- `ea_ct_country_ports.txt`: {country_port_report['distinct_country_codes']} "
        f"distinct country codes, {country_port_report['raw_port_list_entries']} raw port "
        f"list entries, {country_port_report['sub_country_objects']} sub-country objects, "
        f"{country_port_report['exploded_row_count']} exploded (country_iso2, port_id) rows."
    )

    lines.append("\n## Per-mapping duplication (build plan 4.5)\n")
    lines.append("| mapping_name | raw | distinct |")
    lines.append("|---|---|---|")
    for mapping_name, expected in constants["ea_dataset_catalogue"][
        "expected_per_mapping_raw_distinct"
    ].items():
        row = dedup_report[dedup_report["mapping_name"] == mapping_name].iloc[0]
        lines.append(f"| {mapping_name} | {int(row['raw_count'])} | {int(row['distinct_count'])} |")

    lines.append("\n## Country string resolution, by source_system\n")
    lines.append("| source_system | distinct raw strings | high confidence | unresolved |")
    lines.append("|---|---|---|---|")
    for source in by_source_total.index:
        lines.append(
            f"| {source} | {by_source_total[source]} | {by_source_high[source]} | "
            f"{by_source_unresolved[source]} |"
        )
    lines.append(
        "\n`ea_mappings_catalogue` is not in this table: `ea_api_mappings.txt` carries "
        f"only the keys `{sorted(keys_seen)}` on every mapping record "
        f"(checked programmatically) — no discrete country field. The plan names it as "
        "a source_system that could carry country-like strings, but the pinned snapshot "
        "does not have one; the only country signal in this file is incidental text "
        "inside `mapping_name` (e.g. `US gas balances`), and pulling a country out of "
        "free text would be a substring match, which build plan 4.4 forbids. No rows "
        "are contributed from this source, and no code was written to guess one.\n"
    )

    lines.append(
        f"\nTotal distinct (source_system, raw_value) pairs: {len(crosswalk)}. "
        f"High confidence: {len(high)}. Unresolved: {len(unresolved)}.\n"
    )

    lines.append("\n## Area to node proposal (build plan 4.6b)\n")
    proposed = area_node_proposal[area_node_proposal["proposed_node_id"] != ""]
    lines.append(
        f"{len(proposed)} of {len(area_node_proposal)} areas propose a node_id: "
        + ", ".join(f"{r.area_name} -> {r.proposed_node_id}" for r in proposed.itertuples())
        + "."
    )
    lines.append(
        "\nEvery Russia-related area (`Russian Pacific`, `Baltic Sea Upper`, `Baltic Sea "
        "Low`, `Arctic Ocean & Barents Sea`) failed to resolve: the two Baltic areas and "
        "the Arctic area each span several countries besides Russia (for example `Baltic "
        "Sea Low` is DE, DK, LT, LV, PL, RU, SE), so none is a single-country match for "
        "`ru_baltic` or `ru_arctic_other`. `Russian Pacific` is single-country (RU) but "
        "the name does not correspond one-to-one with either `ru_sakhalin` or "
        "`ru_arctic_other` without inference, so it is also left unresolved. `Australia "
        "South` is single-country (AU) but the plan names no `au_south` node, so it "
        "documents a genuine finer-taxonomy discrepancy rather than resolving. `US "
        "Atlantic Coast` and `US North Pacific` are each two countries (adding Bermuda "
        "and Canada respectively), so of the five US-named areas only three resolve "
        "(`Alaska`, `US Gulf`, `US West Coast`), leaving the plan's `us_east` node "
        "without a clean area match — the five-areas-against-four-nodes discrepancy the "
        "build plan anticipated.\n"
    )

    lines.append("\n## dim_port gap (build plan 4.6c)\n")
    lines.append(
        "Neither `ea_ct_areas_metadata.txt` nor `ea_ct_country_ports.txt` carries a port "
        "name, a coordinate, or any attribute beyond an integer `port_id` and a country "
        "grouping. `dim_port` in forecast plan section 4.3 needs a representative load "
        "and discharge port per node with coordinates, so it cannot be built from these "
        "two files. The missing input is a port metadata endpoint giving name and "
        "position per `port_id`.\n"
    )

    lines.append("\n## Deviations from the letter of the plan, and why\n")
    lines.append(
        "- **Pinned ISO 3166-1 source.** Build plan 4.3 requires real countries "
        '"from a pinned ISO 3166-1 source recorded in a manifest, not from a package '
        'that reaches the network at import." No offline ISO package (pycountry, '
        "babel, iso3166, country_converter) is installed in the `lt_lng_flows` "
        "environment, and the hard constraint here is no network call of any kind. "
        "`data/geo/raw/iso3166_1_countries.csv` was therefore authored as a static "
        "snapshot from the standard ISO 3166-1 alpha-2 list (249 codes, English short "
        "names, five-continent `region` grouping), not pulled from a live source. This "
        "is recorded in `data/geo/iso3166_1_manifest.json` with its own note. This is "
        "worth a human sanity check before session 2 sign-off: it was authored from "
        "static reference knowledge, not fetched and hashed from an authoritative URL "
        "the way forecast plan 4.6 describes for the eventual geo master.\n"
    )
    lines.append(
        "- **Manifests scoped as named in 4.1.** `workbooks_202608_manifest.json` "
        "covers only the three LNG workbooks under `data/raw/workbooks/202608`; "
        "`Export_GTF_IEA_202606.xlsx` has no manifest of its own, matching the two "
        "manifests 4.1 names explicitly. Its country strings are still in "
        "`raw_country_strings.parquet` as source_system `iea_gtf`.\n"
    )
    lines.append(
        "- **Area-to-node proposal uses a curated candidate table, not name text "
        "matching.** The plan's own worked example (`US Gulf` to `us_gulf`) only works "
        "as literal text for a minority of the fourteen named areas (`Alaska` does not "
        "literally contain `us_alaska`; `Canada Atlantic Coast` does not literally "
        "contain `ca_east`). `config/area_node_candidates.yaml` hand-lists the "
        "fourteen area names from build plan 4.6b against their candidate node_id, "
        "sourced directly from the plan text. The build still refuses to accept a "
        "candidate unless the area's actual member-country list is exactly the "
        "expected single country, and unless the candidate node_id is one of the ids "
        "in `config/lng_nodes.yaml` — so a wrong or finer-grained candidate (`au_south`) "
        "is caught and left unresolved rather than accepted on the strength of the "
        "table alone.\n"
    )
    lines.append(
        "- **`.gitignore`.** The four lines from build plan 4.6d were not all present "
        "(`!data/**/.gitkeep` existed but `!**/.gitkeep` and `!**/*_manifest.json` did "
        "not). Both missing lines were added; nothing else in the file was changed. "
        "Note for the record, not something this session changed: the file also "
        "contains a bare `docs/` rule that gitignores the entire `docs/` directory, "
        "including this note and the two plan documents themselves — none of `docs/` "
        "is currently tracked. That predates this session and is outside the four "
        "lines this session was told to add; flagging it rather than touching it.\n"
    )

    lines.append("\n## Deferred to session 2 (not one of the eleven deliverables here)\n")
    lines.append(
        "Forecast plan 4.5 trap 6: cross-checking, row by row in the two project "
        "workbooks, whether the `ISO 2-letter code` column and the alias resolution "
        "of the `Country` column agree. This session resolves `Country` and `ISO "
        "2-letter code` independently as two columns of the same source_system, which "
        "is enough to build the crosswalk proposal, but does not join them back "
        "row-by-row to flag a disagreement. That join belongs with the applied "
        "crosswalk in session 2, once `xwalk_country_alias.csv` is signed off.\n"
    )

    lines.append("\n## Unresolved raw strings, by source_system\n")
    for source in sorted(unresolved["source_system"].unique()):
        subset = sorted(unresolved.loc[unresolved["source_system"] == source, "raw_value"].unique())
        lines.append(f"\n### {source} ({len(subset)} unresolved)\n")
        for value in subset:
            note = crosswalk.loc[
                (crosswalk["source_system"] == source) & (crosswalk["raw_value"] == value), "note"
            ].iloc[0]
            suffix = f" — {note}" if note else ""
            lines.append(f"- `{value}`{suffix}")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "session_01_country_key.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote docs/session_01_country_key.md")

    print("\nAll thirteen 4.7 checks passed.")
    print(f"Unresolved count (total): {len(unresolved)}")
    for source in by_source_total.index:
        print(f"  {source}: {by_source_unresolved[source]} unresolved of {by_source_total[source]}")


if __name__ == "__main__":
    main()
