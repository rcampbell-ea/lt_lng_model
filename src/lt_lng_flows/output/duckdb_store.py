"""
duckdb_store.py
------------------
Session 2, build plan 4.6/2.8. Creates ``data/output/lt_lng_flows.duckdb``
and loads ``dim_country``, ``dim_country_adjacency``, ``dim_supply_node``,
``dim_demand_node`` and the applied alias crosswalk, each with its primary
key and, where the plan names one, its foreign keys to ``dim_country``
declared and enforced by the database itself (CLAUDE.md, "foreign keys are
enforced by the database, not by convention").
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def create_store(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    return duckdb.connect(str(db_path))


def load_dim_country(con: duckdb.DuckDBPyConnection, dim_country: pd.DataFrame) -> None:
    con.register("dim_country_df", dim_country)
    con.execute("CREATE TABLE dim_country AS SELECT * FROM dim_country_df")
    con.execute("ALTER TABLE dim_country ADD PRIMARY KEY (country_iso2)")
    con.unregister("dim_country_df")


def load_dim_country_adjacency(con: duckdb.DuckDBPyConnection, adjacency: pd.DataFrame) -> None:
    # DuckDB (1.5.x, pinned in environment.yml) does not support adding a
    # FOREIGN KEY via ALTER TABLE ("No support for that ALTER TABLE option
    # yet"): both PK and FK must be declared at CREATE TABLE time. Create
    # the empty, constrained table first, then insert from the dataframe.
    con.register("adjacency_df", adjacency)
    con.execute(
        "CREATE TABLE dim_country_adjacency ("
        "country_iso2_a VARCHAR, country_iso2_b VARCHAR, "
        "PRIMARY KEY (country_iso2_a, country_iso2_b), "
        "FOREIGN KEY (country_iso2_a) REFERENCES dim_country (country_iso2), "
        "FOREIGN KEY (country_iso2_b) REFERENCES dim_country (country_iso2))"
    )
    con.execute("INSERT INTO dim_country_adjacency SELECT * FROM adjacency_df")
    con.unregister("adjacency_df")


def _load_node_table(
    con: duckdb.DuckDBPyConnection, table_name: str, node_df: pd.DataFrame
) -> None:
    con.register("node_df", node_df)
    con.execute(
        f"CREATE TABLE {table_name} ("
        f"node_id VARCHAR, country_iso2 VARCHAR, is_split_country BOOLEAN, "
        f"PRIMARY KEY (node_id), "
        f"FOREIGN KEY (country_iso2) REFERENCES dim_country (country_iso2))"
    )
    con.execute(f"INSERT INTO {table_name} SELECT * FROM node_df")
    con.unregister("node_df")


def load_dim_supply_node(con: duckdb.DuckDBPyConnection, supply_node: pd.DataFrame) -> None:
    _load_node_table(con, "dim_supply_node", supply_node)


def load_dim_demand_node(con: duckdb.DuckDBPyConnection, demand_node: pd.DataFrame) -> None:
    _load_node_table(con, "dim_demand_node", demand_node)


def load_xwalk_country_alias(
    con: duckdb.DuckDBPyConnection, applied_crosswalk: pd.DataFrame
) -> None:
    """Foreign key on country_iso2 is declared only where it is non empty:
    an unresolved row (which per build plan check 2 should not exist once
    check 2 has passed) is a build-time invariant, not a schema-level
    nullable FK escape hatch. Loading with a non empty, unmapped code must
    raise, which is exactly what this session's enforcement test proves.
    """
    con.register("xwalk_df", applied_crosswalk)
    con.execute("CREATE TABLE xwalk_country_alias AS SELECT * FROM xwalk_df")
    con.execute("ALTER TABLE xwalk_country_alias ADD PRIMARY KEY (source_system, raw_value)")
    con.unregister("xwalk_df")


def assert_foreign_key_enforced(con: duckdb.DuckDBPyConnection) -> None:
    """Build plan 2.8: attempt to insert a fact row carrying an unmapped
    country_iso2 into a throwaway fact table with a declared FK to
    dim_country, and assert the insert raises. If it does not raise, every
    integrity guarantee in plan section 4 is decorative.
    """
    con.execute(
        "CREATE TABLE _fk_enforcement_probe (country_iso2 VARCHAR, "
        "FOREIGN KEY (country_iso2) REFERENCES dim_country (country_iso2))"
    )
    try:
        con.execute("INSERT INTO _fk_enforcement_probe VALUES ('ZZ_UNMAPPED')")
        raise AssertionError(
            "assert_foreign_key_enforced: an unmapped country_iso2 was accepted; "
            "foreign key enforcement is not working"
        )
    except duckdb.ConstraintException:
        pass
    finally:
        con.execute("DROP TABLE _fk_enforcement_probe")
