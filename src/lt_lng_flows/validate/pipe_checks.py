"""
pipe_checks.py
---------------
Session 3, build plan 3.3. Validates ``fact_pipe_flow_hist`` against
``dim_country_adjacency`` (geometric adjacency plus the session 2
``adjacency_override.csv`` evidence, already unioned by build_session2 into
the parquet this reads): every corridor with a real country on both ends
must have adjacency or an explicit override row, or it is a data error per
build plan 4.3. Violations are listed, never silently absorbed
(``CLAUDE.md``, "fail loudly").

Pseudo codes (XL, "Liquefied Natural Gas" -- an LNG terminal delivering into
a country, not a land border; XN, "Not Elsewhere Specified") are excluded
from the adjacency requirement: a pseudo code has no border to be adjacent
across, exactly as ``adjacency.py`` already treats them in session 2.

Session 8, STEP 4 adds five checks over ``fact_pipe_net_position`` (session
7) and ``fact_net_gas_position`` (session 6), the checks the CA-US 264.8
bcma error should have failed before it ever reached the report. None of
these raises: each returns its list of violations, named with both
corridor/country and both numbers, for the caller to report or fail the
build on, per this module's existing "fail loudly, not silently" pattern.
"""

from __future__ import annotations

import pandas as pd


def check_gtf_adjacency(
    fact_pipe_flow_hist: pd.DataFrame,
    dim_country_adjacency: pd.DataFrame,
    real_country_codes: set[str],
) -> list[dict]:
    """Returns the list of violating (origin_iso2, destination_iso2) corridors
    -- real countries on both ends, present in fact_pipe_flow_hist, with
    neither geometric adjacency nor an override row. Does not raise: the
    session 3 gate is "passes or lists its violations", so the caller
    decides whether an empty list means PASS and a non-empty one is reported
    rather than silently absorbed.
    """
    pairs = set(map(tuple, dim_country_adjacency.values.tolist()))

    corridors = fact_pipe_flow_hist[["origin_iso2", "destination_iso2"]].drop_duplicates()
    violations = []
    for _, row in corridors.iterrows():
        origin, destination = row["origin_iso2"], row["destination_iso2"]
        if origin not in real_country_codes or destination not in real_country_codes:
            continue
        if origin == destination:
            continue
        if (origin, destination) not in pairs:
            violations.append({"origin_iso2": origin, "destination_iso2": destination})
    return violations


def check_export_within_supply(
    fact_pipe_net_position: pd.DataFrame, fact_net_gas_position: pd.DataFrame
) -> list[dict]:
    """4a. A net pipe *exporter* (``net_pipe_bcm`` positive) cannot export
    more than its own ``supply_bcm`` that year -- Canada at 264.8 bcma
    against a supply of 228.0 is exactly this: it implies Canada exporting
    more gas by pipe alone than it produces or receives in total. Rows with
    either value null are skipped -- an incomplete corridor or an unmodelled
    supply figure is not evidence of a violation, per CLAUDE.md ("a null
    beats a plausible invented number").
    """
    merged = fact_pipe_net_position.merge(
        fact_net_gas_position[["country_iso2", "year", "supply_bcm"]],
        on=["country_iso2", "year"],
        how="inner",
    )
    bad = merged[
        merged["net_pipe_bcm"].notnull()
        & merged["supply_bcm"].notnull()
        & (merged["net_pipe_bcm"] > merged["supply_bcm"])
    ]
    return [
        {
            "country_iso2": r["country_iso2"],
            "year": int(r["year"]),
            "net_pipe_bcm": r["net_pipe_bcm"],
            "supply_bcm": r["supply_bcm"],
        }
        for _, r in bad.iterrows()
    ]


def check_pipe_within_surplus(
    fact_pipe_net_position: pd.DataFrame, fact_net_gas_position: pd.DataFrame
) -> list[dict]:
    """4b. ``|net_pipe_bcm|`` cannot exceed ``|surplus_deficit_bcm|``. Pipe
    plus LNG equals the surplus (5.2's identity), so a country cannot move
    more gas by pipe alone than its whole supply-minus-demand position --
    this is the check that catches Canada, Tunisia and Norway all at once,
    each on the same corridor-magnitude mistake. Rows with either value
    null are skipped, same reasoning as 4a.
    """
    merged = fact_pipe_net_position.merge(
        fact_net_gas_position[["country_iso2", "year", "surplus_deficit_bcm"]],
        on=["country_iso2", "year"],
        how="inner",
    )
    bad = merged[
        merged["net_pipe_bcm"].notnull()
        & merged["surplus_deficit_bcm"].notnull()
        & (merged["net_pipe_bcm"].abs() > merged["surplus_deficit_bcm"].abs())
    ]
    return [
        {
            "country_iso2": r["country_iso2"],
            "year": int(r["year"]),
            "net_pipe_bcm": r["net_pipe_bcm"],
            "surplus_deficit_bcm": r["surplus_deficit_bcm"],
        }
        for _, r in bad.iterrows()
    ]


def check_transit_near_zero(
    fact_pipe_net_position: pd.DataFrame,
    fact_net_gas_position: pd.DataFrame,
    tolerance_bcm: float,
) -> list[dict]:
    """4c. Every corridor needs both legs; a transit country -- one with no
    domestic gas supply of its own (``supply_bcm`` null or ~0) -- can only
    pass gas through, so its net pipe position should sit within
    ``tolerance_bcm`` of zero. Tunisia at +21.4 with zero gas production is
    exactly a one-legged entry: TN-IT was entered without DZ-TN, so gas
    appears to originate in Tunisia rather than merely cross it. A
    transit country with a genuinely null (undecided) net_pipe_bcm is
    skipped -- an unresolved corridor is not evidence either way.
    """
    merged = fact_pipe_net_position.merge(
        fact_net_gas_position[["country_iso2", "year", "supply_bcm"]],
        on=["country_iso2", "year"],
        how="inner",
    )
    no_supply = merged["supply_bcm"].isnull() | (merged["supply_bcm"].abs() < tolerance_bcm)
    bad = merged[
        no_supply
        & merged["net_pipe_bcm"].notnull()
        & (merged["net_pipe_bcm"].abs() > tolerance_bcm)
    ]
    return [
        {
            "country_iso2": r["country_iso2"],
            "year": int(r["year"]),
            "net_pipe_bcm": r["net_pipe_bcm"],
            "supply_bcm": r["supply_bcm"],
        }
        for _, r in bad.iterrows()
    ]


def check_corridor_endpoints_adjacent(
    corridor_pairs: list[tuple[str, str]], dim_country_adjacency: pd.DataFrame
) -> list[tuple[str, str]]:
    """4d. Every corridor endpoint pair must be adjacent in
    ``dim_country_adjacency`` (geometric adjacency plus a signed-off
    ``crosswalks/adjacency_override.csv`` row for a named subsea link, e.g.
    Dolphin QA-AE) or it is a data error: a pipe cannot cross a border that
    is not there. This is the same rule ``check_gtf_adjacency`` (session 3)
    and ``pipe_flow_forecast.check_corridor_adjacency`` (session 7) already
    apply; this wrapper exists so session 8's report and its own fixture
    live beside the other STEP 4 checks rather than only in session 7's
    module.
    """
    from lt_lng_flows.pipe import pipe_flow_forecast as pff

    return pff.check_corridor_adjacency(corridor_pairs, dim_country_adjacency)


def check_global_pipe_closure(
    fact_pipe_net_position: pd.DataFrame, modelled_countries: list[str], tolerance_bcm: float
) -> list[dict]:
    """4e. Physical pipe gas is conserved: summed across every modelled
    country, net_pipe_bcm should sit within ``tolerance_bcm`` of zero each
    year (every exporter's outflow is some importer's inflow). Session 7
    summed to +48.8 -- a real leakage, not attributed to any named corridor.
    A year where any modelled country's net_pipe_bcm is null is skipped
    entirely rather than summed over the countries that do have a value:
    a partial sum reading as balanced (or as a small residual) would hide
    exactly the kind of gap this check exists to surface.
    """
    scoped = fact_pipe_net_position[fact_pipe_net_position["country_iso2"].isin(modelled_countries)]
    violations = []
    for year, grp in scoped.groupby("year"):
        countries_present = set(grp["country_iso2"])
        if countries_present != set(modelled_countries) or grp["net_pipe_bcm"].isnull().any():
            continue
        total = grp["net_pipe_bcm"].sum()
        if abs(total) > tolerance_bcm:
            violations.append({"year": int(year), "global_net_pipe_bcm": total})
    return violations
