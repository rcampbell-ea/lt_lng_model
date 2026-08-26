"""Session 3, build plan 3.5: fact_gas_balance loader. Reports empty when no
pull has landed, and parses a fixture snapshot shaped like
scripts/pull_ea_series.py's output when one has."""

from __future__ import annotations

import json

import pytest

from lt_lng_flows.ingest import ea_series


def test_build_fact_gas_balance_empty_when_no_snapshot(tmp_path):
    df, snapshots = ea_series.build_fact_gas_balance(tmp_path / "ea_api")
    assert df.empty
    assert snapshots == []
    assert list(df.columns) == ea_series.FACT_GAS_BALANCE_COLUMNS


def test_build_fact_gas_balance_parses_fixture_snapshot(tmp_path):
    mapping_dir = tmp_path / "ea_api" / "202608" / "mapping_297"
    mapping_dir.mkdir(parents=True)
    # Shape confirmed against a real pull this session (docs/session_03_ingestion.md):
    # dataset-level fields live under "metadata", not the record's top level;
    # "dataset_id" is the one field that is top level.
    payload = [
        {
            "pagination": {"page": 1, "max_pages": 1},
            "dataset_id": 73067,
            "metadata": {
                "country_iso": "US",
                "aspect": "supply",
                "category": "natural_gas",
                "unit": "bcm",
                "frequency": "yearly",
                "lifecycle_stage": "forecast",
                "release_date": "2026-08-01",
            },
            "data": {"2025-01-01": 1100.0, "2026-01-01": 1150.0},
        },
        {
            "pagination": {"page": 1, "max_pages": 1},
            "dataset_id": 73068,
            "metadata": {
                "country_iso": None,
                "aspect": "supply",
                "category": "natural_gas",
                "unit": "bcm",
                "frequency": "yearly",
                "lifecycle_stage": "forecast",
                "release_date": "2026-08-01",
            },
            "data": {"2025-01-01": 5000.0},
        },
    ]
    (mapping_dir / "response.json").write_text(json.dumps(payload), encoding="utf-8")

    df, snapshots = ea_series.build_fact_gas_balance(tmp_path / "ea_api")
    assert len(snapshots) == 1
    assert len(df) == 3
    us_2025 = df[(df["country_iso2"] == "US") & (df["year"] == 2025)]
    assert us_2025.iloc[0]["value"] == 1100.0
    assert us_2025.iloc[0]["component"] == "supply"
    world_row = df[df["country_iso2"].isnull()]
    assert len(world_row) == 1


def test_read_one_snapshot_keeps_monthly_rows_distinct_by_period(tmp_path):
    """Regression: mappings 5/6 ('Global LNG exports/imports') are monthly
    frequency. (dataset_id, year) alone collides across a year's twelve
    months -- caught as a real PRIMARY KEY violation against a live pull
    (docs/session_03_ingestion.md). The grain must be (dataset_id, period).
    """
    path = tmp_path / "response.json"
    payload = [
        {
            "dataset_id": 130,
            "metadata": {
                "country_iso": "DZ",
                "aspect": "exports",
                "category": "natural_gas",
                "unit": "Mt",
                "frequency": "monthly",
                "lifecycle_stage": "forecast",
            },
            "data": {"2010-01-01": 1.1, "2010-02-01": 1.2, "2010-03-01": 1.3},
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    df = ea_series.read_one_snapshot(path)
    assert len(df) == 3
    assert df["period"].nunique() == 3
    assert (df["year"] == 2010).all()
    assert df.set_index("period").index.is_unique


def test_read_one_snapshot_raises_on_missing_top_level_key(tmp_path):
    path = tmp_path / "response.json"
    path.write_text(json.dumps([{"dataset_id": 1}]), encoding="utf-8")
    with pytest.raises(ValueError, match="missing keys"):
        ea_series.read_one_snapshot(path)


def test_read_one_snapshot_raises_on_missing_metadata_key(tmp_path):
    path = tmp_path / "response.json"
    path.write_text(
        json.dumps(
            [{"dataset_id": 1, "metadata": {"aspect": "supply", "category": "natural_gas"}}]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="metadata missing keys"):
        ea_series.read_one_snapshot(path)


def test_read_one_snapshot_raises_on_bad_country_iso_length(tmp_path):
    path = tmp_path / "response.json"
    payload = [
        {
            "dataset_id": 1,
            "metadata": {
                "country_iso": "USA",
                "aspect": "supply",
                "category": "natural_gas",
                "unit": "bcm",
                "frequency": "yearly",
                "lifecycle_stage": "forecast",
            },
            "data": {"2025-01-01": 1.0},
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="country_iso"):
        ea_series.read_one_snapshot(path)
