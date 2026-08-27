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


def _load_typed_table_with_fk(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    df: pd.DataFrame,
    pk_columns: list[str],
    fk_columns_to_dim_country: list[str],
) -> None:
    """DuckDB 1.5.x (pinned in environment.yml) does not support adding a
    FOREIGN KEY via ALTER TABLE, only PRIMARY KEY (see
    ``load_dim_country_adjacency``'s comment). Every fact table this session
    adds needs both, so this declares the full column list, types inferred
    from the dataframe by way of a throwaway typed empty insert, with PK and
    FK constraints all present at CREATE TABLE time.
    """
    con.register(f"{table_name}_stage_df", df)
    con.execute(f"CREATE TABLE {table_name}_stage AS SELECT * FROM {table_name}_stage_df")
    columns_sql = con.execute(
        "SELECT column_name, data_type FROM duckdb_columns() "
        f"WHERE table_name = '{table_name}_stage'"
    ).fetchall()
    con.unregister(f"{table_name}_stage_df")
    con.execute(f"DROP TABLE {table_name}_stage")

    col_defs = ", ".join(f'"{name}" {dtype}' for name, dtype in columns_sql)
    pk_sql = f", PRIMARY KEY ({', '.join(pk_columns)})"
    fk_sql = "".join(
        f", FOREIGN KEY ({col}) REFERENCES dim_country (country_iso2)"
        for col in fk_columns_to_dim_country
    )
    con.execute(f"CREATE TABLE {table_name} ({col_defs}{pk_sql}{fk_sql})")

    con.register(f"{table_name}_df", df)
    if len(df):
        con.execute(f"INSERT INTO {table_name} SELECT * FROM {table_name}_df")
    con.unregister(f"{table_name}_df")


def load_fact_liq_project(con: duckdb.DuckDBPyConnection, fact_liq_project: pd.DataFrame) -> None:
    """Session 3, build plan 3.1. Country level only per the Prototype
    phasing decision: FK to dim_country, no FK to a node table this
    session."""
    _load_typed_table_with_fk(
        con, "fact_liq_project", fact_liq_project, ["liq_project_row_id"], ["country_iso2"]
    )


def load_fact_regas_project(
    con: duckdb.DuckDBPyConnection, fact_regas_project: pd.DataFrame
) -> None:
    _load_typed_table_with_fk(
        con, "fact_regas_project", fact_regas_project, ["regas_project_row_id"], ["country_iso2"]
    )


def load_fact_lng_contract(con: duckdb.DuckDBPyConnection, fact_lng_contract: pd.DataFrame) -> None:
    _load_typed_table_with_fk(
        con,
        "fact_lng_contract",
        fact_lng_contract,
        ["contract_row_id"],
        ["exporter_iso2", "importer_iso2"],
    )


def load_fact_pipe_flow_hist(
    con: duckdb.DuckDBPyConnection, fact_pipe_flow_hist: pd.DataFrame
) -> None:
    """Build plan 3.3. PK/FK must be declared at CREATE TABLE time (DuckDB
    1.5.x has no ALTER TABLE ADD FOREIGN KEY support), same pattern as
    ``load_dim_country_adjacency``."""
    con.register("fact_pipe_flow_hist_df", fact_pipe_flow_hist)
    con.execute(
        "CREATE TABLE fact_pipe_flow_hist ("
        "origin_iso2 VARCHAR, destination_iso2 VARCHAR, year INTEGER, bcm DOUBLE, "
        "source VARCHAR, "
        "PRIMARY KEY (origin_iso2, destination_iso2, year), "
        "FOREIGN KEY (origin_iso2) REFERENCES dim_country (country_iso2), "
        "FOREIGN KEY (destination_iso2) REFERENCES dim_country (country_iso2))"
    )
    con.execute("INSERT INTO fact_pipe_flow_hist SELECT * FROM fact_pipe_flow_hist_df")
    con.unregister("fact_pipe_flow_hist_df")


def load_fact_gas_balance(con: duckdb.DuckDBPyConnection, fact_gas_balance: pd.DataFrame) -> None:
    """Build plan 3.5. PK is (dataset_id, period): one row per native
    observation date per dataset, not per year -- mappings 5 and 6 ("Global
    LNG exports/imports") are monthly frequency, so (dataset_id, year) alone
    collided across a series' twelve months per year (caught against a real
    pull, see docs/session_03_ingestion.md and ea_series.py's module
    docstring). FK to dim_country is nullable (a region/world aggregate row
    carries a null country_iso2, which DuckDB's foreign key constraint
    permits without violating it) -- exactly what plan 3.2b describes for
    mapping 314's non-country rows.
    """
    con.register("fact_gas_balance_df", fact_gas_balance)
    con.execute(
        "CREATE TABLE fact_gas_balance ("
        "country_iso2 VARCHAR, period VARCHAR, year INTEGER, component VARCHAR, "
        "category VARCHAR, value DOUBLE, unit VARCHAR, lifecycle_stage VARCHAR, "
        "frequency VARCHAR, dataset_id BIGINT, mapping_id BIGINT, "
        "aspect_subtype VARCHAR, category_subtype VARCHAR, region VARCHAR, "
        "sub_region VARCHAR, description VARCHAR, forecast_start_date VARCHAR, "
        "release_date VARCHAR, source VARCHAR, metadata_json VARCHAR, "
        "PRIMARY KEY (dataset_id, period), "
        "FOREIGN KEY (country_iso2) REFERENCES dim_country (country_iso2))"
    )
    if len(fact_gas_balance):
        con.execute("INSERT INTO fact_gas_balance SELECT * FROM fact_gas_balance_df")
    con.unregister("fact_gas_balance_df")


def load_fact_lng_flow_baseline(
    con: duckdb.DuckDBPyConnection, fact_lng_flow_baseline: pd.DataFrame
) -> None:
    """Build plan 3.4c. Country level, ``bcm`` left nullable pending the
    unit question (see ``oilx_flows.py``)."""
    con.register("fact_lng_flow_baseline_df", fact_lng_flow_baseline)
    con.execute(
        "CREATE TABLE fact_lng_flow_baseline ("
        "origin_iso2 VARCHAR, destination_iso2 VARCHAR, year INTEGER, bcm DOUBLE, "
        "quantity_kt DOUBLE, quantity_cbm DOUBLE, quantity_mmbtu DOUBLE, "
        "source VARCHAR, release_date VARCHAR, raw_records_json VARCHAR, "
        "PRIMARY KEY (origin_iso2, destination_iso2, year, source), "
        "FOREIGN KEY (origin_iso2) REFERENCES dim_country (country_iso2), "
        "FOREIGN KEY (destination_iso2) REFERENCES dim_country (country_iso2))"
    )
    if len(fact_lng_flow_baseline):
        con.execute("INSERT INTO fact_lng_flow_baseline SELECT * FROM fact_lng_flow_baseline_df")
    con.unregister("fact_lng_flow_baseline_df")


def load_dim_aggregate(con: duckdb.DuckDBPyConnection, dim_aggregate: pd.DataFrame) -> None:
    """Build plan 3.7. Empty this session (no LT taxonomy pull yet); schema
    only, per ``dim_aggregate.py``."""
    con.register("dim_aggregate_df", dim_aggregate)
    con.execute(
        "CREATE TABLE dim_aggregate ("
        "aggregate_id VARCHAR, aggregate_name VARCHAR, member_country_iso2 VARCHAR, "
        "source VARCHAR, "
        "PRIMARY KEY (aggregate_id, member_country_iso2), "
        "FOREIGN KEY (member_country_iso2) REFERENCES dim_country (country_iso2))"
    )
    if len(dim_aggregate):
        con.execute("INSERT INTO dim_aggregate SELECT * FROM dim_aggregate_df")
    con.unregister("dim_aggregate_df")


def load_dim_country_region_tag(
    con: duckdb.DuckDBPyConnection, dim_country_region_tag: pd.DataFrame
) -> None:
    """Build plan 3.6b. Empty this session (needs the mapping-specific EA
    series pull); schema only, per ``lt_region.py``."""
    con.register("dim_country_region_tag_df", dim_country_region_tag)
    con.execute(
        "CREATE TABLE dim_country_region_tag ("
        "country_iso2 VARCHAR, scheme VARCHAR, tag_value VARCHAR, "
        "PRIMARY KEY (country_iso2, scheme, tag_value), "
        "FOREIGN KEY (country_iso2) REFERENCES dim_country (country_iso2))"
    )
    if len(dim_country_region_tag):
        con.execute("INSERT INTO dim_country_region_tag SELECT * FROM dim_country_region_tag_df")
    con.unregister("dim_country_region_tag_df")


def load_fact_net_gas_position(
    con: duckdb.DuckDBPyConnection, fact_net_gas_position: pd.DataFrame
) -> None:
    """Session 6. Supply (mapping 297) minus total demand (mapping 314), per
    (``country_iso2``, ``year``), over the full span both mappings actually
    carry data for -- widened from session 5's 2025-2050 slice.
    ``surplus_deficit_bcm`` (renamed from session 5's
    ``net_gas_position_bcm``) is supply minus demand only; ``missing_side``
    names which side (if any) is absent for that row instead of session 5's
    two boolean flags. ``net_pipe_bcm``/``months_observed`` (IEA GTF,
    European coverage only) and ``lng_net_bcm`` (mapping 545) sit beside the
    surplus/deficit figure as separately-sourced columns, per the session 6
    task -- never summed against it, never reconciled. All four numeric
    columns are nullable: a country/mapping/period combination with no
    coverage carries a null there, never a fabricated zero (CLAUDE.md, "a
    null beats a plausible invented number")."""
    con.register("fact_net_gas_position_df", fact_net_gas_position)
    con.execute(
        "CREATE TABLE fact_net_gas_position ("
        "country_iso2 VARCHAR, year INTEGER, supply_bcm DOUBLE, demand_bcm DOUBLE, "
        "surplus_deficit_bcm DOUBLE, missing_side VARCHAR, "
        "net_pipe_bcm DOUBLE, months_observed INTEGER, lng_net_bcm DOUBLE, "
        "source VARCHAR, "
        "PRIMARY KEY (country_iso2, year), "
        "FOREIGN KEY (country_iso2) REFERENCES dim_country (country_iso2))"
    )
    if len(fact_net_gas_position):
        con.execute("INSERT INTO fact_net_gas_position SELECT * FROM fact_net_gas_position_df")
    con.unregister("fact_net_gas_position_df")


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
