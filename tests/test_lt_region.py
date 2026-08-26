"""Session 3, build plan 3.6b/3.7: lt_region derivation reports "not
derivable" when the region-carrying EA pull hasn't happened (the state this
session leaves it in), and correctly partitions/multi-values a fixture that
does carry a region column."""

from __future__ import annotations

import pandas as pd

from lt_lng_flows.geo import dim_aggregate, lt_region


def _dim_country_stub():
    return pd.DataFrame(
        {
            "country_iso2": ["FR", "DE", "ZZ_unused"],
            "role_lng": ["importer", "none", "none"],
            "role_pipe": ["none", "exporter", "none"],
        }
    )


def test_derive_lt_region_not_derivable_when_no_region_column():
    empty = pd.DataFrame(columns=["country_iso2", "year", "component", "value"])
    result = lt_region.derive_lt_region(empty, _dim_country_stub())
    assert result["derivable"] is False
    assert "not been pulled" in result["reason"] or "no EA series" in result["reason"]


def test_derive_lt_region_partition_and_multi_valued():
    fact_gas_balance = pd.DataFrame(
        {
            "country_iso2": ["FR", "FR", "DE"],
            "mapping_id": [314, 550, 314],
            "region": ["EUR", "OECD", "EUR"],
            "year": [2025, 2025, 2025],
            "component": ["demand"] * 3,
            "value": [1.0, 1.0, 1.0],
        }
    )
    result = lt_region.derive_lt_region(fact_gas_balance, _dim_country_stub())
    assert result["derivable"] is True
    assert result["lt_region_by_country"] == {"DE": "EUR"}
    assert result["multi_valued_countries"] == {"FR": ["EUR", "OECD"]}
    # role_lng/role_pipe both none for ZZ_unused stub, so it's fine it's absent
    assert result["missing_from_partition"] == []


def test_empty_dim_country_region_tag_schema():
    df = lt_region.empty_dim_country_region_tag()
    assert list(df.columns) == lt_region.REGION_TAG_COLUMNS
    assert df.empty


def test_empty_dim_aggregate_schema():
    df = dim_aggregate.empty_dim_aggregate()
    assert list(df.columns) == dim_aggregate.DIM_AGGREGATE_COLUMNS
    assert df.empty
