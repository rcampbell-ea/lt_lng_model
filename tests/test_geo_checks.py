"""
Session 1 gate: the thirteen checks in build plan 4.7, run against the
actual outputs of ``scripts/build_session1.py``. If the build has not been
run yet, these tests skip rather than fail, since they validate the
deliverables on disk rather than re-running the build themselves.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from lt_lng_flows.geo.area_node_proposal import load_valid_node_ids
from lt_lng_flows.geo.country_master import AliasResolver, build_dim_country
from lt_lng_flows.validate import geo_checks

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_GEO = ROOT / "data" / "geo"
CROSSWALKS_DIR = ROOT / "crosswalks"

REQUIRED_ARTIFACTS = [
    DATA_INTERIM / "raw_country_strings.parquet",
    DATA_GEO / "dim_country.parquet",
    CROSSWALKS_DIR / "xwalk_country_alias_proposed.csv",
    DATA_INTERIM / "ea_dataset_catalogue.parquet",
    DATA_INTERIM / "ea_ct_area.parquet",
    DATA_INTERIM / "ea_ct_area_country.parquet",
    DATA_INTERIM / "ea_ct_country_port.parquet",
    CROSSWALKS_DIR / "xwalk_area_node_proposed.csv",
    DATA_INTERIM / "workbooks_202608_manifest.json",
    DATA_INTERIM / "ea_api_202608_manifest.json",
]


def _require_build():
    missing = [str(p) for p in REQUIRED_ARTIFACTS if not p.is_file()]
    if missing:
        pytest.skip(
            "session 1 build outputs not present; run scripts/build_session1.py "
            f"first. Missing: {missing}"
        )


@pytest.fixture(scope="module")
def constants():
    with (CONFIG_DIR / "session_01_constants.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def dim_country():
    _require_build()
    return pd.read_parquet(DATA_GEO / "dim_country.parquet")


@pytest.fixture(scope="module")
def raw_country_strings():
    _require_build()
    return pd.read_parquet(DATA_INTERIM / "raw_country_strings.parquet")


@pytest.fixture(scope="module")
def crosswalk():
    _require_build()
    return pd.read_csv(CROSSWALKS_DIR / "xwalk_country_alias_proposed.csv", keep_default_na=False)


@pytest.fixture(scope="module")
def ea_dataset_catalogue():
    _require_build()
    return pd.read_parquet(DATA_INTERIM / "ea_dataset_catalogue.parquet")


@pytest.fixture(scope="module")
def ea_ct_area():
    _require_build()
    return pd.read_parquet(DATA_INTERIM / "ea_ct_area.parquet")


@pytest.fixture(scope="module")
def ea_ct_area_country():
    _require_build()
    return pd.read_parquet(DATA_INTERIM / "ea_ct_area_country.parquet")


@pytest.fixture(scope="module")
def ea_ct_country_port():
    _require_build()
    return pd.read_parquet(DATA_INTERIM / "ea_ct_country_port.parquet")


@pytest.fixture(scope="module")
def area_node_proposal():
    _require_build()
    return pd.read_csv(CROSSWALKS_DIR / "xwalk_area_node_proposed.csv", keep_default_na=False)


# ---- checks 1, 2 ----------------------------------------------------------


def test_check_01_dim_country_pk_unique(dim_country):
    geo_checks.check_dim_country_pk_unique(dim_country)


def test_check_02_pseudo_codes_present(dim_country):
    with (CONFIG_DIR / "pseudo_country_codes.yaml").open(encoding="utf-8") as f:
        pseudo_codes = yaml.safe_load(f)["pseudo_codes"]
    geo_checks.check_pseudo_codes_present(dim_country, pseudo_codes)


# ---- checks 3-6 (crosswalk) -----------------------------------------------


def test_check_03_raw_strings_covered_exactly_once(raw_country_strings, crosswalk):
    geo_checks.check_raw_strings_covered_exactly_once(raw_country_strings, crosswalk)


def test_check_04_proposed_iso2_known(crosswalk, dim_country):
    geo_checks.check_proposed_iso2_known(crosswalk, dim_country)


def test_check_05_no_zz_proposed(crosswalk):
    geo_checks.check_no_zz_proposed(crosswalk)


def test_check_06_confidence_method_consistency(crosswalk):
    geo_checks.check_confidence_method_consistency(crosswalk)


# ---- check 7 (ea dataset catalogue counts) --------------------------------


def test_check_07_ea_dataset_catalogue_counts(constants):
    _require_build()
    catalogue = pd.read_parquet(DATA_INTERIM / "ea_dataset_catalogue.parquet")
    from lt_lng_flows.ingest.ea_dataset_catalogue import read_ea_dataset_catalogue

    _, dedup_report = read_ea_dataset_catalogue(
        ROOT / "data" / "raw" / "ea_api" / "202608" / "ea_api_mappings.txt"
    )
    geo_checks.check_ea_dataset_catalogue_counts(catalogue, dedup_report, constants)


# ---- check 8 (ascii lower snake case) -------------------------------------


def test_check_08_ascii_lower_snake_case(dim_country, crosswalk, area_node_proposal):
    names = {}
    for col in dim_country.columns:
        names[f"dim_country.{col}"] = col
    for col in crosswalk.columns:
        names[f"xwalk_country_alias_proposed.{col}"] = col
    for col in area_node_proposal.columns:
        names[f"xwalk_area_node_proposed.{col}"] = col
    for artifact in REQUIRED_ARTIFACTS:
        names[f"filename:{artifact.name}"] = artifact.name
    geo_checks.check_ascii_lower_snake_case(names)


def test_check_08_rejects_bad_names():
    with pytest.raises(AssertionError):
        geo_checks.check_ascii_lower_snake_case({"bad": "Not-Snake-Case"})


# ---- checks 9-11 (ea cargo tracking) ---------------------------------------


def test_check_09_ea_ct_area_shape(ea_ct_area, constants):
    geo_checks.check_ea_ct_area_shape(ea_ct_area, constants)


def test_check_10_ea_ct_country_codes_valid(ea_ct_area_country, ea_ct_country_port, dim_country):
    geo_checks.check_ea_ct_country_codes_valid(ea_ct_area_country, ea_ct_country_port, dim_country)


def test_check_11_ea_ct_uniqueness_and_subcountry(
    ea_ct_area_country, ea_ct_country_port, constants
):
    _require_build()
    from lt_lng_flows.ingest.ea_cargo_tracking import read_ea_ct_country_ports

    _, report = read_ea_ct_country_ports(
        ROOT / "data" / "raw" / "ea_api" / "202608" / "ea_ct_country_ports.txt"
    )
    geo_checks.check_ea_ct_uniqueness_and_subcountry(
        ea_ct_area_country, ea_ct_country_port, report, constants
    )


# ---- check 12 (area-node proposal) -----------------------------------------


def test_check_12_area_node_proposal(area_node_proposal, ea_ct_area):
    valid_node_ids = load_valid_node_ids(CONFIG_DIR / "lng_nodes.yaml")
    geo_checks.check_area_node_proposal(area_node_proposal, ea_ct_area, valid_node_ids)


# ---- check 13 (data/interim provenance) ------------------------------------


def test_check_13_data_interim_provenance():
    _require_build()
    expected_parquet_names = {
        "raw_country_strings.parquet",
        "ea_dataset_catalogue.parquet",
        "ea_ct_area.parquet",
        "ea_ct_area_country.parquet",
        "ea_ct_country_port.parquet",
    }
    geo_checks.check_data_interim_provenance(DATA_INTERIM, ROOT, expected_parquet_names)


# ---- deliverable-level sanity: no fuzzy matching, ZZ never proposed --------


def test_alias_resolver_exact_match_only():
    dim = build_dim_country(
        DATA_GEO / "raw" / "iso3166_1_countries.csv", CONFIG_DIR / "pseudo_country_codes.yaml"
    )
    resolver = AliasResolver(dim, {"portfolio": "XP", "multiple": "XM"})

    assert resolver.resolve("FR") == {
        "proposed_iso2": "FR",
        "confidence": "high",
        "method": "exact_iso2",
        "note": "",
    }
    assert resolver.resolve("fr")["proposed_iso2"] == "FR"
    assert resolver.resolve("France")["proposed_iso2"] == "FR"
    assert resolver.resolve("Portfolio")["proposed_iso2"] == "XP"

    # No substring, edit-distance, or partial match: "Frenchland" is not "France".
    unresolved = resolver.resolve("Frenchland")
    assert unresolved["proposed_iso2"] == ""
    assert unresolved["method"] == "unresolved"

    # ZZ is never proposed, even on a literal exact match.
    zz_result = resolver.resolve("ZZ")
    assert zz_result["proposed_iso2"] == ""
    assert zz_result["method"] == "unresolved"


def test_dim_country_rejects_missing_column(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("country_iso2,country_name\nFR,France\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing expected columns"):
        build_dim_country(bad_csv, CONFIG_DIR / "pseudo_country_codes.yaml")
