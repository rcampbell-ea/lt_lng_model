"""
lng_net_position.py
--------------------
Session 8, STEP 5. Turns analyst pipeline assumptions into an LNG number --
the tool this session builds, not a number this session produces. As of
this session there are no analyst-entered flow values in
``config/pipeline_flows.yaml`` (session 8 STEP 1 stripped every one), so a
correct run of this module returns every country's LNG position null. That
is the correct output, not a bug to work around.

``lng_net_bcm = surplus_deficit_bcm - net_pipe_bcm``, per country per year
(plan 5.2's identity, with pipe already netted rather than split into
imports/exports). Null propagates: a null on either side of the subtraction
makes the result null, never a fabricated zero (CLAUDE.md, "a null beats a
plausible invented number") -- an incomplete corridor anywhere touching a
country makes that country's LNG position unknown, not zero.

Written at mapping 545's grain (plan section 10): ``net_exports_bcm`` and
``net_imports_bcm`` per country per year, in bcm, resolved from the single
derived ``lng_net_bcm`` by sign -- a positive balance is a net exporter that
year, a negative one a net importer. This does not reproduce mapping 545's
per-country dual-role split (5.7: a country can be a net exporter on its own
liquefaction row and a net importer on its own regas row in the same year);
the country-level balance identity here yields one net number per country
per year, so it resolves to exactly one of the two columns, with the other
held at 0.0 (not null -- the balance identity settles which side that
country is on that year, it does not leave the other side undetermined).
"""

from __future__ import annotations

import pandas as pd


def build_lng_net_position(
    fact_net_gas_position: pd.DataFrame, fact_pipe_net_position: pd.DataFrame
) -> pd.DataFrame:
    """country_iso2, year, lng_net_bcm, net_exports_bcm, net_imports_bcm,
    source. Joined on (country_iso2, year); a country/year present in one
    input but not the other carries a null lng_net_bcm rather than being
    silently dropped or treated as zero on the missing side."""
    merged = fact_net_gas_position[["country_iso2", "year", "surplus_deficit_bcm"]].merge(
        fact_pipe_net_position[["country_iso2", "year", "net_pipe_bcm"]],
        on=["country_iso2", "year"],
        how="outer",
    )

    has_both = merged["surplus_deficit_bcm"].notnull() & merged["net_pipe_bcm"].notnull()
    merged["lng_net_bcm"] = pd.NA
    merged.loc[has_both, "lng_net_bcm"] = (
        merged.loc[has_both, "surplus_deficit_bcm"] - merged.loc[has_both, "net_pipe_bcm"]
    )

    is_null = merged["lng_net_bcm"].isnull()
    is_export = ~is_null & (merged["lng_net_bcm"] > 0)
    is_import = ~is_null & (merged["lng_net_bcm"] <= 0)

    merged["net_exports_bcm"] = pd.NA
    merged["net_imports_bcm"] = pd.NA
    merged.loc[is_export, "net_exports_bcm"] = merged.loc[is_export, "lng_net_bcm"]
    merged.loc[is_export, "net_imports_bcm"] = 0.0
    merged.loc[is_import, "net_imports_bcm"] = -merged.loc[is_import, "lng_net_bcm"]
    merged.loc[is_import, "net_exports_bcm"] = 0.0

    merged["source"] = "derived_surplus_deficit_minus_net_pipe"

    return (
        merged[
            [
                "country_iso2",
                "year",
                "lng_net_bcm",
                "net_exports_bcm",
                "net_imports_bcm",
                "source",
            ]
        ]
        .sort_values(["country_iso2", "year"])
        .reset_index(drop=True)
    )
