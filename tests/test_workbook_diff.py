"""Session 3, build plan 3.2: workbook_diff must report "no prior vintage
found" as a result, and must have a passing test against a synthetic second
vintage that exercises new/status-change/capacity-revision and
added/amended/expired logic -- the gate 3 named explicitly."""

from __future__ import annotations

import pandas as pd

from lt_lng_flows.ingest import workbook_diff


def test_diff_project_table_reports_no_prior_vintage():
    current = pd.DataFrame(
        {
            "country_raw": ["AO"],
            "project": ["Angola LNG"],
            "trains": ["Train 1"],
            "status": ["Active"],
        }
    )
    result = workbook_diff.diff_project_table(current, None)
    assert result == {"prior_vintage_found": False}


def test_diff_project_table_synthetic_second_vintage():
    prior = pd.DataFrame(
        {
            "country_raw": ["AO", "US"],
            "project": ["Angola LNG", "Sabine Pass"],
            "trains": ["Train 1", "Train 1-5"],
            "status": ["Active", "Under Construction"],
            "mtpa": [5.2, 27.0],
            "bcf_per_d": [0.68, 3.5],
            "bcma": [7.1, 36.0],
        }
    )
    current = pd.DataFrame(
        {
            "country_raw": ["AO", "US", "MZ"],
            "project": ["Angola LNG", "Sabine Pass", "Rovuma LNG"],
            "trains": ["Train 1", "Train 1-5", "Train 1"],
            # AO unchanged, US status advanced, MZ is new
            "status": ["Active", "Active", "Planned"],
            "mtpa": [5.2, 30.0, 3.4],
            "bcf_per_d": [0.68, 3.9, 0.4],
            "bcma": [7.1, 40.0, 4.5],
        }
    )
    result = workbook_diff.diff_project_table(current, prior)
    assert result["prior_vintage_found"] is True
    assert list(result["new_projects"]["project"]) == ["Rovuma LNG"]
    assert list(result["status_changes"]["project"]) == ["Sabine Pass"]
    assert result["status_changes"].iloc[0]["prior_status"] == "Under Construction"
    assert result["status_changes"].iloc[0]["current_status"] == "Active"
    revised_cols = set(result["capacity_revisions"]["column"])
    assert revised_cols == {"mtpa", "bcf_per_d", "bcma"}


def test_diff_contract_table_reports_no_prior_vintage():
    current = pd.DataFrame(
        {
            "exporter_raw": ["QA"],
            "importer_raw": ["JP"],
            "seller": ["QatarEnergy"],
            "buyer": ["Jera"],
            "contract_start": ["2020-01-01"],
            "status": ["Current"],
        }
    )
    result = workbook_diff.diff_contract_table(current, None)
    assert result == {"prior_vintage_found": False}


def test_diff_contract_table_added_amended_expired():
    prior = pd.DataFrame(
        {
            "exporter_raw": ["QA", "US"],
            "importer_raw": ["JP", "KR"],
            "seller": ["QatarEnergy", "Cheniere"],
            "buyer": ["Jera", "Kogas"],
            "contract_start": ["2020-01-01", "2018-01-01"],
            "status": ["Current", "Current"],
        }
    )
    current = pd.DataFrame(
        {
            "exporter_raw": ["QA", "US", "AU"],
            "importer_raw": ["JP", "KR", "CN"],
            "seller": ["QatarEnergy", "Cheniere", "Woodside"],
            "buyer": ["Jera", "Kogas", "Sinopec"],
            "contract_start": ["2020-01-01", "2018-01-01", "2024-01-01"],
            # Qatar->Japan contract amended (status changed), US->Korea expired
            # (absent from current), AU->China is newly added
            "status": ["Future", "Current", "Current"],
        }
    )
    # drop the US->KR row from current to simulate expiry
    current = current[current["exporter_raw"] != "US"].reset_index(drop=True)

    result = workbook_diff.diff_contract_table(current, prior)
    assert result["prior_vintage_found"] is True
    assert list(result["contracts_added"]["exporter_raw"]) == ["AU"]
    assert list(result["contracts_amended"]["exporter_raw"]) == ["QA"]
    assert list(result["contracts_expired"]["exporter_raw"]) == ["US"]


def test_find_prior_vintage_none_when_no_earlier_directory(tmp_path):
    (tmp_path / "202608").mkdir()
    (tmp_path / "202608" / "workbook.xlsx").write_bytes(b"x")
    result = workbook_diff.find_prior_vintage(tmp_path, "202608", "workbook.xlsx")
    assert result is None


def test_find_prior_vintage_finds_most_recent_earlier_directory(tmp_path):
    (tmp_path / "202606").mkdir()
    (tmp_path / "202606" / "workbook.xlsx").write_bytes(b"x")
    (tmp_path / "202607").mkdir()
    (tmp_path / "202607" / "workbook.xlsx").write_bytes(b"x")
    (tmp_path / "202608").mkdir()
    result = workbook_diff.find_prior_vintage(tmp_path, "202608", "workbook.xlsx")
    assert result == tmp_path / "202607" / "workbook.xlsx"
