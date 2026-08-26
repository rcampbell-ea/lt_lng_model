"""
Unit test for lt_lng_flows.output.duckdb_store: the foreign key enforcement
proof required by build plan 2.8. If this does not raise, every integrity
guarantee in plan section 4 is decorative.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lt_lng_flows.output import duckdb_store


def test_foreign_key_rejects_unmapped_country(tmp_path):
    con = duckdb_store.create_store(tmp_path / "test.duckdb")
    try:
        dim_country = pd.DataFrame({"country_iso2": ["FR", "DE"]})
        duckdb_store.load_dim_country(con, dim_country)
        duckdb_store.assert_foreign_key_enforced(con)
    finally:
        con.close()


def test_node_table_rejects_unmapped_country(tmp_path):
    con = duckdb_store.create_store(tmp_path / "test2.duckdb")
    try:
        dim_country = pd.DataFrame({"country_iso2": ["QA"]})
        duckdb_store.load_dim_country(con, dim_country)
        supply_node = pd.DataFrame(
            {"node_id": ["qatar"], "country_iso2": ["QA"], "is_split_country": [False]}
        )
        duckdb_store.load_dim_supply_node(con, supply_node)

        import duckdb as duckdb_module

        with pytest.raises(duckdb_module.ConstraintException):
            con.execute("INSERT INTO dim_supply_node VALUES ('bad_node', 'ZZ', false)")
    finally:
        con.close()


def test_fact_liq_project_pk_and_fk(tmp_path):
    """Session 3, build plan 3.1."""
    con = duckdb_store.create_store(tmp_path / "test3.duckdb")
    try:
        dim_country = pd.DataFrame({"country_iso2": ["AO"]})
        duckdb_store.load_dim_country(con, dim_country)
        fact_liq_project = pd.DataFrame(
            {
                "liq_project_row_id": [1],
                "country_raw": ["Angola"],
                "country_iso2": ["AO"],
                "project": ["Angola LNG"],
                "status": ["Active"],
                "mtpa": [5.2],
            }
        )
        duckdb_store.load_fact_liq_project(con, fact_liq_project)
        assert con.execute("SELECT count(*) FROM fact_liq_project").fetchone()[0] == 1

        import duckdb as duckdb_module

        with pytest.raises(duckdb_module.ConstraintException):
            con.execute(
                "INSERT INTO fact_liq_project (liq_project_row_id, country_raw, country_iso2, "
                "project, status, mtpa) VALUES (2, 'Neverland', 'ZZ', 'x', 'Active', 1.0)"
            )
    finally:
        con.close()


def test_fact_pipe_flow_hist_pk_and_fk(tmp_path):
    """Session 3, build plan 3.3."""
    con = duckdb_store.create_store(tmp_path / "test4.duckdb")
    try:
        dim_country = pd.DataFrame({"country_iso2": ["AT", "DE"]})
        duckdb_store.load_dim_country(con, dim_country)
        fact_pipe_flow_hist = pd.DataFrame(
            {
                "origin_iso2": ["AT"],
                "destination_iso2": ["DE"],
                "year": [2020],
                "bcm": [1.5],
                "source": ["iea_gtf_202606"],
            }
        )
        duckdb_store.load_fact_pipe_flow_hist(con, fact_pipe_flow_hist)
        assert con.execute("SELECT count(*) FROM fact_pipe_flow_hist").fetchone()[0] == 1

        import duckdb as duckdb_module

        with pytest.raises(duckdb_module.ConstraintException):
            con.execute(
                "INSERT INTO fact_pipe_flow_hist VALUES ('AT', 'ZZ', 2021, 1.0, 'iea_gtf_202606')"
            )
    finally:
        con.close()


def test_fact_gas_balance_and_fact_lng_flow_baseline_load_empty(tmp_path):
    """Session 3, build plan 3.5/3.4c: an empty typed table loads cleanly
    when no pull has landed, per the ea_series.py/oilx_flows.py schemas."""
    from lt_lng_flows.ingest import ea_series, oilx_flows

    con = duckdb_store.create_store(tmp_path / "test5.duckdb")
    try:
        dim_country = pd.DataFrame({"country_iso2": ["FR"]})
        duckdb_store.load_dim_country(con, dim_country)
        duckdb_store.load_fact_gas_balance(con, ea_series._empty_fact_gas_balance())
        duckdb_store.load_fact_lng_flow_baseline(con, oilx_flows._empty_fact_lng_flow_baseline())
        assert con.execute("SELECT count(*) FROM fact_gas_balance").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM fact_lng_flow_baseline").fetchone()[0] == 0
    finally:
        con.close()
