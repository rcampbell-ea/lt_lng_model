"""
lt_region.py
------------
Session 3, build plan 3.6b/4.3b. ``lt_region`` in ``dim_country`` is derived
from the distinct ``(country_iso, region)`` pairs on the LT demand mappings
(314 and the eleven sector mappings 550-560), tested to be a partition
before it is trusted, never read from the API's own ``region`` field
wholesale (that field mixes geography, OECD, OPEC and Suez schemes, per plan
4.3b) and never filled from Natural Earth or the workbook region columns.

This needs the mapping-specific EA series pull (build plan 3.4/3.6), which
this session does not run. ``derive_lt_region`` therefore returns an
explicit "not derivable, snapshot missing" result rather than falling back
to any other source when the required mappings are absent from
``fact_gas_balance`` -- exactly the discipline plan 3.6b requires
("do not pick a winner, do not fall back... and do not fill from Natural
Earth"), extended to the case where there is no candidate data at all.

``dim_country_region_tag`` (every other EA grouping, key
(``country_iso2``, ``scheme``, ``tag_value``)) has the same dependency: it
is built from series metadata this session did not pull, so it is created
with its schema and left empty, same as ``dim_aggregate``.
"""

from __future__ import annotations

import pandas as pd

REGION_TAG_COLUMNS = ["country_iso2", "scheme", "tag_value"]

# Region mapping_ids named in plan 3.6b: total demand plus the eleven sector
# demand mappings.
LT_REGION_MAPPING_IDS = (314, 550, 551, 552, 553, 554, 555, 556, 557, 558, 559, 560)


def derive_lt_region(fact_gas_balance: pd.DataFrame, dim_country: pd.DataFrame) -> dict:
    """Returns a dict:
      - "derivable": bool
      - "reason": str, present when not derivable
      - "lt_region_by_country": {country_iso2: region} when derivable and a
        partition
      - "multi_valued_countries": {country_iso2: sorted(regions)} -- reported,
        left null in dim_country, never resolved by picking a winner
      - "missing_from_partition": sorted list of country_iso2 with a role_lng
        or role_pipe other than "none" but absent from the candidate set

    ``fact_gas_balance`` here would need a ``region``/``mapping_id`` column
    that the current ``ea_series.py`` schema does not carry (it carries
    ``component`` = the EA ``aspect`` field, not ``region``) -- because no
    live pull has happened to confirm the ``/timeseries/`` response actually
    surfaces ``region`` per series alongside ``country_iso``. So this
    function reports "not derivable" whenever the expected region column is
    absent, which is always true against the current ingestion path until
    that pull lands and a region-carrying loader is written against its
    real shape.
    """
    if fact_gas_balance.empty or "region" not in fact_gas_balance.columns:
        return {
            "derivable": False,
            "reason": (
                "no EA series snapshot with a 'region' field is available yet; "
                "mappings 314 and 550-560 have not been pulled "
                "(scripts/pull_ea_series.py has not been run for them this session)"
            ),
        }

    candidate = fact_gas_balance[fact_gas_balance["mapping_id"].isin(LT_REGION_MAPPING_IDS)]
    candidate = candidate[candidate["country_iso2"].notnull()]
    pairs = candidate[["country_iso2", "region"]].drop_duplicates()

    counts = pairs.groupby("country_iso2")["region"].nunique()
    multi_valued = sorted(counts[counts > 1].index)
    multi_valued_map = {
        code: sorted(pairs.loc[pairs["country_iso2"] == code, "region"].tolist())
        for code in multi_valued
    }

    single_valued = pairs[~pairs["country_iso2"].isin(multi_valued)]
    lt_region_by_country = dict(
        zip(single_valued["country_iso2"], single_valued["region"], strict=True)
    )

    relevant_codes = set(
        dim_country.loc[
            (dim_country["role_lng"] != "none") | (dim_country["role_pipe"] != "none"),
            "country_iso2",
        ]
    )
    covered = set(pairs["country_iso2"])
    missing_from_partition = sorted(relevant_codes - covered)

    return {
        "derivable": True,
        "lt_region_by_country": lt_region_by_country,
        "multi_valued_countries": multi_valued_map,
        "missing_from_partition": missing_from_partition,
    }


def empty_dim_country_region_tag() -> pd.DataFrame:
    return pd.DataFrame(columns=REGION_TAG_COLUMNS)
