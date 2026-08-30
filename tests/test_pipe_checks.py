"""Session 8, STEP 4: fixtures for pipe_checks' five new validations, each
built to fail before the check existed -- the CA-US 264.8 bcma error (session
7) is used directly as the 4a/4b fixture, and Tunisia's TN-IT-without-DZ-TN
as the 4c fixture, per the session 8 task."""

from __future__ import annotations

import pandas as pd

from lt_lng_flows.validate import pipe_checks


def _pipe_row(country, year, net_pipe_bcm):
    return {"country_iso2": country, "year": year, "net_pipe_bcm": net_pipe_bcm, "basis": "assumed"}


def _balance_row(country, year, supply_bcm, surplus_deficit_bcm):
    return {
        "country_iso2": country,
        "year": year,
        "supply_bcm": supply_bcm,
        "surplus_deficit_bcm": surplus_deficit_bcm,
    }


def test_check_export_within_supply_flags_canada_style_overshoot():
    # Session 7's real numbers: Canada's 2030 net pipe export was 264.75 bcm
    # against a supply of 228.0 bcm -- exceeding its own total supply.
    pipe = pd.DataFrame([_pipe_row("CA", 2030, 264.75)])
    balance = pd.DataFrame([_balance_row("CA", 2030, 228.0, 81.3)])
    violations = pipe_checks.check_export_within_supply(pipe, balance)
    assert len(violations) == 1
    assert violations[0]["country_iso2"] == "CA"
    assert violations[0]["net_pipe_bcm"] == 264.75
    assert violations[0]["supply_bcm"] == 228.0


def test_check_export_within_supply_passes_when_export_within_supply():
    pipe = pd.DataFrame([_pipe_row("NO", 2030, 110.6)])
    balance = pd.DataFrame([_balance_row("NO", 2030, 120.0, 100.0)])
    assert pipe_checks.check_export_within_supply(pipe, balance) == []


def test_check_pipe_within_surplus_flags_canada_pipe_exceeding_whole_surplus():
    # Canada's 264.75 bcm net pipe export against an 81.3 bcm total surplus
    # implies Canada importing 183 bcm of LNG it never called for.
    pipe = pd.DataFrame([_pipe_row("CA", 2030, 264.75)])
    balance = pd.DataFrame([_balance_row("CA", 2030, 228.0, 81.3)])
    violations = pipe_checks.check_pipe_within_surplus(pipe, balance)
    assert len(violations) == 1
    assert violations[0]["net_pipe_bcm"] == 264.75
    assert violations[0]["surplus_deficit_bcm"] == 81.3


def test_check_pipe_within_surplus_passes_when_pipe_within_surplus():
    pipe = pd.DataFrame([_pipe_row("DE", 2030, -75.15)])
    balance = pd.DataFrame([_balance_row("DE", 2030, 10.0, -90.0)])
    assert pipe_checks.check_pipe_within_surplus(pipe, balance) == []


def test_check_transit_near_zero_flags_tunisia_one_legged_corridor():
    # TN-IT entered without DZ-TN: Tunisia nets +21.4 despite zero gas
    # production, which is impossible for a pure transit country.
    pipe = pd.DataFrame([_pipe_row("TN", 2030, 21.4)])
    balance = pd.DataFrame([_balance_row("TN", 2030, 0.0, None)])
    violations = pipe_checks.check_transit_near_zero(pipe, balance, tolerance_bcm=1.0)
    assert len(violations) == 1
    assert violations[0]["country_iso2"] == "TN"
    assert violations[0]["net_pipe_bcm"] == 21.4


def test_check_transit_near_zero_passes_when_both_legs_entered():
    pipe = pd.DataFrame([_pipe_row("TN", 2030, 0.2)])
    balance = pd.DataFrame([_balance_row("TN", 2030, 0.0, None)])
    assert pipe_checks.check_transit_near_zero(pipe, balance, tolerance_bcm=1.0) == []


def test_check_corridor_endpoints_adjacent_flags_non_adjacent_pair():
    adjacency = pd.DataFrame({"country_iso2_a": ["AT"], "country_iso2_b": ["DE"]})
    flagged = pipe_checks.check_corridor_endpoints_adjacent([("AT", "DE"), ("QA", "AE")], adjacency)
    assert flagged == [("QA", "AE")]


def test_check_global_pipe_closure_flags_session7_style_leakage():
    # A minimal two-country modelled set that nets to +10 bcm globally
    # instead of ~0 -- session 7's real global sum was +48.8.
    pipe = pd.DataFrame([_pipe_row("AT", 2030, 10.0), _pipe_row("DE", 2030, 0.0)])
    violations = pipe_checks.check_global_pipe_closure(
        pipe, modelled_countries=["AT", "DE"], tolerance_bcm=1.0
    )
    assert len(violations) == 1
    assert violations[0]["year"] == 2030
    assert violations[0]["global_net_pipe_bcm"] == 10.0


def test_check_global_pipe_closure_passes_when_balanced():
    pipe = pd.DataFrame([_pipe_row("AT", 2030, 10.0), _pipe_row("DE", 2030, -10.0)])
    violations = pipe_checks.check_global_pipe_closure(
        pipe, modelled_countries=["AT", "DE"], tolerance_bcm=1.0
    )
    assert violations == []


def test_check_global_pipe_closure_skips_year_with_any_null_component():
    pipe = pd.DataFrame([_pipe_row("AT", 2030, 10.0), _pipe_row("DE", 2030, None)])
    violations = pipe_checks.check_global_pipe_closure(
        pipe, modelled_countries=["AT", "DE"], tolerance_bcm=1.0
    )
    assert violations == []  # a partial sum reading as balanced must not be reported as PASS
