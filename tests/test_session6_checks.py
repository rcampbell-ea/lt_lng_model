"""Session 6, step 5: the units data check."""

from __future__ import annotations

import pandas as pd

from lt_lng_flows.validate import session6_checks


def test_find_non_bcm_datasets_lists_only_non_bcm_rows_in_scope():
    fact_gas_balance = pd.DataFrame(
        [
            {
                "mapping_id": 314,
                "category": "natural_gas",
                "aspect_subtype": "total",
                "unit": "bcm",
                "country_iso2": "DE",
                "dataset_id": 1,
                "description": "Germany demand",
            },
            {
                "mapping_id": 314,
                "category": "natural_gas",
                "aspect_subtype": "total",
                "unit": "ktoe",
                "country_iso2": None,
                "dataset_id": 2,
                "description": "World total gas demand ktoe",
            },
            {
                "mapping_id": 314,
                "category": "natural_gas",
                "aspect_subtype": "own_use",
                "unit": "ktoe",
                "country_iso2": "FR",
                "dataset_id": 3,
                "description": "France own use -- different aspect_subtype, out of scope",
            },
        ]
    )
    out = session6_checks.find_non_bcm_datasets(
        fact_gas_balance, mapping_id=314, category="natural_gas", aspect_subtype="total"
    )
    assert len(out) == 1
    assert out.iloc[0]["dataset_id"] == 2
    assert pd.isna(out.iloc[0]["country_iso2"])


def test_find_non_bcm_datasets_empty_when_all_bcm():
    fact_gas_balance = pd.DataFrame(
        [
            {
                "mapping_id": 297,
                "category": "natural_gas",
                "aspect_subtype": None,
                "unit": "bcm",
                "country_iso2": "DE",
                "dataset_id": 1,
                "description": "Germany supply",
            }
        ]
    )
    out = session6_checks.find_non_bcm_datasets(fact_gas_balance, mapping_id=297)
    assert out.empty
