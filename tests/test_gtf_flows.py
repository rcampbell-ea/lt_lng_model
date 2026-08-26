"""Session 3, build plan 3.3/3.4: GTF border flow reading and aggregation to
fact_pipe_flow_hist, plus the adjacency check, on small synthetic fixtures."""

from __future__ import annotations

import openpyxl
import pandas as pd
import pytest

from lt_lng_flows.pipe import gtf_flows
from lt_lng_flows.validate import pipe_checks


def _write_gtf_fixture(path, rows, months=("Oct-08", "Nov-08")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "GTF_data"
    header = ["Borderpoint", "Exit", "Entry", "MAXFLOW (Mm3/h)", *months]
    ws.append(header)
    for row in rows:
        ws.append(row)
    notes = wb.create_sheet("NOTES")
    notes.append(["placeholder"])
    wb.save(path)


def test_read_gtf_border_flows_skips_na_text_cells(tmp_path):
    path = tmp_path / "gtf.xlsx"
    _write_gtf_fixture(
        path,
        [["Test BP", "Austria", "Germany", 10.0, 5.0, "N/A"]],
    )
    long = gtf_flows.read_gtf_border_flows(path)
    assert len(long) == 1  # the N/A cell is skipped, not parsed
    assert long.iloc[0]["value_mm3"] == 5.0
    assert long.iloc[0]["year"] == 2008


def test_build_fact_pipe_flow_hist_aggregates_and_converts_units(tmp_path):
    path = tmp_path / "gtf.xlsx"
    _write_gtf_fixture(
        path,
        [
            ["BP1", "Austria", "Germany", 10.0, 100.0, 200.0],
            ["BP1_virtual", "Austria", "Germany", 10.0, 50.0, 0.0],
        ],
    )
    long = gtf_flows.read_gtf_border_flows(path)
    xwalk = pd.DataFrame(
        {
            "source_system": ["iea_gtf", "iea_gtf"],
            "raw_value": ["Austria", "Germany"],
            "country_iso2": ["AT", "DE"],
        }
    )
    fact = gtf_flows.build_fact_pipe_flow_hist(long, xwalk, mm3_to_bcm=0.001)
    assert set(fact["origin_iso2"]) == {"AT"}
    assert set(fact["destination_iso2"]) == {"DE"}
    # both border points aggregate to one AT->DE corridor per year
    row_2008 = fact[fact["year"] == 2008]
    assert len(row_2008) == 1
    # both months (Oct-08, Nov-08) and both border points sum into the one
    # 2008 AT->DE corridor row: (100+200) + (50+0) = 350 Mm3 -> 0.35 bcm
    assert row_2008.iloc[0]["bcm"] == pytest.approx((100.0 + 200.0 + 50.0 + 0.0) * 0.001)


def test_build_fact_pipe_flow_hist_raises_on_unresolved_country(tmp_path):
    path = tmp_path / "gtf.xlsx"
    _write_gtf_fixture(path, [["BP1", "Narnia", "Germany", 10.0, 100.0, 0.0]])
    long = gtf_flows.read_gtf_border_flows(path)
    xwalk = pd.DataFrame(
        {"source_system": ["iea_gtf"], "raw_value": ["Germany"], "country_iso2": ["DE"]}
    )
    with pytest.raises(ValueError, match="unresolved GTF"):
        gtf_flows.build_fact_pipe_flow_hist(long, xwalk, mm3_to_bcm=0.001)


def test_check_gtf_adjacency_passes_when_adjacency_present():
    fact = pd.DataFrame(
        {"origin_iso2": ["AT"], "destination_iso2": ["DE"], "year": [2020], "bcm": [1.0]}
    )
    adjacency = pd.DataFrame({"country_iso2_a": ["AT"], "country_iso2_b": ["DE"]})
    violations = pipe_checks.check_gtf_adjacency(fact, adjacency, real_country_codes={"AT", "DE"})
    assert violations == []


def test_check_gtf_adjacency_lists_violation_not_absorbed():
    fact = pd.DataFrame(
        {"origin_iso2": ["FR"], "destination_iso2": ["JP"], "year": [2020], "bcm": [1.0]}
    )
    adjacency = pd.DataFrame({"country_iso2_a": ["AT"], "country_iso2_b": ["DE"]})
    violations = pipe_checks.check_gtf_adjacency(fact, adjacency, real_country_codes={"FR", "JP"})
    assert violations == [{"origin_iso2": "FR", "destination_iso2": "JP"}]


def test_check_gtf_adjacency_excludes_pseudo_codes():
    # XL (Liquefied Natural Gas) is not in real_country_codes, so a flow
    # with XL as origin must never be reported as an adjacency violation.
    fact = pd.DataFrame(
        {"origin_iso2": ["XL"], "destination_iso2": ["ES"], "year": [2020], "bcm": [1.0]}
    )
    adjacency = pd.DataFrame({"country_iso2_a": [], "country_iso2_b": []})
    violations = pipe_checks.check_gtf_adjacency(fact, adjacency, real_country_codes={"ES"})
    assert violations == []
