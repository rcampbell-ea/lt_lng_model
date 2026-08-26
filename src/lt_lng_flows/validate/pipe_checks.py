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
