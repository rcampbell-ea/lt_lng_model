"""Session 6: net_pipe_bcm and months_observed from the raw GTF monthly
file, on small synthetic fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from lt_lng_flows.pipe import net_pipe_position

XWALK = pd.DataFrame(
    {
        "source_system": ["iea_gtf"] * 3,
        "raw_value": ["Austria", "Germany", "Netherlands"],
        "country_iso2": ["AT", "DE", "NL"],
    }
)

DIM_COUNTRY = pd.DataFrame(
    {
        "country_iso2": ["AT", "DE", "NL", "US"],
        "is_real_country": [True, True, True, True],
        "continent": ["Europe", "Europe", "Europe", "Americas"],
    }
)


def _gtf_row(exit_raw, entry_raw, month_col, year, value_mm3):
    return {
        "borderpoint": "BP",
        "exit_raw": exit_raw,
        "entry_raw": entry_raw,
        "month_col": month_col,
        "year": year,
        "value_mm3": value_mm3,
    }


def test_build_net_pipe_position_computes_net_and_months_observed_when_complete():
    rows = [_gtf_row("Austria", "Germany", f"Jan-{i:02d}", 2020, 100.0) for i in range(12)]
    # give each row a distinct month_col so months_observed counts to 12
    for i, r in enumerate(rows):
        r["month_col"] = f"M{i:02d}"
    gtf_long = pd.DataFrame(rows)

    out = net_pipe_position.build_net_pipe_position(
        gtf_long,
        XWALK,
        mm3_to_bcm=0.001,
        dim_country=DIM_COUNTRY,
        min_months_observed=12,
        netherlands_iso2="NL",
        netherlands_excluded_from_year=2019,
    )

    at = out[out["country_iso2"] == "AT"].iloc[0]
    de = out[out["country_iso2"] == "DE"].iloc[0]
    assert at["months_observed"] == 12
    assert at["net_pipe_bcm"] == pytest.approx(12 * 100.0 * 0.001)  # AT is origin: exporter
    assert de["net_pipe_bcm"] == pytest.approx(-12 * 100.0 * 0.001)  # DE is destination: importer


def test_build_net_pipe_position_excludes_net_pipe_when_incomplete_but_keeps_months_observed():
    rows = [
        {
            "borderpoint": "BP",
            "exit_raw": "Austria",
            "entry_raw": "Germany",
            "month_col": f"M{i}",
            "year": 2020,
            "value_mm3": 100.0,
        }
        for i in range(3)  # only 3 distinct months
    ]
    gtf_long = pd.DataFrame(rows)

    out = net_pipe_position.build_net_pipe_position(
        gtf_long,
        XWALK,
        mm3_to_bcm=0.001,
        dim_country=DIM_COUNTRY,
        min_months_observed=12,
        netherlands_iso2="NL",
        netherlands_excluded_from_year=2019,
    )

    at = out[out["country_iso2"] == "AT"].iloc[0]
    assert at["months_observed"] == 3
    assert pd.isna(at["net_pipe_bcm"])  # excluded, but not silently dropped from the table


def test_build_net_pipe_position_excludes_netherlands_from_cutoff_year_regardless_of_months():
    months = [f"M{i}" for i in range(12)]
    rows_2018 = [
        {
            "borderpoint": "BP",
            "exit_raw": "Netherlands",
            "entry_raw": "Germany",
            "month_col": m,
            "year": 2018,
            "value_mm3": 100.0,
        }
        for m in months
    ]
    rows_2020 = [
        {
            "borderpoint": "BP",
            "exit_raw": "Netherlands",
            "entry_raw": "Germany",
            "month_col": m,
            "year": 2020,
            "value_mm3": 100.0,
        }
        for m in months
    ]
    gtf_long = pd.DataFrame(rows_2018 + rows_2020)

    out = net_pipe_position.build_net_pipe_position(
        gtf_long,
        XWALK,
        mm3_to_bcm=0.001,
        dim_country=DIM_COUNTRY,
        min_months_observed=12,
        netherlands_iso2="NL",
        netherlands_excluded_from_year=2019,
    )

    nl_2018 = out[(out["country_iso2"] == "NL") & (out["year"] == 2018)].iloc[0]
    nl_2020 = out[(out["country_iso2"] == "NL") & (out["year"] == 2020)].iloc[0]
    assert nl_2018["months_observed"] == 12
    assert not pd.isna(nl_2018["net_pipe_bcm"])
    assert nl_2020["months_observed"] == 12
    assert pd.isna(nl_2020["net_pipe_bcm"])  # excluded regardless of month completeness


def test_build_net_pipe_position_excludes_non_european_countries_from_output():
    gtf_long = pd.DataFrame(
        [
            {
                "borderpoint": "BP",
                "exit_raw": "Austria",
                "entry_raw": "Germany",
                "month_col": "M0",
                "year": 2020,
                "value_mm3": 100.0,
            }
        ]
    )
    extra = pd.DataFrame(
        {"source_system": ["iea_gtf"], "raw_value": ["USA"], "country_iso2": ["US"]}
    )
    xwalk = pd.concat([XWALK, extra], ignore_index=True)
    out = net_pipe_position.build_net_pipe_position(
        gtf_long,
        xwalk,
        mm3_to_bcm=0.001,
        dim_country=DIM_COUNTRY,
        min_months_observed=1,
        netherlands_iso2="NL",
        netherlands_excluded_from_year=2019,
    )
    assert "US" not in set(out["country_iso2"])
