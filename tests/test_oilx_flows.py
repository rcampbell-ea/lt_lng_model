"""Session 3, build plan 3.4c: fact_lng_flow_baseline loader. Reports empty
when no pull has landed, and parses a fixture snapshot shaped like
scripts/pull_oilx_flows.py's output (PascalCase fields per plan 3.2c)."""

from __future__ import annotations

import json

import pytest

from lt_lng_flows.ingest import oilx_flows


def test_build_fact_lng_flow_baseline_empty_when_no_snapshot(tmp_path):
    df, snapshots = oilx_flows.build_fact_lng_flow_baseline(tmp_path / "oilx")
    assert df.empty
    assert snapshots == []
    assert list(df.columns) == oilx_flows.FACT_LNG_FLOW_BASELINE_COLUMNS


def test_build_fact_lng_flow_baseline_parses_fixture_and_excludes_deleted(tmp_path):
    flows_dir = tmp_path / "oilx" / "202608" / "flows_lng"
    flows_dir.mkdir(parents=True)
    payload = [
        {
            "OriginCountryCode": "QA",
            "DestinationCountryCode": "JP",
            "ReferenceDate": "2025-03-01",
            "QuantityKT": 65.0,
            "QuantityCBM": 140000.0,
            "QuantityMMBtu": 3200000.0,
            "Deleted": False,
        },
        {
            "OriginCountryCode": "QA",
            "DestinationCountryCode": "JP",
            "ReferenceDate": "2025-06-01",
            "QuantityKT": 70.0,
            "QuantityCBM": 150000.0,
            "QuantityMMBtu": 3400000.0,
            "Deleted": False,
        },
        {
            "OriginCountryCode": "US",
            "DestinationCountryCode": "GB",
            "ReferenceDate": "2025-01-01",
            "QuantityKT": 60.0,
            "QuantityCBM": 130000.0,
            "QuantityMMBtu": 3000000.0,
            "Deleted": True,
        },
    ]
    (flows_dir / "response.json").write_text(json.dumps(payload), encoding="utf-8")

    df, snapshots = oilx_flows.build_fact_lng_flow_baseline(tmp_path / "oilx")
    assert len(snapshots) == 1
    assert len(df) == 1  # QA->JP 2025 aggregated; deleted US->GB row excluded
    row = df.iloc[0]
    assert row["origin_iso2"] == "QA"
    assert row["destination_iso2"] == "JP"
    assert row["year"] == 2025
    assert row["quantity_kt"] == pytest.approx(135.0)
    assert row["bcm"] is None  # unit question open, never a fabricated conversion


def test_read_one_snapshot_raises_on_bad_country_code(tmp_path):
    path = tmp_path / "response.json"
    payload = [
        {
            "OriginCountryCode": "QATAR",
            "DestinationCountryCode": "JP",
            "ReferenceDate": "2025-01-01",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="non two-character"):
        oilx_flows.read_one_snapshot(path)
