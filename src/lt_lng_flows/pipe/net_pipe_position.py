"""
net_pipe_position.py
---------------------
Session 6. ``net_pipe_bcm`` per country per year, from the IEA GTF border
flow file, for the surplus/deficit table's "known split" (beside the table,
never subtracted from it). European coverage only, since the GTF file's own
scope is European (and neighbouring) border points -- see
``dim_country.continent``, reused rather than a hand-maintained country
list.

Built from the raw monthly border-point rows (``read_gtf_border_flows``),
not from the already-aggregated ``fact_pipe_flow_hist`` (session 3), because
``fact_pipe_flow_hist`` aggregates months away and this session needs
``months_observed`` -- how many distinct calendar months actually fed a
country/year's net position -- to make incompleteness visible per the
session 6 task.
"""

from __future__ import annotations

import pandas as pd


def _resolve_countries(gtf_long: pd.DataFrame, applied_crosswalk: pd.DataFrame) -> pd.DataFrame:
    xwalk = applied_crosswalk[applied_crosswalk["source_system"] == "iea_gtf"]
    lookup = xwalk.set_index("raw_value")["country_iso2"]

    df = gtf_long.copy()
    df["origin_iso2"] = df["exit_raw"].map(lookup)
    df["destination_iso2"] = df["entry_raw"].map(lookup)

    unresolved_exit = df.loc[df["origin_iso2"].isnull(), "exit_raw"].unique()
    unresolved_entry = df.loc[df["destination_iso2"].isnull(), "entry_raw"].unique()
    if len(unresolved_exit) or len(unresolved_entry):
        raise ValueError(
            f"net_pipe_position: unresolved GTF Exit/Entry values -- "
            f"exit={sorted(unresolved_exit.tolist())}, entry={sorted(unresolved_entry.tolist())}"
        )
    return df


def build_net_pipe_position(
    gtf_long: pd.DataFrame,
    applied_crosswalk: pd.DataFrame,
    mm3_to_bcm: float,
    dim_country: pd.DataFrame,
    min_months_observed: int,
    netherlands_iso2: str,
    netherlands_excluded_from_year: int,
) -> pd.DataFrame:
    """country_iso2, year, net_pipe_bcm, months_observed. Restricted to real
    European countries in the output (``dim_country.continent == 'Europe'``)
    -- a non-European corridor endpoint (e.g. Algeria, Libya, Turkiye) still
    counts fully towards the European counterpart's own export/import total
    and month count, it is simply not itself reported as a row here, since
    GTF is only a physical border-flow record for its European corridors,
    not that country's whole pipe network.

    ``months_observed`` is the number of distinct calendar months in the
    pinned GTF file for which that country had a non-missing value on
    either side (exit or entry) of any corridor that year. A country-year
    with ``months_observed < min_months_observed`` gets ``net_pipe_bcm``
    set null -- excluded from the figure, per the session 6 task -- while
    ``months_observed`` itself is still reported, so the incompleteness is
    visible rather than silently absorbed. The Netherlands is additionally
    excluded for every year from ``netherlands_excluded_from_year`` onward
    regardless of its month count: its own GTF publication stopped in
    January 2019 (plan section 3), and residual rows from the other side of
    a corridor can pass the twelve-month test without the Dutch side's
    series being complete.
    """
    df = _resolve_countries(gtf_long, applied_crosswalk)
    df["bcm"] = df["value_mm3"] * mm3_to_bcm

    exports = (
        df.groupby(["origin_iso2", "year"], as_index=False)["bcm"]
        .sum()
        .rename(columns={"origin_iso2": "country_iso2", "bcm": "exports_bcm"})
    )
    imports = (
        df.groupby(["destination_iso2", "year"], as_index=False)["bcm"]
        .sum()
        .rename(columns={"destination_iso2": "country_iso2", "bcm": "imports_bcm"})
    )

    touches = pd.concat(
        [
            df[["origin_iso2", "year", "month_col"]].rename(
                columns={"origin_iso2": "country_iso2"}
            ),
            df[["destination_iso2", "year", "month_col"]].rename(
                columns={"destination_iso2": "country_iso2"}
            ),
        ],
        ignore_index=True,
    )
    months_observed = (
        touches.groupby(["country_iso2", "year"])["month_col"]
        .nunique()
        .rename("months_observed")
        .reset_index()
    )

    out = months_observed.merge(exports, on=["country_iso2", "year"], how="left").merge(
        imports, on=["country_iso2", "year"], how="left"
    )
    out["net_pipe_bcm"] = out["exports_bcm"].fillna(0.0) - out["imports_bcm"].fillna(0.0)

    incomplete = out["months_observed"] < min_months_observed
    nl_discontinued = (out["country_iso2"] == netherlands_iso2) & (
        out["year"] >= netherlands_excluded_from_year
    )
    out.loc[incomplete | nl_discontinued, "net_pipe_bcm"] = pd.NA

    european_codes = set(
        dim_country.loc[
            dim_country["is_real_country"] & (dim_country["continent"] == "Europe"),
            "country_iso2",
        ]
    )
    out = out[out["country_iso2"].isin(european_codes)]

    return (
        out[["country_iso2", "year", "net_pipe_bcm", "months_observed"]]
        .sort_values(["country_iso2", "year"])
        .reset_index(drop=True)
    )
