"""
session6_checks.py
-------------------
Session 6, step 5: the units data check. Mapping 314's natural_gas total
demand series and mapping 297's natural_gas supply series are each expected
to be entirely bcm; this lists any dataset in either mapping's relevant
scope that is denominated in something else, so a unit mismatch is a named
finding, not a silent factor-of-a-thousand error buried in a sum.
"""

from __future__ import annotations

import pandas as pd


def find_non_bcm_datasets(
    fact_gas_balance: pd.DataFrame,
    mapping_id: int,
    category: str = "natural_gas",
    aspect_subtype: str | None = None,
) -> pd.DataFrame:
    """One row per (dataset_id, unit, country_iso2, description) in the
    given mapping/category(/aspect_subtype) scope whose unit is not bcm.
    ``country_iso2`` is left as-is, including null -- a null here means the
    series carries no country at all (e.g. a WORLD aggregate), which is
    itself part of the finding, not something to paper over.
    """
    scope = fact_gas_balance[
        (fact_gas_balance["mapping_id"] == mapping_id) & (fact_gas_balance["category"] == category)
    ]
    if aspect_subtype is not None:
        scope = scope[scope["aspect_subtype"] == aspect_subtype]
    non_bcm = scope[scope["unit"] != "bcm"]
    return (
        non_bcm[["country_iso2", "dataset_id", "unit", "description"]]
        .drop_duplicates()
        .sort_values(["unit", "dataset_id"])
        .reset_index(drop=True)
    )
