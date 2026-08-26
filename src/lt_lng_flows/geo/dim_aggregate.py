"""
dim_aggregate.py
------------------
Session 3, build plan 3.7/4.4. ``dim_aggregate``: EA's own published LT
dataset aggregates (EU, Other Europe, World, ...), taken as given from the
pulled metadata, with an explicit member list per aggregate. Not the
"Europe aggregate" demand-block node from the decisions register (a
separate, later, this-project's-own construct for the freight/allocation
layer) -- this table is EA's taxonomy only, and the two must not be
conflated (build plan 3.7).

No LT taxonomy pull (the mapping-specific EA series pull, build plan 3.4)
has landed as of this session, so member lists cannot be populated from
data. Per build plan 3.7 ("If the pull has not happened, create the schema
and leave the member lists empty, flagged"), this returns the schema with
zero rows and a report flag naming why -- never a hand-typed EU/Other
Europe membership from general knowledge, which would be exactly the kind
of unreviewed judgement CLAUDE.md's "null beats a plausible invented
number" rule exists to keep out.
"""

from __future__ import annotations

import pandas as pd

DIM_AGGREGATE_COLUMNS = ["aggregate_id", "aggregate_name", "member_country_iso2", "source"]


def empty_dim_aggregate() -> pd.DataFrame:
    return pd.DataFrame(columns=DIM_AGGREGATE_COLUMNS)
