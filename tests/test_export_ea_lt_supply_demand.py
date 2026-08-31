"""EA long-term supply/demand export: filters, shape assertions, and the
country-name merge. Fixtures are shaped like ea_series.read_one_snapshot's
output (test_ea_series.py's fixture pattern), not raw API JSON."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import export_ea_lt_supply_demand as export_mod  # noqa: E402

SUPPLY_SPEC = {
    "mapping_id": 297,
    "category": "natural_gas",
    "unit": "bcm",
    "aspect_subtype": None,
    "expected_countries": 2,
    "expected_min_year": 2012,
    "expected_max_year": 2013,
    "expected_obs_per_series": 2,
}

DEMAND_SPEC = {
    "mapping_id": 314,
    "category": "natural_gas",
    "unit": "bcm",
    "aspect_subtype": "total",
    "expected_countries": 1,
    "expected_min_year": 2012,
    "expected_max_year": 2013,
    "expected_obs_per_series": 2,
}


def _row(
    dataset_id,
    country_iso2,
    year,
    category="natural_gas",
    unit="bcm",
    aspect_subtype=None,
    value=1.0,
):
    return {
        "dataset_id": dataset_id,
        "country_iso2": country_iso2,
        "period": f"{year}-01-01",
        "year": year,
        "category": category,
        "unit": unit,
        "aspect_subtype": aspect_subtype,
        "value": value,
    }


def test_filter_series_keeps_only_matching_rows_and_reports_exclusions():
    df = pd.DataFrame(
        [
            *[_row(1, "US", y) for y in (2012, 2013)],
            *[_row(2, "GB", y) for y in (2012, 2013)],
            *[_row(3, "FR", y, category="oil_products") for y in (2012, 2013)],
            *[_row(4, "DE", y, unit="ktoe") for y in (2012, 2013)],
            *[_row(5, None, y) for y in (2012, 2013)],
        ]
    )
    filtered, exclusions = export_mod.filter_series(df, SUPPLY_SPEC, "supply")

    assert set(filtered["dataset_id"]) == {1, 2}
    assert set(filtered["country_iso2"]) == {"US", "GB"}
    joined = " ".join(exclusions)
    assert "category='oil_products'" in joined
    assert "unit='ktoe'" in joined
    assert "country_iso2 blank" in joined
    assert all("mapping 297 (supply)" in line for line in exclusions)


def test_filter_series_applies_aspect_subtype_filter_for_demand():
    df = pd.DataFrame(
        [
            *[_row(10, "US", y, aspect_subtype="total") for y in (2012, 2013)],
            *[_row(11, "GB", y, aspect_subtype="power") for y in (2012, 2013)],
        ]
    )
    filtered, exclusions = export_mod.filter_series(df, DEMAND_SPEC, "demand")

    assert set(filtered["dataset_id"]) == {10}
    assert any("aspect_subtype='power'" in line for line in exclusions)


def test_assert_shape_passes_on_matching_data():
    df = pd.DataFrame(
        [
            *[_row(1, "US", y) for y in (2012, 2013)],
            *[_row(2, "GB", y) for y in (2012, 2013)],
        ]
    )
    export_mod.assert_shape(df, SUPPLY_SPEC, "supply")


def test_assert_shape_raises_on_mismatched_countries():
    df = pd.DataFrame([*[_row(1, "US", y) for y in (2012, 2013)]])
    with pytest.raises(AssertionError, match="countries: expected 2, got 1"):
        export_mod.assert_shape(df, SUPPLY_SPEC, "supply")


def test_assert_shape_raises_on_mismatched_observations_per_series():
    df = pd.DataFrame(
        [
            *[_row(1, "US", y) for y in (2012, 2013)],
            _row(2, "GB", 2012),
        ]
    )
    with pytest.raises(AssertionError, match="observations per series"):
        export_mod.assert_shape(df, SUPPLY_SPEC, "supply")


def _dim_country():
    return pd.DataFrame(
        {
            "country_iso2": ["US", "GB", "FR", "XM"],
            "country_name_display": ["United States", "United Kingdom", "France", "Multiple"],
            "is_real_country": [True, True, True, False],
        }
    )


def test_build_output_table_outer_merges_and_leaves_gaps_empty():
    supply = pd.DataFrame([_row(1, "US", 2012), _row(1, "US", 2013), _row(2, "GB", 2012)])
    demand = pd.DataFrame([_row(10, "US", 2012), _row(11, "FR", 2012)])

    table = export_mod.build_output_table(supply, demand, _dim_country())

    assert list(table.columns) == [
        "country_iso2",
        "country_name",
        "year",
        "supply_bcm",
        "demand_bcm",
    ]
    us_2012 = table[(table["country_iso2"] == "US") & (table["year"] == 2012)].iloc[0]
    assert us_2012["supply_bcm"] == 1.0
    assert us_2012["demand_bcm"] == 1.0
    us_2013 = table[(table["country_iso2"] == "US") & (table["year"] == 2013)].iloc[0]
    assert us_2013["supply_bcm"] == 1.0
    assert pd.isnull(us_2013["demand_bcm"])
    fr_2012 = table[(table["country_iso2"] == "FR") & (table["year"] == 2012)].iloc[0]
    assert pd.isnull(fr_2012["supply_bcm"])
    assert fr_2012["demand_bcm"] == 1.0
    assert fr_2012["country_name"] == "France"
    assert (table["demand_bcm"].fillna(0) != 0).sum() == 2  # never a fabricated zero
    assert not (table.fillna(-1) == 0).any().any()


def test_build_output_table_raises_on_unmapped_country():
    supply = pd.DataFrame([_row(1, "ZZ", 2012)])
    demand = pd.DataFrame(columns=supply.columns)
    with pytest.raises(ValueError, match="not present in dim_country"):
        export_mod.build_output_table(supply, demand, _dim_country())


def test_build_output_table_raises_on_pseudo_country_code():
    """CLAUDE.md: 'a ZZ reaching any output is a bug, not a category' -- XM is
    mapped in dim_country (so it passes the unmapped-code check) but flagged
    is_real_country=False, and must still be rejected."""
    supply = pd.DataFrame([_row(1, "XM", 2012)])
    demand = pd.DataFrame(columns=supply.columns)
    with pytest.raises(ValueError, match="is_real_country=False"):
        export_mod.build_output_table(supply, demand, _dim_country())


def test_build_output_table_raises_on_duplicate_country_year():
    """Two datasets both claiming the same country-year in one series would
    silently double up a value in an outer merge; must raise instead."""
    supply = pd.DataFrame([_row(1, "US", 2012), _row(2, "US", 2012)])
    demand = pd.DataFrame(columns=supply.columns)
    with pytest.raises(ValueError, match="duplicate"):
        export_mod.build_output_table(supply, demand, _dim_country())


def test_build_output_table_raises_on_row_with_no_source_value():
    """Defensive: a row must be backed by at least one real series value,
    never an all-empty fabricated row."""
    supply = pd.DataFrame([_row(1, "US", 2012, value=None)])
    demand = pd.DataFrame(columns=supply.columns)
    with pytest.raises(ValueError, match="neither a supply nor a demand value"):
        export_mod.build_output_table(supply, demand, _dim_country())


def test_summarize_buckets_countries_by_coverage():
    table = pd.DataFrame(
        {
            "country_iso2": ["US", "GB", "FR"],
            "country_name": ["United States", "United Kingdom", "France"],
            "year": [2012, 2012, 2012],
            "supply_bcm": [1.0, 1.0, None],
            "demand_bcm": [1.0, None, 1.0],
        }
    )
    summary = export_mod.summarize(table)
    assert summary["rows_written"] == 3
    assert summary["both_countries"] == ["US"]
    assert summary["supply_only_countries"] == ["GB"]
    assert summary["demand_only_countries"] == ["FR"]


def test_find_latest_vintage_picks_newest_by_name(tmp_path):
    (tmp_path / "202606").mkdir()
    (tmp_path / "202608").mkdir()
    (tmp_path / "not_a_vintage").mkdir()
    assert export_mod.find_latest_vintage(tmp_path) == "202608"


def test_find_latest_vintage_raises_when_none_pinned(tmp_path):
    with pytest.raises(RuntimeError, match="No pinned EA API vintage"):
        export_mod.find_latest_vintage(tmp_path)
