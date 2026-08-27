"""
net_gas_position.py
--------------------
Session 6. The surplus/deficit table itself (EA supply minus EA demand, per
country per year, over the full span mappings 297 and 314 actually carry
data -- not the 2025-2050 model horizon used by session 5), plus the LNG
side of the known split (mapping 545, beside the table, never subtracted
from it). The pipe side of the known split lives in
``lt_lng_flows.pipe.net_pipe_position`` since it reads a different source
(IEA GTF, not the EA API).

No balance identity is asserted here. ``surplus_deficit_bcm`` is exactly
``supply_bcm - demand_bcm`` from EA's own two forecasts; ``net_pipe_bcm``
and ``lng_net_bcm`` sit beside it as separately-sourced components, per the
session 6 task -- not summed against it, not reconciled, no residual named.
"""

from __future__ import annotations

from itertools import product

import pandas as pd

MAPPING_SUPPLY = 297
MAPPING_DEMAND = 314
MAPPING_LNG = 545


def _real_country_codes(dim_country: pd.DataFrame) -> set[str]:
    return set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])


def _assert_one_row_per_country_year(frame: pd.DataFrame, label: str, mapping_id: int) -> None:
    dup = frame.groupby(["country_iso2", "year"]).size()
    offenders = dup[dup > 1]
    if len(offenders):
        raise ValueError(
            f"net_gas_position: ambiguous {label} -- more than one mapping {mapping_id} row "
            f"for (country_iso2, year): {offenders.index.tolist()[:5]}"
        )


def _assert_known_countries(frame: pd.DataFrame, label: str, real_codes: set[str]) -> None:
    unresolved = set(frame["country_iso2"]) - real_codes
    if unresolved:
        raise ValueError(
            f"net_gas_position: {label} carries country_iso2 value(s) not in dim_country's real "
            f"countries -- exact-join violation, naming the offender(s): {sorted(unresolved)}"
        )


def extract_supply(fact_gas_balance: pd.DataFrame) -> pd.DataFrame:
    """Mapping 297, the same scope session 5 used: category=natural_gas,
    unit=bcm, frequency=yearly, lifecycle_stage=forecast, a real country
    attached. No year restriction -- the full pinned span."""
    return fact_gas_balance[
        (fact_gas_balance["mapping_id"] == MAPPING_SUPPLY)
        & (fact_gas_balance["category"] == "natural_gas")
        & (fact_gas_balance["unit"] == "bcm")
        & (fact_gas_balance["frequency"] == "yearly")
        & (fact_gas_balance["lifecycle_stage"] == "forecast")
        & fact_gas_balance["country_iso2"].notnull()
    ][["country_iso2", "year", "value"]].rename(columns={"value": "supply_bcm"})


def extract_demand(fact_gas_balance: pd.DataFrame) -> pd.DataFrame:
    """Mapping 314, aspect_subtype=total, category=natural_gas, unit=bcm.
    The unit filter is deliberate, not incidental: mapping 314's natural_gas
    total-demand rows are bcm for every country-attached dataset in the
    pinned snapshot, and the one ktoe row (dataset 587472) is a WORLD
    aggregate with no country attached at all (see step 5 / session 6
    catch-up doc) -- the country_iso2.notnull() filter below drops it for
    that reason on its own, and the unit filter is a second, independent
    guard against ever summing a non-bcm value into demand_bcm."""
    return fact_gas_balance[
        (fact_gas_balance["mapping_id"] == MAPPING_DEMAND)
        & (fact_gas_balance["aspect_subtype"] == "total")
        & (fact_gas_balance["category"] == "natural_gas")
        & (fact_gas_balance["unit"] == "bcm")
        & fact_gas_balance["country_iso2"].notnull()
    ][["country_iso2", "year", "value"]].rename(columns={"value": "demand_bcm"})


def build_fact_net_gas_position(
    fact_gas_balance: pd.DataFrame, dim_country: pd.DataFrame
) -> pd.DataFrame:
    """The surplus/deficit table: country_iso2, year, supply_bcm, demand_bcm,
    surplus_deficit_bcm, missing_side. Span is the union of every year
    either mapping actually carries data for (min to max, inclusive) --
    established from the data itself, not assumed from a config horizon.
    missing_side is null when both sides are present, else one of
    'supply', 'demand', 'both' naming which side(s) are absent for that
    country/year -- never a zero standing in for an absent observation.
    """
    real_codes = _real_country_codes(dim_country)

    supply = extract_supply(fact_gas_balance)
    demand = extract_demand(fact_gas_balance)

    _assert_one_row_per_country_year(supply, "supply", MAPPING_SUPPLY)
    _assert_one_row_per_country_year(demand, "demand", MAPPING_DEMAND)
    _assert_known_countries(supply, "supply", real_codes)
    _assert_known_countries(demand, "demand", real_codes)

    countries = sorted(set(supply["country_iso2"]) | set(demand["country_iso2"]))
    year_min = min(supply["year"].min(), demand["year"].min())
    year_max = max(supply["year"].max(), demand["year"].max())
    years = list(range(int(year_min), int(year_max) + 1))
    grid = pd.DataFrame(list(product(countries, years)), columns=["country_iso2", "year"])

    out = grid.merge(supply, on=["country_iso2", "year"], how="left").merge(
        demand, on=["country_iso2", "year"], how="left"
    )
    has_supply = out["supply_bcm"].notnull()
    has_demand = out["demand_bcm"].notnull()
    out["surplus_deficit_bcm"] = out["supply_bcm"] - out["demand_bcm"]

    missing_side = pd.Series(pd.NA, index=out.index, dtype="object")
    missing_side[~has_supply & ~has_demand] = "both"
    missing_side[~has_supply & has_demand] = "supply"
    missing_side[has_supply & ~has_demand] = "demand"
    out["missing_side"] = missing_side

    out["source"] = "ea_mapping_297_minus_314_total"
    return (
        out[
            [
                "country_iso2",
                "year",
                "supply_bcm",
                "demand_bcm",
                "surplus_deficit_bcm",
                "missing_side",
                "source",
            ]
        ]
        .sort_values(["country_iso2", "year"])
        .reset_index(drop=True)
    )


def build_lng_net_position(
    fact_gas_balance: pd.DataFrame, dim_country: pd.DataFrame
) -> pd.DataFrame:
    """Mapping 545, net_exports minus net_imports per country per year.
    The North West Europe aggregate row (no country_iso2) is excluded, per
    the session 6 task -- not attributed to any single country. Where a
    country has a series on only one side of net_exports/net_imports for a
    given year, the missing side is treated as 0 for the netting arithmetic
    (mapping 545 simply does not publish a series for a country/year
    combination too immaterial to warrant one -- same convention session 5
    used for the same data, plan 5.7's definition of 'net'); a country/year
    with no 545 series on either side gets a null lng_net_bcm, never a
    fabricated 0.
    """
    real_codes = _real_country_codes(dim_country)
    m545 = fact_gas_balance[
        (fact_gas_balance["mapping_id"] == MAPPING_LNG)
        & (fact_gas_balance["category_subtype"] == "LNG")
        & (fact_gas_balance["unit"] == "bcm")
        & fact_gas_balance["country_iso2"].notnull()
    ]
    _assert_known_countries(m545, "mapping 545", real_codes)

    pivot = m545.pivot_table(
        index=["country_iso2", "year"], columns="component", values="value", aggfunc="sum"
    )
    for col in ("net_exports", "net_imports"):
        if col not in pivot.columns:
            pivot[col] = pd.NA
    pivot = pivot.reset_index()

    has_either = pivot["net_exports"].notnull() | pivot["net_imports"].notnull()
    pivot["lng_net_bcm"] = pd.NA
    pivot.loc[has_either, "lng_net_bcm"] = pivot.loc[has_either, "net_exports"].fillna(
        0.0
    ) - pivot.loc[has_either, "net_imports"].fillna(0.0)

    return (
        pivot[["country_iso2", "year", "lng_net_bcm"]]
        .sort_values(["country_iso2", "year"])
        .reset_index(drop=True)
    )
