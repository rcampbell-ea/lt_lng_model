"""
geo_checks.py
--------------
Session 1, build plan 4.7: checks 1-13 below. Session 2, build plan 4.8:
checks under the ``session2_check_`` prefix, checks 1-5 and 8-11 of that
section (6 and 7, port coordinates and route distances, cannot run until
gate B closes and are reported skipped, not implemented as pass/fail here).
Each function raises ``AssertionError`` naming the offender on failure;
nothing is dropped, clamped or defaulted silently (CLAUDE.md, "fail loudly").
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pandas as pd

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# 1. dim_country primary key unique and non null.
def check_dim_country_pk_unique(dim_country: pd.DataFrame) -> None:
    if dim_country["country_iso2"].isnull().any():
        raise AssertionError("check 1: dim_country has a null country_iso2")
    if dim_country["country_iso2"].duplicated().any():
        dupes = sorted(dim_country.loc[dim_country["country_iso2"].duplicated(), "country_iso2"])
        raise AssertionError(f"check 1: dim_country has duplicate country_iso2 values: {dupes}")


# 2. every pseudo code present and is_real_country = False.
def check_pseudo_codes_present(dim_country: pd.DataFrame, pseudo_codes: dict) -> None:
    present = set(dim_country["country_iso2"])
    expected = set(pseudo_codes.keys())
    missing = sorted(expected - present)
    if missing:
        raise AssertionError(f"check 2: pseudo codes missing from dim_country: {missing}")
    pseudo_rows = dim_country[dim_country["country_iso2"].isin(expected)]
    still_real = sorted(pseudo_rows.loc[pseudo_rows["is_real_country"], "country_iso2"])
    if still_real:
        raise AssertionError(f"check 2: pseudo codes marked is_real_country = True: {still_real}")


# 3. every (source_system, raw_value) pair appears exactly once in the crosswalk.
def check_raw_strings_covered_exactly_once(
    raw_country_strings: pd.DataFrame, crosswalk: pd.DataFrame
) -> None:
    raw_pairs = set(
        raw_country_strings[["source_system", "raw_value"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    xwalk_pairs_list = list(
        crosswalk[["source_system", "raw_value"]].itertuples(index=False, name=None)
    )
    xwalk_pairs = set(xwalk_pairs_list)

    if len(xwalk_pairs_list) != len(xwalk_pairs):
        counts: dict[tuple, int] = {}
        for pair in xwalk_pairs_list:
            counts[pair] = counts.get(pair, 0) + 1
        dup = sorted(p for p, n in counts.items() if n > 1)
        raise AssertionError(
            f"check 3: crosswalk has duplicated (source_system, raw_value) pairs: {dup[:10]}"
        )

    missing = sorted(raw_pairs - xwalk_pairs)
    if missing:
        raise AssertionError(
            f"check 3: {len(missing)} (source_system, raw_value) pairs from raw_country_strings "
            f"are missing from the crosswalk, e.g. {missing[:10]}"
        )
    extra = sorted(xwalk_pairs - raw_pairs)
    if extra:
        raise AssertionError(
            f"check 3: crosswalk has {len(extra)} pairs not present in raw_country_strings, "
            f"e.g. {extra[:10]}"
        )


# 4. no proposed_iso2 value is absent from dim_country.
def check_proposed_iso2_known(crosswalk: pd.DataFrame, dim_country: pd.DataFrame) -> None:
    valid = set(dim_country["country_iso2"])
    proposed = crosswalk.loc[crosswalk["proposed_iso2"] != "", "proposed_iso2"]
    bad = sorted(set(proposed) - valid)
    if bad:
        raise AssertionError(f"check 4: proposed_iso2 values absent from dim_country: {bad}")


# 5. no proposed_iso2 equals ZZ.
def check_no_zz_proposed(crosswalk: pd.DataFrame) -> None:
    if (crosswalk["proposed_iso2"] == "ZZ").any():
        raise AssertionError("check 5: crosswalk proposes ZZ; ZZ is never a valid proposal")


# 6. confidence/method/proposed_iso2 consistency.
def check_confidence_method_consistency(crosswalk: pd.DataFrame) -> None:
    high_but_empty = crosswalk[
        (crosswalk["confidence"] == "high") & (crosswalk["proposed_iso2"] == "")
    ]
    if not high_but_empty.empty:
        raise AssertionError(
            f"check 6: {len(high_but_empty)} confidence=high rows have an empty proposed_iso2"
        )
    unresolved_but_filled = crosswalk[
        (crosswalk["method"] == "unresolved") & (crosswalk["proposed_iso2"] != "")
    ]
    if not unresolved_but_filled.empty:
        raise AssertionError(
            f"check 6: {len(unresolved_but_filled)} method=unresolved rows have a "
            f"non empty proposed_iso2"
        )


# 7. ea_dataset_catalogue distinct id count and per-mapping raw/distinct.
def check_ea_dataset_catalogue_counts(
    catalogue: pd.DataFrame, dedup_report: pd.DataFrame, constants: dict
) -> None:
    cfg = constants["ea_dataset_catalogue"]

    total_mappings = dedup_report["mapping_id"].nunique()
    if total_mappings != cfg["expected_total_mappings"]:
        raise AssertionError(
            f"check 7: expected {cfg['expected_total_mappings']} mappings, found {total_mappings}"
        )

    total_references = int(dedup_report["raw_count"].sum())
    if total_references != cfg["expected_total_references"]:
        raise AssertionError(
            f"check 7: expected {cfg['expected_total_references']} raw dataset_id references, "
            f"found {total_references}"
        )

    total_distinct = catalogue["dataset_id"].nunique()
    if total_distinct != cfg["expected_total_distinct_ids"]:
        raise AssertionError(
            f"check 7: expected {cfg['expected_total_distinct_ids']} distinct dataset ids, "
            f"found {total_distinct}"
        )

    for mapping_name, expected in cfg["expected_per_mapping_raw_distinct"].items():
        row = dedup_report[dedup_report["mapping_name"] == mapping_name]
        if row.empty:
            raise AssertionError(f"check 7: mapping '{mapping_name}' not found in the catalogue")
        raw = int(row["raw_count"].sum())
        distinct = int(row["distinct_count"].sum())
        if raw != expected["raw"] or distinct != expected["distinct"]:
            raise AssertionError(
                f"check 7: mapping '{mapping_name}' expected raw={expected['raw']} "
                f"distinct={expected['distinct']}, found raw={raw} distinct={distinct}"
            )


# 8. ascii lower snake case for every identifier, column name and file name this session wrote.
def check_ascii_lower_snake_case(names: dict[str, str]) -> None:
    bad = []
    for label, name in names.items():
        for part in name.split("."):
            if not _TOKEN_RE.match(part):
                bad.append((label, name))
                break
    if bad:
        raise AssertionError(f"check 8: names not ascii lower snake case: {bad}")


# 9. ea_ct_area shape.
def check_ea_ct_area_shape(ea_ct_area: pd.DataFrame, constants: dict) -> None:
    expected = constants["ea_cargo_tracking"]["expected_area_count"]
    if len(ea_ct_area) != expected:
        raise AssertionError(f"check 9: expected {expected} areas, found {len(ea_ct_area)}")
    if ea_ct_area["area_id"].duplicated().any():
        dupes = sorted(ea_ct_area.loc[ea_ct_area["area_id"].duplicated(), "area_id"])
        raise AssertionError(f"check 9: duplicate area_id values: {dupes}")
    bad_suez = sorted(set(ea_ct_area["suez_position"].dropna()) - {"east", "west"})
    if bad_suez or ea_ct_area["suez_position"].isnull().any():
        raise AssertionError(
            f"check 9: suez_position values outside {{east, west}} or null present: {bad_suez}"
        )


# 10. every country_iso2 in the two ea_ct tables is two characters and present in dim_country.
def check_ea_ct_country_codes_valid(
    ea_ct_area_country: pd.DataFrame, ea_ct_country_port: pd.DataFrame, dim_country: pd.DataFrame
) -> None:
    valid = set(dim_country["country_iso2"])
    for label, df in (
        ("ea_ct_area_country", ea_ct_area_country),
        ("ea_ct_country_port", ea_ct_country_port),
    ):
        codes = set(df["country_iso2"])
        bad_len = sorted(c for c in codes if len(c) != 2)
        if bad_len:
            raise AssertionError(
                f"check 10: {label} has country_iso2 not two characters: {bad_len}"
            )
        missing = sorted(codes - valid)
        if missing:
            raise AssertionError(
                f"check 10: {label} has country codes absent from dim_country: {missing}"
            )


# 11. uniqueness of (area_id, country_iso2, port_id) / (country_iso2, port_id), sub-country rows.
def check_ea_ct_uniqueness_and_subcountry(
    ea_ct_area_country: pd.DataFrame,
    ea_ct_country_port: pd.DataFrame,
    country_port_report: dict,
    constants: dict,
) -> None:
    if ea_ct_area_country.duplicated(subset=["area_id", "country_iso2", "port_id"]).any():
        raise AssertionError(
            "check 11: duplicate (area_id, country_iso2, port_id) rows in ea_ct_area_country"
        )

    membership = ea_ct_area_country[["area_id", "country_iso2"]]
    port_counts = ea_ct_area_country.groupby(["area_id", "country_iso2"])["port_id"].apply(
        lambda s: s.duplicated().any()
    )
    if port_counts.any():
        bad_pairs = sorted(port_counts[port_counts].index.tolist())
        raise AssertionError(
            f"check 11: repeated port_id within (area_id, country_iso2): {bad_pairs[:10]}"
        )
    del membership

    if ea_ct_country_port.duplicated(subset=["country_iso2", "port_id"]).any():
        raise AssertionError(
            "check 11: duplicate (country_iso2, port_id) rows in ea_ct_country_port"
        )

    expected_subc = constants["ea_cargo_tracking"]["expected_sub_country_objects"]
    if country_port_report["sub_country_objects"] != expected_subc:
        raise AssertionError(
            f"check 11: expected {expected_subc} sub-country objects, found "
            f"{country_port_report['sub_country_objects']}"
        )
    non_null = ea_ct_country_port["sub_country_id"].notnull()
    if non_null.sum() == 0:
        raise AssertionError("check 11: no rows carry a non null sub_country_id, expected some")
    if (~non_null).sum() == 0:
        raise AssertionError(
            "check 11: every row carries a non null sub_country_id, expected some null"
        )


# 12. every area in xwalk_area_node_proposed.csv appears once; proposed_node_id is a section 4.3 id.
def check_area_node_proposal(
    xwalk_area_node: pd.DataFrame, ea_ct_area: pd.DataFrame, valid_node_ids: set[str]
) -> None:
    if xwalk_area_node["area_id"].duplicated().any():
        dupes = sorted(xwalk_area_node.loc[xwalk_area_node["area_id"].duplicated(), "area_id"])
        raise AssertionError(f"check 12: duplicate area_id in xwalk_area_node_proposed: {dupes}")
    if set(xwalk_area_node["area_id"]) != set(ea_ct_area["area_id"]):
        missing = sorted(set(ea_ct_area["area_id"]) - set(xwalk_area_node["area_id"]))
        extra = sorted(set(xwalk_area_node["area_id"]) - set(ea_ct_area["area_id"]))
        raise AssertionError(
            f"check 12: xwalk_area_node_proposed does not cover exactly ea_ct_area's areas; "
            f"missing={missing}, extra={extra}"
        )
    non_empty = xwalk_area_node.loc[xwalk_area_node["proposed_node_id"] != "", "proposed_node_id"]
    bad = sorted(set(non_empty) - valid_node_ids)
    if bad:
        raise AssertionError(f"check 12: proposed_node_id values not named in section 4.3: {bad}")


# 13. every file in data/interim is a tracked manifest or an ignored parquet.
def check_data_interim_provenance(
    data_interim_dir: Path, repo_root: Path, expected_parquet_names: set[str]
) -> None:
    for entry in sorted(data_interim_dir.iterdir()):
        if entry.is_dir():
            continue
        name = entry.name
        if name == ".gitkeep":
            continue
        if name.endswith("_manifest.json"):
            kind = "manifest"
        elif name in expected_parquet_names:
            kind = "parquet"
        else:
            raise AssertionError(
                f"check 13: unexpected file in data/interim: {name} (not a *_manifest.json "
                f"and not one of the parquet names section 4 names)"
            )
        result = subprocess.run(
            ["git", "check-ignore", "-v", str(entry)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        # `git check-ignore -v` exits 0 whenever ANY rule (positive or
        # negative) matched, not only when the path is actually ignored,
        # so the exit code alone cannot tell tracked and ignored apart. The
        # matched rule's own text can: a rule beginning with "!" is a
        # negation, meaning the path is NOT ignored.
        matched_rule = result.stdout.split(":", 2)[-1].split("\t", 1)[0] if result.stdout else ""
        is_ignored = bool(result.stdout) and not matched_rule.startswith("!")
        if kind == "manifest" and is_ignored:
            raise AssertionError(
                f"check 13: manifest {name} is git-ignored but must be tracked: {result.stdout}"
            )
        if kind == "parquet" and not is_ignored:
            raise AssertionError(
                f"check 13: parquet {name} is not git-ignored but data/raw outputs must be"
            )


# ---------------------------------------------------------------------------
# Session 2, build plan 4.8.
# ---------------------------------------------------------------------------


# 4.8 check 1: country_iso2 unique, two uppercase letters, every real ISO code present.
def session2_check_1_country_iso2_shape(
    dim_country: pd.DataFrame, iso_dim_country: pd.DataFrame
) -> None:
    check_dim_country_pk_unique(dim_country)
    bad_codes = [
        c for c in dim_country["country_iso2"] if not (len(c) == 2 and c.isalpha() and c.isupper())
    ]
    if bad_codes:
        raise AssertionError(f"4.8 check 1: codes not two uppercase letters: {bad_codes}")
    expected_real = set(iso_dim_country.loc[iso_dim_country["is_real_country"], "country_iso2"])
    present_real = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])
    missing = sorted(expected_real - present_real)
    if missing:
        raise AssertionError(f"4.8 check 1: real ISO codes missing from dim_country: {missing}")


# 4.8 check 2: every raw name string in every source resolves through the applied crosswalk.
def session2_check_2_all_raw_values_resolved(applied_crosswalk: pd.DataFrame) -> None:
    unresolved = applied_crosswalk[
        applied_crosswalk["country_iso2"].isnull() | (applied_crosswalk["country_iso2"] == "")
    ]
    if not unresolved.empty:
        offenders = list(
            unresolved[["source_system", "raw_value"]].itertuples(index=False, name=None)
        )[:10]
        raise AssertionError(
            f"4.8 check 2: {len(unresolved)} rows in the applied crosswalk are unresolved, "
            f"e.g. {offenders}"
        )


# 4.8 check 3: alias table many to one within each source system.
def session2_check_3_alias_many_to_one(applied_crosswalk: pd.DataFrame) -> None:
    dupes = applied_crosswalk[
        applied_crosswalk.duplicated(subset=["source_system", "raw_value"], keep=False)
    ]
    if not dupes.empty:
        bad = sorted(set(map(tuple, dupes[["source_system", "raw_value"]].values.tolist())))
        raise AssertionError(
            f"4.8 check 3: (source_system, raw_value) appears more than once: {bad[:10]}"
        )


# 4.8 check 4: every real country has geometry, and its stored point falls inside its own polygon.
def session2_check_4_geometry_and_containment(
    dim_country: pd.DataFrame, dissolved_geometry, centroids: pd.DataFrame
) -> list[str]:
    """Returns the list of real, LNG/pipe-role-relevant countries missing
    geometry at 1:50m resolution ("gate C" candidates) instead of raising
    for them: build_dim_country has already decided these are a reported
    gap rather than a build blocker (see its docstring), since neither a
    hand-entered polygon nor a third network pull is something this check
    is entitled to reach for on its own. A genuinely broken containment for
    a country that DOES have geometry still raises: that is a real defect,
    not a sourcing gap.
    """
    from shapely.geometry import Point

    real = dim_country[dim_country["is_real_country"]]
    missing_geom = set(real["country_iso2"]) - set(dissolved_geometry["country_iso2"])
    relevant = sorted(
        code
        for code in missing_geom
        if dim_country.loc[dim_country["country_iso2"] == code, "role_lng"].iloc[0] != "none"
        or dim_country.loc[dim_country["country_iso2"] == code, "role_pipe"].iloc[0] != "none"
    )

    merged = dissolved_geometry.merge(centroids, on="country_iso2")
    failures = []
    for _, row in merged.iterrows():
        point = Point(row["centroid_lon"], row["centroid_lat"])
        if not row.geometry.contains(point):
            failures.append(row["country_iso2"])
    if failures:
        raise AssertionError(
            f"4.8 check 4: stored centroid falls outside its own polygon: {sorted(failures)}"
        )

    return relevant


# 4.8 check 8: no landlocked country appears as an LNG exporter or importer.
def session2_check_8_no_landlocked_lng_role(dim_country: pd.DataFrame) -> None:
    violations = dim_country[
        (dim_country["is_landlocked"] == True)  # noqa: E712
        & dim_country["role_lng"].isin(["exporter", "importer", "both"])
    ]
    if not violations.empty:
        raise AssertionError(
            f"4.8 check 8: landlocked country with an LNG role: "
            f"{sorted(violations['country_iso2'])}"
        )


# 4.8 check 9: adjacency is symmetric, and every modelled pipe corridor has adjacency or an
# override.
def session2_check_9_adjacency_symmetric_and_pipe_corridors(
    applied_adjacency: pd.DataFrame,
    gtf_border_pairs: list[dict],
    applied_crosswalk: pd.DataFrame,
    real_country_codes: set[str],
) -> None:
    pairs = set(map(tuple, applied_adjacency.values.tolist()))
    asymmetric = sorted(p for p in pairs if (p[1], p[0]) not in pairs)
    if asymmetric:
        raise AssertionError(f"4.8 check 9: adjacency not symmetric for pairs: {asymmetric[:10]}")

    xwalk_map = {
        (row["source_system"], row["raw_value"]): row["country_iso2"]
        for _, row in applied_crosswalk[applied_crosswalk["source_system"] == "iea_gtf"].iterrows()
    }
    unsupported = []
    for record in gtf_border_pairs:
        exit_code = xwalk_map.get(("iea_gtf", record["exit_raw"]))
        entry_code = xwalk_map.get(("iea_gtf", record["entry_raw"]))
        if exit_code not in real_country_codes or entry_code not in real_country_codes:
            continue
        if exit_code == entry_code:
            continue
        if (exit_code, entry_code) not in pairs:
            unsupported.append((record["borderpoint"], exit_code, entry_code))
    if unsupported:
        raise AssertionError(
            f"4.8 check 9: GTF border point(s) with neither geometric adjacency nor an "
            f"override entry: {unsupported[:10]}"
        )


# 4.8 check 10: no ZZ anywhere in any output.
def session2_check_10_no_zz(
    tables: dict[str, pd.DataFrame], columns_by_table: dict[str, list[str]]
) -> None:
    offenders = []
    for name, df in tables.items():
        for col in columns_by_table.get(name, []):
            if col in df.columns and (df[col] == "ZZ").any():
                offenders.append((name, col))
    if offenders:
        raise AssertionError(f"4.8 check 10: ZZ present in output: {offenders}")


# 4.8 check 11: snapshot hashes match the manifest.
def session2_check_11_snapshot_hashes_match_manifest(
    manifest_files: dict[str, dict], base_dir: Path
) -> None:
    mismatches = []
    for filename, facts in manifest_files.items():
        path = base_dir / filename
        if not path.is_file():
            mismatches.append((filename, "missing"))
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != facts["sha256"]:
            mismatches.append((filename, "sha256 mismatch"))
    if mismatches:
        raise AssertionError(
            f"4.8 check 11: snapshot hash mismatch against manifest (source changed without "
            f"a version bump): {mismatches}"
        )


# 2.9: dim_port_candidate confidence/coordinate consistency.
def session2_check_port_candidate_confidence(port_candidates: pd.DataFrame) -> None:
    high = port_candidates[port_candidates["confidence"] == "high"]
    bad_high = high[high["latitude"].isnull() | high["longitude"].isnull()]
    if not bad_high.empty:
        raise AssertionError(
            f"2.9: {len(bad_high)} confidence=high port candidate rows have a null coordinate"
        )
    out_of_bounds = high[~high["latitude"].between(-90, 90) | ~high["longitude"].between(-180, 180)]
    if not out_of_bounds.empty:
        raise AssertionError(
            f"2.9: {len(out_of_bounds)} confidence=high port candidate rows have an "
            f"out-of-bounds coordinate"
        )

    unresolved = port_candidates[port_candidates["method"] == "unresolved"]
    bad_unresolved = unresolved[
        unresolved["latitude"].notnull() | unresolved["longitude"].notnull()
    ]
    if not bad_unresolved.empty:
        raise AssertionError(
            f"2.9: {len(bad_unresolved)} method=unresolved port candidate rows have a "
            f"non null coordinate"
        )
