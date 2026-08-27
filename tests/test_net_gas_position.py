"""Session 6: fact_net_gas_position over the full pinned span, plus the
mapping 545 LNG net position, on small synthetic fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from lt_lng_flows.model import net_gas_position as ngp


def _dim_country(codes):
    return pd.DataFrame({"country_iso2": codes, "is_real_country": [True] * len(codes)})


def _gas_balance_row(**overrides):
    row = {
        "country_iso2": "DE",
        "period": "2020-01-01",
        "year": 2020,
        "component": "supply",
        "category": "natural_gas",
        "value": 10.0,
        "unit": "bcm",
        "lifecycle_stage": "forecast",
        "frequency": "yearly",
        "dataset_id": 1,
        "mapping_id": 297,
        "aspect_subtype": None,
        "category_subtype": None,
    }
    row.update(overrides)
    return row


def test_build_fact_net_gas_position_spans_full_data_range_not_a_fixed_horizon():
    rows = [
        _gas_balance_row(country_iso2="DE", year=2010, dataset_id=1, value=5.0),
        _gas_balance_row(country_iso2="DE", year=2030, dataset_id=2, value=6.0),
        _gas_balance_row(
            country_iso2="DE",
            year=2010,
            dataset_id=3,
            value=4.0,
            component="demand",
            mapping_id=314,
            aspect_subtype="total",
        ),
        _gas_balance_row(
            country_iso2="DE",
            year=2030,
            dataset_id=4,
            value=3.0,
            component="demand",
            mapping_id=314,
            aspect_subtype="total",
        ),
    ]
    fact_gas_balance = pd.DataFrame(rows)
    out = ngp.build_fact_net_gas_position(fact_gas_balance, _dim_country(["DE"]))

    assert out["year"].min() == 2010
    assert out["year"].max() == 2030
    assert len(out) == 21  # 2010..2030 inclusive, one country

    row_2010 = out[out["year"] == 2010].iloc[0]
    assert row_2010["surplus_deficit_bcm"] == pytest.approx(1.0)
    assert pd.isna(row_2010["missing_side"])

    row_2020 = out[out["year"] == 2020].iloc[0]
    assert pd.isna(row_2020["supply_bcm"])
    assert pd.isna(row_2020["demand_bcm"])
    assert row_2020["missing_side"] == "both"


def test_build_fact_net_gas_position_flags_missing_side_not_a_zero():
    rows = [
        _gas_balance_row(country_iso2="DE", year=2020, dataset_id=1, value=5.0),
        _gas_balance_row(
            country_iso2="FR",
            year=2020,
            dataset_id=2,
            value=4.0,
            component="demand",
            mapping_id=314,
            aspect_subtype="total",
        ),
    ]
    fact_gas_balance = pd.DataFrame(rows)
    out = ngp.build_fact_net_gas_position(fact_gas_balance, _dim_country(["DE", "FR"]))

    de = out[out["country_iso2"] == "DE"].iloc[0]
    fr = out[out["country_iso2"] == "FR"].iloc[0]
    assert de["missing_side"] == "demand"
    assert pd.isna(de["demand_bcm"])
    assert pd.isna(de["surplus_deficit_bcm"])  # never a fabricated zero
    assert fr["missing_side"] == "supply"


def test_build_fact_net_gas_position_raises_on_unresolved_country():
    rows = [_gas_balance_row(country_iso2="ZZ", year=2020, dataset_id=1, value=5.0)]
    fact_gas_balance = pd.DataFrame(rows)
    with pytest.raises(ValueError, match="exact-join violation"):
        ngp.build_fact_net_gas_position(fact_gas_balance, _dim_country(["DE"]))


def test_build_fact_net_gas_position_excludes_non_bcm_and_countryless_demand_rows():
    # A WORLD-level demand aggregate: no country, denominated in ktoe --
    # must never reach demand_bcm (session 6 step 5's finding, dataset
    # 587472 in the real pinned data).
    rows = [
        _gas_balance_row(country_iso2="DE", year=2020, dataset_id=1, value=5.0),
        _gas_balance_row(
            country_iso2=None,
            year=2020,
            dataset_id=2,
            value=2375011.0,
            component="demand",
            mapping_id=314,
            aspect_subtype="total",
            unit="ktoe",
        ),
    ]
    fact_gas_balance = pd.DataFrame(rows)
    out = ngp.build_fact_net_gas_position(fact_gas_balance, _dim_country(["DE"]))
    assert out["demand_bcm"].isnull().all()


def test_build_lng_net_position_excludes_nwe_aggregate_and_nets_available_sides():
    rows = [
        {
            "country_iso2": "US",
            "year": 2030,
            "component": "net_exports",
            "value": 50.0,
            "unit": "bcm",
            "mapping_id": 545,
            "category_subtype": "LNG",
        },
        {
            "country_iso2": "US",
            "year": 2030,
            "component": "net_imports",
            "value": 5.0,
            "unit": "bcm",
            "mapping_id": 545,
            "category_subtype": "LNG",
        },
        {
            "country_iso2": "JP",
            "year": 2030,
            "component": "net_imports",
            "value": 30.0,
            "unit": "bcm",
            "mapping_id": 545,
            "category_subtype": "LNG",
        },
        {
            "country_iso2": None,
            "year": 2030,
            "component": "net_imports",
            "value": 999.0,
            "unit": "bcm",
            "mapping_id": 545,
            "category_subtype": "LNG",
        },
    ]
    fact_gas_balance = pd.DataFrame(rows)
    out = ngp.build_lng_net_position(fact_gas_balance, _dim_country(["US", "JP"]))

    us = out[out["country_iso2"] == "US"].iloc[0]
    jp = out[out["country_iso2"] == "JP"].iloc[0]
    assert us["lng_net_bcm"] == pytest.approx(45.0)
    assert jp["lng_net_bcm"] == pytest.approx(-30.0)  # net_exports side absent, treated as 0
    assert None not in set(out["country_iso2"])  # NWE-style null-country row excluded
