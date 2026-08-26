"""
implied_pipe_diagnostic.py
----------------------------
Session 3, build plan 3.4d. Per country per year: ``net_gas_position``
(supply minus demand, from ``fact_gas_balance``) minus ``net_lng_position``
(exports minus imports, from ``fact_lng_flow_baseline``) gives an implied net
pipe position, reported against ``fact_pipe_flow_hist`` (GTF) where GTF has
country-pair coverage that year.

This is a **diagnostic for the session report, not a fact table** (build
plan 3.4d): it folds in own-use, losses and storage movements uncorrected,
and is expected to diverge from GTF for corridors GTF does not cover
(Russia into China) and for LNG-heavy importers where mapping 297's
marketed-vs-gross ambiguity (session 1 open question 3) amplifies. The
divergence is reported per country, never smoothed, and this module is never
a source ``fact_pipe_flow_hist`` is built from.

Both inputs are frequently empty in this session (neither the EA nor the
OilX pull has necessarily landed): the diagnostic runs and reports that
emptiness explicitly rather than skipping silently, per the session 3 gate
("the implied-pipe diagnostic runs and reports; empty-pending-pull is an
acceptable report, a silent skip is not").
"""

from __future__ import annotations

import pandas as pd


def compute_net_gas_position(fact_gas_balance: pd.DataFrame) -> pd.DataFrame:
    """net_gas_position = supply - demand, per (country_iso2, year), using
    the raw EA ``aspect`` component names ``supply`` and ``demand`` (see
    ``ea_series.py`` docstring on why components are not yet remapped onto
    the plan 5.2 identity term names). Countries or years missing either
    component are excluded, not zero-filled.

    Filters to ``category == "natural_gas"``: mapping 314 ("Long term total
    demand") carries "demand" as the ``aspect`` for oil_products, NGLs and
    liquids too, in kb/d rather than bcm. Without this filter, summing
    "demand" would mix incompatible units and categories into one number --
    caught before it could reach the diagnostic against a real pull (see
    docs/session_03_ingestion.md).
    """
    if fact_gas_balance.empty:
        return pd.DataFrame(columns=["country_iso2", "year", "net_gas_position_bcm"])

    relevant = fact_gas_balance[
        fact_gas_balance["component"].isin(["supply", "demand"])
        & (fact_gas_balance["category"] == "natural_gas")
        & fact_gas_balance["country_iso2"].notnull()
    ]
    pivot = relevant.pivot_table(
        index=["country_iso2", "year"], columns="component", values="value", aggfunc="sum"
    )
    if "supply" not in pivot.columns or "demand" not in pivot.columns:
        return pd.DataFrame(columns=["country_iso2", "year", "net_gas_position_bcm"])
    pivot = pivot.dropna(subset=["supply", "demand"])
    pivot["net_gas_position_bcm"] = pivot["supply"] - pivot["demand"]
    return pivot.reset_index()[["country_iso2", "year", "net_gas_position_bcm"]]


def compute_net_lng_position(fact_lng_flow_baseline: pd.DataFrame) -> pd.DataFrame:
    """net_lng_position = exports (sum as origin) - imports (sum as
    destination), per (country_iso2, year), in bcm. Returns empty if
    ``bcm`` is not populated (open per plan 3.2c/session 1 question 6 until
    the volume unit is confirmed against a live response -- see
    ``oilx_flows.py``).
    """
    if fact_lng_flow_baseline.empty or fact_lng_flow_baseline["bcm"].isnull().all():
        return pd.DataFrame(columns=["country_iso2", "year", "net_lng_position_bcm"])

    df = fact_lng_flow_baseline.dropna(subset=["bcm"])
    exports = df.groupby(["origin_iso2", "year"])["bcm"].sum().rename("exports_bcm")
    imports = df.groupby(["destination_iso2", "year"])["bcm"].sum().rename("imports_bcm")
    exports.index.names = ["country_iso2", "year"]
    imports.index.names = ["country_iso2", "year"]
    combined = pd.concat([exports, imports], axis=1).fillna(0.0)
    combined["net_lng_position_bcm"] = combined["exports_bcm"] - combined["imports_bcm"]
    return combined.reset_index()[["country_iso2", "year", "net_lng_position_bcm"]]


def compute_implied_pipe_diagnostic(
    fact_gas_balance: pd.DataFrame,
    fact_lng_flow_baseline: pd.DataFrame,
    fact_pipe_flow_hist: pd.DataFrame,
    large_divergence_bcm: float,
) -> dict:
    """Returns a dict:
      - "net_gas_position": DataFrame
      - "net_lng_position": DataFrame
      - "diagnostic": DataFrame with country_iso2, year, implied_net_pipe_bcm,
        gtf_net_pipe_bcm (None where GTF has no coverage that country/year),
        divergence_bcm, is_large_divergence
      - "inputs_empty": {"gas_balance": bool, "lng_flow_baseline": bool}
    so the caller can report "empty pending pull" explicitly rather than
    silently producing zero rows.
    """
    net_gas = compute_net_gas_position(fact_gas_balance)
    net_lng = compute_net_lng_position(fact_lng_flow_baseline)

    inputs_empty = {
        "gas_balance": net_gas.empty,
        "lng_flow_baseline": net_lng.empty,
    }

    if net_gas.empty or net_lng.empty:
        return {
            "net_gas_position": net_gas,
            "net_lng_position": net_lng,
            "diagnostic": pd.DataFrame(
                columns=[
                    "country_iso2",
                    "year",
                    "implied_net_pipe_bcm",
                    "gtf_net_pipe_bcm",
                    "divergence_bcm",
                    "is_large_divergence",
                ]
            ),
            "inputs_empty": inputs_empty,
        }

    merged = net_gas.merge(net_lng, on=["country_iso2", "year"], how="inner")
    merged["implied_net_pipe_bcm"] = merged["net_gas_position_bcm"] - merged["net_lng_position_bcm"]

    if fact_pipe_flow_hist.empty:
        gtf_net = pd.DataFrame(columns=["country_iso2", "year", "gtf_net_pipe_bcm"])
    else:
        exports = (
            fact_pipe_flow_hist.groupby(["origin_iso2", "year"])["bcm"].sum().rename("pipe_exports")
        )
        imports = (
            fact_pipe_flow_hist.groupby(["destination_iso2", "year"])["bcm"]
            .sum()
            .rename("pipe_imports")
        )
        exports.index.names = ["country_iso2", "year"]
        imports.index.names = ["country_iso2", "year"]
        gtf_net = pd.concat([exports, imports], axis=1).fillna(0.0)
        gtf_net["gtf_net_pipe_bcm"] = gtf_net["pipe_exports"] - gtf_net["pipe_imports"]
        gtf_net = gtf_net.reset_index()[["country_iso2", "year", "gtf_net_pipe_bcm"]]

    diagnostic = merged.merge(gtf_net, on=["country_iso2", "year"], how="left")
    diagnostic["divergence_bcm"] = (
        diagnostic["implied_net_pipe_bcm"] - diagnostic["gtf_net_pipe_bcm"]
    )
    diagnostic["is_large_divergence"] = diagnostic["divergence_bcm"].abs() >= large_divergence_bcm

    return {
        "net_gas_position": net_gas,
        "net_lng_position": net_lng,
        "diagnostic": diagnostic,
        "inputs_empty": inputs_empty,
    }
