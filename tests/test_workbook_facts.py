"""Session 3, build plan 3.1: fact table readers on small synthetic
fixtures, so row-count and distribution assertions are exercised without
data/raw. See ``tests/test_ingest.py`` for the fixture-writing convention
this follows."""

from __future__ import annotations

import openpyxl
import pandas as pd
import pytest

from lt_lng_flows.ingest import workbook_facts as wf


def _write_project_workbook(path, sheet_name, header_row_idx, header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for _ in range(header_row_idx - 1):
        ws.append([None])
    ws.append(header)
    for row in rows:
        ws.append(row)
    # trailing all-null rows, mimicking the ~3500-row sheet dimension trap
    for _ in range(20):
        ws.append([None] * len(header))
    wb.save(path)


def test_read_fact_liq_project_trims_trailing_blank_rows(tmp_path):
    path = tmp_path / "liq.xlsx"
    header = list(wf._PROJECT_COLUMN_MAP_LIQ.keys())
    row = [None] * len(header)

    def set_cell(name, value):
        row[header.index(name)] = value

    set_cell("Region", "Africa")
    set_cell("Country", "Angola")
    set_cell("ISO 2-letter code", "AO")
    set_cell("Project", "Angola LNG")
    set_cell("Trains", "Train 1")
    set_cell("Company", "Sonangol")
    set_cell("Start date", "2013-06")
    set_cell("Start Year", 2013)
    set_cell("MTPA", 5.2)
    set_cell("bcf/d", 0.68)
    set_cell("bcma", 7.1)
    set_cell("Status", "Active")
    set_cell("Type", "Baseload")

    _write_project_workbook(path, "Global Liquefaction Database", 4, header, [row])
    df = wf.read_fact_liq_project(path)
    assert len(df) == 1
    assert df.iloc[0]["country_raw"] == "Angola"
    assert df.iloc[0]["liq_project_row_id"] == 1


def test_read_fact_lng_contract_full_columns(tmp_path):
    path = tmp_path / "contracts.xlsx"
    header = list(wf._CONTRACT_COLUMN_MAP.keys())
    row = [None] * len(header)

    def set_cell(name, value):
        row[header.index(name)] = value

    set_cell("Export country", "Portfolio")
    set_cell("Import country", "Multiple")
    set_cell("Seller", "Shell")
    set_cell("Buyer", "Various")
    set_cell("bcm", 1.2)
    set_cell("Status", "Current")
    set_cell("Delivery type", "DES")
    set_cell("Destination flexibility", "Flexible")
    set_cell("Agreement Type", "SPA")

    _write_project_workbook(path, "Global LNG Contract Database", 3, header, [row])
    df = wf.read_fact_lng_contract(path)
    assert len(df) == 1
    assert df.iloc[0]["exporter_raw"] == "Portfolio"
    assert df.iloc[0]["importer_raw"] == "Multiple"
    assert df.attrs["header_row"] == 3


def test_assert_row_counts_raises_and_names_offender():
    constants = {
        "workbook_row_counts": {
            "liquefaction": {
                "sheet": "Global Liquefaction Database",
                "expected_rows": 2,
                "expected_countries": 1,
            },
            "regas": {
                "sheet": "Global Regas Database",
                "expected_rows": 1,
                "expected_countries": 1,
            },
            "contracts": {
                "sheet": "Global LNG Contract Database",
                "expected_rows": 1,
                "header_row": 3,
            },
        }
    }
    liq = pd.DataFrame({"country_raw": ["AO"]})  # 1 row, expected 2
    regas = pd.DataFrame({"country_raw": ["AO"]})
    contracts = pd.DataFrame({"exporter_raw": ["X"]})
    contracts.attrs["header_row"] = 3
    with pytest.raises(AssertionError, match="Global Liquefaction Database row count"):
        wf.assert_row_counts(liq, regas, contracts, constants)


def test_resolve_country_columns_raises_on_unmapped_value():
    df = pd.DataFrame({"country_raw": ["Neverland"]})
    xwalk = pd.DataFrame(
        {
            "source_system": ["workbook_liquefaction"],
            "raw_value": ["Angola"],
            "country_iso2": ["AO"],
        }
    )
    with pytest.raises(ValueError, match="no crosswalk entry"):
        wf.resolve_country_columns(
            df, "workbook_liquefaction", xwalk, {"country_raw": "country_iso2"}
        )


def test_resolve_country_columns_resolves_known_value():
    df = pd.DataFrame({"country_raw": ["Angola"]})
    xwalk = pd.DataFrame(
        {
            "source_system": ["workbook_liquefaction"],
            "raw_value": ["Angola"],
            "country_iso2": ["AO"],
        }
    )
    out = wf.resolve_country_columns(
        df, "workbook_liquefaction", xwalk, {"country_raw": "country_iso2"}
    )
    assert out.iloc[0]["country_iso2"] == "AO"
