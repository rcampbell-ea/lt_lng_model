"""Session 8: lng_net_bcm = surplus_deficit_bcm - net_pipe_bcm, on small
synthetic fixtures. Nulls propagate; never zero-filled."""

from __future__ import annotations

import pandas as pd
import pytest

from lt_lng_flows.model import lng_net_position as lnp


def _balance_row(country, year, surplus_deficit_bcm):
    return {"country_iso2": country, "year": year, "surplus_deficit_bcm": surplus_deficit_bcm}


def _pipe_row(country, year, net_pipe_bcm):
    return {"country_iso2": country, "year": year, "net_pipe_bcm": net_pipe_bcm}


def test_build_lng_net_position_computes_surplus_minus_pipe():
    balance = pd.DataFrame([_balance_row("DE", 2030, -90.0)])
    pipe = pd.DataFrame([_pipe_row("DE", 2030, -75.15)])
    out = lnp.build_lng_net_position(balance, pipe)
    row = out[(out["country_iso2"] == "DE") & (out["year"] == 2030)].iloc[0]
    assert row["lng_net_bcm"] == pytest.approx(-90.0 - (-75.15))
    assert row["net_imports_bcm"] == pytest.approx(90.0 - 75.15)
    assert row["net_exports_bcm"] == 0.0


def test_build_lng_net_position_positive_balance_is_a_net_exporter():
    balance = pd.DataFrame([_balance_row("QA", 2030, 100.0)])
    pipe = pd.DataFrame([_pipe_row("QA", 2030, 20.5)])
    out = lnp.build_lng_net_position(balance, pipe)
    row = out.iloc[0]
    assert row["lng_net_bcm"] == pytest.approx(79.5)
    assert row["net_exports_bcm"] == pytest.approx(79.5)
    assert row["net_imports_bcm"] == 0.0


def test_build_lng_net_position_null_pipe_makes_lng_net_null_not_zero():
    # This is the case that matters most this session: every corridor in
    # config/pipeline_flows.yaml is currently null (STEP 1), so every
    # country's derived LNG number must be null, not a fabricated figure.
    balance = pd.DataFrame([_balance_row("CA", 2030, 81.3)])
    pipe = pd.DataFrame([_pipe_row("CA", 2030, None)])
    out = lnp.build_lng_net_position(balance, pipe)
    row = out.iloc[0]
    assert pd.isna(row["lng_net_bcm"])
    assert pd.isna(row["net_exports_bcm"])
    assert pd.isna(row["net_imports_bcm"])


def test_build_lng_net_position_country_missing_from_one_side_is_null_not_dropped():
    balance = pd.DataFrame([_balance_row("JP", 2030, -50.0)])
    pipe = pd.DataFrame([_pipe_row("JP", 2030, 0.0)])
    balance_no_pipe = pd.DataFrame([_balance_row("XX", 2030, 10.0)])
    out = lnp.build_lng_net_position(pd.concat([balance, balance_no_pipe], ignore_index=True), pipe)
    xx = out[out["country_iso2"] == "XX"].iloc[0]
    assert pd.isna(xx["lng_net_bcm"])
