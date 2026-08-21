"""Fail-loudly behaviour of the session 1 ingest readers, on small synthetic
fixtures rather than the pinned snapshots, so these run without data/raw."""

from __future__ import annotations

import json

import openpyxl
import pytest

from lt_lng_flows.ingest import ea_cargo_tracking, ea_dataset_catalogue, workbook_reader


def _write_workbook(path, sheet_name, header_row_idx, header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for _ in range(header_row_idx - 1):
        ws.append([None])
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_read_workbook_raises_on_missing_header(tmp_path):
    path = tmp_path / "bad.xlsx"
    _write_workbook(
        path, "Global Liquefaction Database", 1, ["Region", "Country"], [["Africa", "Angola"]]
    )
    spec = workbook_reader.WORKBOOK_SPECS[0]
    with pytest.raises(ValueError, match="header row not found"):
        workbook_reader.read_workbook(path, spec)


def test_read_workbook_raises_on_blank_country_cell(tmp_path):
    path = tmp_path / "liq.xlsx"
    spec = workbook_reader.WORKBOOK_SPECS[0]
    header = list(spec.data_sheet.required_columns)
    row = [None] * len(header)
    row[header.index("Country")] = None
    row[header.index("ISO 2-letter code")] = "AO"
    _write_workbook(path, spec.data_sheet.sheet_name, 1, header, [row])
    with pytest.raises(ValueError, match="is empty inside the data range"):
        workbook_reader.read_workbook(path, spec)


def test_read_workbook_missing_data_sheet_raises(tmp_path):
    path = tmp_path / "wrongsheet.xlsx"
    spec = workbook_reader.WORKBOOK_SPECS[0]
    _write_workbook(path, "Some Other Sheet", 1, list(spec.data_sheet.required_columns), [])
    with pytest.raises(ValueError, match="expected data sheet"):
        workbook_reader.read_workbook(path, spec)


def test_ea_dataset_catalogue_missing_key_raises(tmp_path):
    path = tmp_path / "mappings.txt"
    path.write_text(
        json.dumps({"group": [{"mapping_id": 1, "name": "x", "dataset_ids": [1, 1, 2]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing keys"):
        ea_dataset_catalogue.read_ea_dataset_catalogue(path)


def test_ea_dataset_catalogue_dedup_and_report(tmp_path):
    path = tmp_path / "mappings.txt"
    path.write_text(
        json.dumps(
            {
                "group": [
                    {
                        "mapping_id": 1,
                        "name": "x",
                        "dataset_ids": [1, 1, 2],
                        "licensed": "yes",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalogue, dedup_report = ea_dataset_catalogue.read_ea_dataset_catalogue(path)
    assert len(catalogue) == 2
    assert dedup_report.iloc[0]["raw_count"] == 3
    assert dedup_report.iloc[0]["distinct_count"] == 2


def test_ea_cargo_tracking_rejects_non_success(tmp_path):
    path = tmp_path / "areas.txt"
    path.write_text(json.dumps({"data": [], "success": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="success"):
        ea_cargo_tracking.read_ea_ct_areas(path)


def test_ea_cargo_tracking_rejects_duplicate_country_in_area(tmp_path):
    path = tmp_path / "areas.txt"
    payload = {
        "data": [
            {
                "ID": 1,
                "Name": "Test Area",
                "SuezPosition": "East",
                "Countries": [
                    {"Code": "US", "Ports": [1]},
                    {"Code": "US", "Ports": [2]},
                ],
            }
        ],
        "success": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="more than once"):
        ea_cargo_tracking.read_ea_ct_areas(path)


def test_ea_cargo_tracking_handles_subcountry_shape(tmp_path):
    path = tmp_path / "ports.txt"
    payload = {
        "data": [
            {"Country": "CA", "Ports": [1, {"SubCountry": 6, "Ports": [2, 3]}]},
        ],
        "success": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    df, report = ea_cargo_tracking.read_ea_ct_country_ports(path)
    assert report["sub_country_objects"] == 1
    assert report["raw_port_list_entries"] == 2
    assert len(df) == 3
    assert df.loc[df["port_id"] == 1, "sub_country_id"].isnull().all()
    assert (df.loc[df["port_id"].isin([2, 3]), "sub_country_id"] == 6).all()


def test_ea_cargo_tracking_rejects_duplicate_pair(tmp_path):
    path = tmp_path / "ports.txt"
    payload = {"data": [{"Country": "CA", "Ports": [1, 1]}], "success": True}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        ea_cargo_tracking.read_ea_ct_country_ports(path)


def test_slugify_ascii_lower_snake_case():
    assert ea_cargo_tracking.slugify("Arctic Ocean & Barents Sea") == "arctic_ocean_barents_sea"
    assert ea_cargo_tracking.slugify("US Gulf") == "us_gulf"
