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
