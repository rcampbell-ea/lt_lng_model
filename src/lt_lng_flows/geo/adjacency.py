"""
adjacency.py
--------------
Session 2, build plan 4.3/2.5. Proposes ``crosswalks/adjacency_override.csv``
from evidence in the IEA GTF file: a border point whose Exit and Entry
countries resolve to two real, distinct countries that are not geometrically
adjacent is a named pipeline connection the boundary geometry cannot show
(a subsea line, or a connection routed through a third country's territory
without touching it administratively). Every row is evidenced by a specific
GTF border point name; nothing is invented. Pseudo codes (XL, "Liquefied
Natural Gas", is the one seen in practice as an Exit/Entry value) are
excluded, because a pseudo code has no border to be adjacent across.

The override rows are unioned into the geometric adjacency to produce the
final, applied ``dim_country_adjacency`` -- unlike the alias crosswalk and
the port candidates, this file is direct evidence from a pinned source
rather than a proposal needing a human's independent judgement, so it does
not gate on a sign-off step.
"""

from __future__ import annotations

import pandas as pd


def build_adjacency_override(
    gtf_border_pairs: list[dict],
    applied_crosswalk: pd.DataFrame,
    geometric_adjacency: pd.DataFrame,
    real_country_codes: set[str],
) -> pd.DataFrame:
    xwalk_map = {
        (row["source_system"], row["raw_value"]): row["country_iso2"]
        for _, row in applied_crosswalk[applied_crosswalk["source_system"] == "iea_gtf"].iterrows()
    }
    adjacent_pairs = set(map(tuple, geometric_adjacency.values.tolist()))

    seen: dict[tuple[str, str], str] = {}
    for record in gtf_border_pairs:
        exit_code = xwalk_map.get(("iea_gtf", record["exit_raw"]))
        entry_code = xwalk_map.get(("iea_gtf", record["entry_raw"]))
        if exit_code is None or entry_code is None:
            raise ValueError(
                f"build_adjacency_override: unresolved GTF raw value in border point "
                f"{record['borderpoint']!r}: exit={record['exit_raw']!r} "
                f"entry={record['entry_raw']!r}"
            )
        if exit_code not in real_country_codes or entry_code not in real_country_codes:
            continue
        if exit_code == entry_code:
            continue
        if (exit_code, entry_code) in adjacent_pairs:
            continue
        key = tuple(sorted((exit_code, entry_code)))
        seen.setdefault(key, record["borderpoint"])

    rows = [
        {
            "country_iso2_a": a,
            "country_iso2_b": b,
            "reason": "named_pipeline_border_point_no_shared_land_border",
            "source": "iea_gtf",
            "note": f"GTF border point {borderpoint!r}: Exit/Entry countries resolve to "
            f"{a}/{b}, which do not share a geometric land border at 1:50m resolution",
        }
        for (a, b), borderpoint in sorted(seen.items())
    ]
    return pd.DataFrame(
        rows, columns=["country_iso2_a", "country_iso2_b", "reason", "source", "note"]
    )


def apply_adjacency_override(
    geometric_adjacency: pd.DataFrame, override: pd.DataFrame
) -> pd.DataFrame:
    """Union the geometric adjacency with the override rows, symmetric both
    ways.
    """
    override_pairs = set()
    for _, row in override.iterrows():
        override_pairs.add((row["country_iso2_a"], row["country_iso2_b"]))
        override_pairs.add((row["country_iso2_b"], row["country_iso2_a"]))

    combined = set(map(tuple, geometric_adjacency.values.tolist())) | override_pairs
    return pd.DataFrame(sorted(combined), columns=["country_iso2_a", "country_iso2_b"])
