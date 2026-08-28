"""Session 7: pipe_flow_forecast, on small synthetic fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from lt_lng_flows.pipe import pipe_flow_forecast as pff

REAL_COUNTRIES = {"AT", "DE", "NL", "RU", "UA"}


def _gtf_long_row(exit_raw, entry_raw, month_col, year, value_mm3=100.0):
    return {
        "borderpoint": "BP",
        "exit_raw": exit_raw,
        "entry_raw": entry_raw,
        "month_col": month_col,
        "year": year,
        "value_mm3": value_mm3,
    }


XWALK = pd.DataFrame(
    {
        "source_system": ["iea_gtf"] * 3,
        "raw_value": ["Austria", "Germany", "Russia"],
        "country_iso2": ["AT", "DE", "RU"],
    }
)


def test_corridor_months_observed_counts_distinct_months():
    rows = [_gtf_long_row("Austria", "Germany", f"M{i}", 2020) for i in range(6)]
    gtf_long = pd.DataFrame(rows)
    out = pff.corridor_months_observed(gtf_long, XWALK)
    row = out[(out["origin_iso2"] == "AT") & (out["year"] == 2020)].iloc[0]
    assert row["months_observed"] == 6


def _hist_row(origin, destination, year, bcm):
    return {"origin_iso2": origin, "destination_iso2": destination, "year": year, "bcm": bcm}


def test_project_measured_corridors_flat_default_uses_lookback_average():
    hist = pd.DataFrame(
        [_hist_row("AT", "DE", y, v) for y, v in zip([2022, 2023, 2024], [10.0, 20.0, 30.0])]
    )
    years_at = [2022, 2023, 2024]
    months = pd.DataFrame(
        [
            {"origin_iso2": "AT", "destination_iso2": "DE", "year": y, "months_observed": 12}
            for y in years_at
        ]
    )
    out, stale = pff.project_measured_corridors(
        hist,
        months,
        REAL_COUNTRIES,
        overrides=[],
        default_continuation={"path": "flat", "lookback_years": 3},
        horizon_end=2027,
        stale_year_threshold=2020,
    )
    assert stale == []
    measured = out[out["basis"] == "measured"]
    assert len(measured) == 3
    continuation = out[out["basis"] == "assumed"]
    assert set(continuation["year"]) == {2025, 2026, 2027}
    assert continuation["flow_bcm"].iloc[0] == pytest.approx((10 + 20 + 30) / 3)


def test_project_measured_corridors_excludes_pseudo_and_non_real_endpoints():
    hist = pd.DataFrame([_hist_row("AT", "DE", 2024, 10.0), _hist_row("XL", "DE", 2024, 999.0)])
    months = pd.DataFrame(
        [
            {"origin_iso2": "AT", "destination_iso2": "DE", "year": 2024, "months_observed": 12},
            {"origin_iso2": "XL", "destination_iso2": "DE", "year": 2024, "months_observed": 12},
        ]
    )
    out, _ = pff.project_measured_corridors(
        hist, months, REAL_COUNTRIES, [], {"path": "flat", "lookback_years": 3}, 2025, 2020
    )
    assert "XL" not in set(out["origin_iso2"])


def test_project_measured_corridors_stale_corridor_gets_no_continuation():
    years_ru_ua = [2017, 2018, 2019]
    hist = pd.DataFrame([_hist_row("RU", "UA", y, 90.0) for y in years_ru_ua])
    months = pd.DataFrame(
        [
            {"origin_iso2": "RU", "destination_iso2": "UA", "year": y, "months_observed": 12}
            for y in years_ru_ua
        ]
    )
    out, stale = pff.project_measured_corridors(
        hist,
        months,
        REAL_COUNTRIES,
        [],
        {"path": "flat", "lookback_years": 3},
        2050,
        stale_year_threshold=2024,
    )
    stale_expected = [{"origin_iso2": "RU", "destination_iso2": "UA", "last_observed_year": 2019}]
    assert stale == stale_expected
    # no flat-forever fabrication from a stale value
    assert out["year"].max() == 2019


def test_project_measured_corridors_override_lookback_wins_over_default():
    years_ru_de = [2020, 2021, 2022, 2023, 2024]
    values_ru_de = [10, 10, 10, 40, 40]
    hist = pd.DataFrame([_hist_row("RU", "DE", y, v) for y, v in zip(years_ru_de, values_ru_de)])
    months = pd.DataFrame(
        [
            {"origin_iso2": "RU", "destination_iso2": "DE", "year": y, "months_observed": 12}
            for y in years_ru_de
        ]
    )
    override = {"origin_iso2": "RU", "destination_iso2": "DE", "path": "flat", "lookback_years": 2}
    out, _ = pff.project_measured_corridors(
        hist, months, REAL_COUNTRIES, [override], {"path": "flat", "lookback_years": 3}, 2025, 2000
    )
    continuation = out[out["basis"] == "assumed"]
    # avg of last 2 years, not last 3
    assert continuation["flow_bcm"].iloc[0] == pytest.approx(40.0)


@pytest.mark.parametrize(
    "continuation,year,expected",
    [
        ({"path": "flat"}, 2040, 10.0),
        ({"path": "growing", "target_flow_bcma": 20.0, "target_year": 2030}, 2025, 10.0),
        ({"path": "growing", "target_flow_bcma": 20.0, "target_year": 2030}, 2030, 20.0),
        ({"path": "growing", "target_flow_bcma": 20.0, "target_year": 2030}, 2040, 20.0),
        ({"path": "terminating", "terminal_year": 2030}, 2030, 0.0),
        ({"path": "terminating", "terminal_year": 2030}, 2040, 0.0),
    ],
)
def test_value_at_year_paths(continuation, year, expected):
    assert pff._value_at_year(10.0, 2025, continuation, year) == pytest.approx(expected)


def test_value_at_year_growing_interpolates_linearly_between_anchor_and_target():
    continuation = {"path": "growing", "target_flow_bcma": 20.0, "target_year": 2030}
    mid = pff._value_at_year(10.0, 2025, continuation, 2027)  # 2 of 5 years in
    assert mid == pytest.approx(10.0 + (20.0 - 10.0) * 2 / 5)


def test_project_assumed_corridors_undecided_is_null_not_zero():
    corridors = [
        {
            "origin_iso2": "MZ",
            "destination_iso2": "ZA",
            "current_flow_bcma": None,
            "continuation": {"path": "undecided"},
            "note": "no bcm figure found",
        }
    ]
    out, undecided = pff.project_assumed_corridors(corridors, 2025, 2027)
    assert len(undecided) == 1
    assert out["flow_bcm"].isnull().all()
    assert (out["basis"] == "undecided").all()


def test_project_assumed_corridors_terminating_reaches_zero_and_stays():
    corridors = [
        {
            "origin_iso2": "IR",
            "destination_iso2": "IQ",
            "current_flow_bcma": 9.0,
            "basis_year": 2024,
            "continuation": {"path": "terminating", "terminal_year": 2027},
        }
    ]
    out, undecided = pff.project_assumed_corridors(corridors, 2025, 2030)
    assert undecided == []
    at_terminal = out[out["year"] == 2027]["flow_bcm"].iloc[0]
    after = out[out["year"] == 2030]["flow_bcm"].iloc[0]
    assert at_terminal == pytest.approx(0.0)
    assert after == pytest.approx(0.0)


def test_project_assumed_corridors_string_average_basis_year_anchors_at_end_year():
    corridors = [
        {
            "origin_iso2": "MM",
            "destination_iso2": "CN",
            "current_flow_bcma": 4.7,
            "basis_year": "2013-2023 average",
            "continuation": {"path": "declining", "target_flow_bcma": 2.0, "target_year": 2040},
        }
    ]
    out, _ = pff.project_assumed_corridors(corridors, 2025, 2040)
    v2025 = out[out["year"] == 2025]["flow_bcm"].iloc[0]
    v2040 = out[out["year"] == 2040]["flow_bcm"].iloc[0]
    assert v2025 < 4.7  # already declining by 2025, anchored at 2023 not 2025
    assert v2040 == pytest.approx(2.0)


def test_check_corridor_adjacency_flags_non_adjacent_pairs():
    adjacency = pd.DataFrame({"country_iso2_a": ["AT"], "country_iso2_b": ["DE"]})
    flagged = pff.check_corridor_adjacency([("AT", "DE"), ("QA", "AE")], adjacency)
    assert flagged == [("QA", "AE")]


def _corridor_row(origin, destination, year, flow_bcm, basis):
    return {
        "origin_iso2": origin,
        "destination_iso2": destination,
        "year": year,
        "flow_bcm": flow_bcm,
        "basis": basis,
    }


def test_net_country_position_computes_exports_minus_imports():
    corridors = pd.DataFrame(
        [
            _corridor_row("AT", "DE", 2025, 10.0, "measured"),
        ]
    )
    out = pff.net_country_position(
        corridors,
        modelled_countries=["AT", "DE"],
        zero_countries=[],
        horizon_start=2025,
        horizon_end=2025,
        history_start=2025,
    )
    at = out[out["country_iso2"] == "AT"].iloc[0]
    de = out[out["country_iso2"] == "DE"].iloc[0]
    assert at["net_pipe_bcm"] == pytest.approx(10.0)
    assert at["basis"] == "measured"
    assert de["net_pipe_bcm"] == pytest.approx(-10.0)


def test_net_country_position_basis_takes_least_certain_of_touching_corridors():
    corridors = pd.DataFrame(
        [
            _corridor_row("RU", "TR", 2025, 20.0, "measured"),
            _corridor_row("AZ", "TR", 2025, 6.0, "assumed"),
        ]
    )
    out = pff.net_country_position(
        corridors,
        modelled_countries=["TR"],
        zero_countries=[],
        horizon_start=2025,
        horizon_end=2025,
        history_start=2025,
    )
    tr = out[out["country_iso2"] == "TR"].iloc[0]
    assert tr["basis"] == "assumed"  # blend of measured + assumed is reported assumed, not measured


def test_net_country_position_null_component_makes_cell_null_not_zero():
    corridors = pd.DataFrame(
        [
            _corridor_row("MY", "SG", 2025, None, "undecided"),
        ]
    )
    out = pff.net_country_position(
        corridors,
        modelled_countries=["MY", "SG"],
        zero_countries=[],
        horizon_start=2025,
        horizon_end=2025,
        history_start=2025,
    )
    my = out[out["country_iso2"] == "MY"].iloc[0]
    assert pd.isna(my["net_pipe_bcm"])
    assert my["basis"] == "undecided"


def test_net_country_position_explicit_zero_for_untouched_country_on_zero_list():
    corridors = pd.DataFrame([_corridor_row("AT", "DE", 2025, 10.0, "measured")])
    out = pff.net_country_position(
        corridors,
        modelled_countries=["AT", "DE", "JP"],
        zero_countries=["JP"],
        horizon_start=2025,
        horizon_end=2025,
        history_start=2025,
    )
    jp = out[out["country_iso2"] == "JP"].iloc[0]
    assert jp["net_pipe_bcm"] == 0.0
    assert jp["basis"] == "explicit_zero"


def test_net_country_position_raises_on_untouched_country_not_in_zero_list():
    corridors = pd.DataFrame([_corridor_row("AT", "DE", 2025, 10.0, "measured")])
    with pytest.raises(ValueError, match="no corridor"):
        pff.net_country_position(
            corridors,
            modelled_countries=["AT", "DE", "JP"],
            zero_countries=[],  # JP untouched and not declared zero -- must raise
            horizon_start=2025,
            horizon_end=2025,
            history_start=2025,
        )
