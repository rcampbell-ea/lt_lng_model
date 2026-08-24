"""
Unit tests for lt_lng_flows.geo.node_master: split-country node generation
and the node-to-country capacity aggregation check (build plan 4.8 check 5).
"""

from __future__ import annotations

import pandas as pd
import pytest

from lt_lng_flows.geo import node_master

SPLIT_NODES = {"US": ["us_gulf", "us_east", "us_west", "us_alaska"], "CA": ["ca_east", "ca_west"]}


def _dim_country(rows):
    return pd.DataFrame(rows, columns=["country_iso2", "country_name_slug", "role_lng"])


def _capacity_row(source_system, project, country_raw, capacity):
    return {
        "source_system": source_system,
        "project": project,
        "country_raw": country_raw,
        "capacity": capacity,
    }


def _crosswalk_row(source_system, raw_value, country_iso2):
    return {"source_system": source_system, "raw_value": raw_value, "country_iso2": country_iso2}


def test_build_node_master_splits_named_countries_and_single_nodes_elsewhere():
    dim_country = _dim_country([("US", "united_states", "exporter"), ("QA", "qatar", "exporter")])
    nodes = node_master.build_node_master(dim_country, SPLIT_NODES)
    assert set(nodes.loc[nodes["country_iso2"] == "US", "node_id"]) == {
        "us_gulf",
        "us_east",
        "us_west",
        "us_alaska",
    }
    qa_rows = nodes[nodes["country_iso2"] == "QA"]
    assert list(qa_rows["node_id"]) == ["qatar"]
    assert qa_rows["is_split_country"].iloc[0] == False  # noqa: E712


def test_build_supply_node_filters_to_exporter_and_both():
    dim_country = _dim_country(
        [
            ("US", "united_states", "exporter"),
            ("JP", "japan", "importer"),
            ("SG", "singapore", "both"),
        ]
    )
    supply = node_master.build_supply_node(dim_country, SPLIT_NODES)
    assert set(supply["country_iso2"]) == {"US", "SG"}


def test_capacity_aggregation_passes_for_single_node_countries():
    capacity_rows = [
        _capacity_row("workbook_liquefaction", "Bonny", "Nigeria", 10.0),
        _capacity_row("workbook_liquefaction", "Ras Laffan", "Qatar", 20.0),
    ]
    applied_crosswalk = pd.DataFrame(
        [
            _crosswalk_row("workbook_liquefaction", "Nigeria", "NG"),
            _crosswalk_row("workbook_liquefaction", "Qatar", "QA"),
        ]
    )
    xwalk = node_master.build_xwalk_project_node_proposed(
        capacity_rows, applied_crosswalk, split_country_codes=set()
    )
    dim_country = pd.DataFrame(
        [
            {"country_iso2": "NG", "country_name_slug": "nigeria"},
            {"country_iso2": "QA", "country_name_slug": "qatar"},
        ]
    )
    xwalk_resolved = node_master.resolve_node_id_for_single_node_countries(xwalk, dim_country)
    node_master_df = pd.DataFrame(
        [
            {"node_id": "nigeria", "country_iso2": "NG"},
            {"node_id": "qatar", "country_iso2": "QA"},
        ]
    )
    report = node_master.check_node_country_capacity_aggregation(xwalk_resolved, node_master_df)
    assert report["countries_proven"] == ["NG", "QA"]
    assert report["countries_skipped_split"] == []
    assert report["skipped_capacity"] == 0.0


def test_capacity_aggregation_skips_split_countries_without_failing():
    capacity_rows = [
        _capacity_row("workbook_liquefaction", "Sabine Pass", "United States", 30.0),
        _capacity_row("workbook_liquefaction", "Bonny", "Nigeria", 10.0),
    ]
    applied_crosswalk = pd.DataFrame(
        [
            _crosswalk_row("workbook_liquefaction", "United States", "US"),
            _crosswalk_row("workbook_liquefaction", "Nigeria", "NG"),
        ]
    )
    xwalk = node_master.build_xwalk_project_node_proposed(
        capacity_rows, applied_crosswalk, split_country_codes={"US"}
    )
    dim_country = pd.DataFrame([{"country_iso2": "NG", "country_name_slug": "nigeria"}])
    xwalk_resolved = node_master.resolve_node_id_for_single_node_countries(xwalk, dim_country)
    node_master_df = pd.DataFrame([{"node_id": "nigeria", "country_iso2": "NG"}])
    report = node_master.check_node_country_capacity_aggregation(xwalk_resolved, node_master_df)
    assert report["countries_skipped_split"] == ["US"]
    assert report["skipped_capacity"] == 30.0
    assert report["skipped_capacity_share"] == pytest.approx(0.75)
