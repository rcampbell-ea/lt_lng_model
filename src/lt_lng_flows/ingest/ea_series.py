"""
ea_series.py
------------
Session 3, build plan 3.5. ``fact_gas_balance`` from whatever
``scripts/pull_ea_series.py`` snapshots exist under
``data/raw/ea_api/<vintage>/mapping_<id>/response.json``. Long form:
``country_iso2``, ``year``, ``component``, ``value``, ``unit``,
``lifecycle_stage``, ``dataset_id``, ``release_date``, ``source``.

**Component naming.** ``component`` is read straight from each dataset's own
``aspect`` metadata field (the EA vocabulary documented in
``docs/session_01_data_availability.md`` section 6: ``supply``, ``demand``,
``production``, ``net_imports``, ``exports``, ``imports``, ``storage``, and
so on), not remapped onto the plan 5.2 balance-identity term names
(``domestic_production``, ``pipe_imports``, ...). That remapping needs the
open questions in plan 5.2 and session 1 question 1 (whether mapping 297
carries net pipe trade) settled first -- forcing a guessed mapping here would
silently pick a side of an unresolved question. See
``docs/session_03_definitions.md``.

**Sign convention.** Values are stored exactly as the API returns them.
Plan 5.2's identity (`net_lng_imports = demand + pipe_exports + ... -
production - pipe_imports`) is model logic for a later session, not an
ingestion-time transform; no sign is flipped here.

Yearly resolution: a series' ``data`` object is ``{date: value}`` per plan
3.2b; this loader takes the year from each date key and, where a series
reports sub-annual (monthly/quarterly) frequency, does **not** aggregate to
annual on its own initiative -- annual aggregation of a sub-annual balance
component is a modelling choice (which months constitute the "year" for a
forecast series, whether to sum or average) that belongs with whichever
session builds the balance, not with ingestion. Rows carry their native
frequency; a caller needing annual-only should filter on it explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

FACT_GAS_BALANCE_COLUMNS = [
    "country_iso2",
    "year",
    "component",
    "value",
    "unit",
    "lifecycle_stage",
    "frequency",
    "dataset_id",
    "release_date",
    "source",
]


def _empty_fact_gas_balance() -> pd.DataFrame:
    return pd.DataFrame(columns=FACT_GAS_BALANCE_COLUMNS)


def find_ea_series_snapshots(ea_api_raw_root: Path) -> list[Path]:
    """Every ``response.json`` written by ``pull_ea_series.py`` under
    ``data/raw/ea_api/<vintage>/mapping_<id>/``. Empty if the operator has
    not run the pull yet (build plan 3.5: "build the loader, test it against
    a fixture, and report the table as empty pending the pull").
    """
    if not ea_api_raw_root.is_dir():
        return []
    return sorted(ea_api_raw_root.glob("*/mapping_*/response.json"))


def read_one_snapshot(path: Path) -> pd.DataFrame:
    """Parse one ``mapping_<id>/response.json`` into long-form
    ``fact_gas_balance`` rows. Expects the ``/timeseries/`` response shape
    from plan 3.2b: a list of per-dataset records (or an object carrying
    them under a ``data``/``results`` key -- both are accepted since the
    exact envelope was not confirmed live as of this session), each with
    dataset-level metadata (``dataset_id``, ``country_iso``, ``aspect``,
    ``unit``, ``frequency``, ``lifecycle_stage``, ``release_date``) and its
    own ``data``: ``{date: value}`` mapping.

    Raises, naming the file, if a record is missing a required metadata key
    or its ``country_iso`` is present but not two characters -- fail loudly
    rather than silently dropping a malformed record.
    """
    if not path.is_file():
        raise FileNotFoundError(f"EA series snapshot not found: {path}")
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        records = payload.get("data") or payload.get("results") or payload.get("datasets")
        if records is None:
            raise ValueError(
                f"{path}: object response has none of the expected keys "
                f"('data', 'results', 'datasets')"
            )
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValueError(f"{path}: unexpected top-level JSON type {type(payload).__name__}")

    required = {"dataset_id", "aspect", "unit", "frequency", "lifecycle_stage"}
    rows = []
    for record in records:
        missing = required - set(record.keys())
        if missing:
            raise ValueError(f"{path}: series record missing keys {sorted(missing)}: {record}")
        country_iso = record.get("country_iso") or None
        if country_iso is not None and len(country_iso) != 2:
            raise ValueError(
                f"{path}: dataset {record['dataset_id']} has country_iso "
                f"{country_iso!r}, expected two characters or null (region/world aggregate)"
            )
        series_data = record.get("data", {})
        for date_str, value in series_data.items():
            if value is None:
                continue
            year = int(str(date_str)[:4])
            rows.append(
                {
                    "country_iso2": country_iso.upper() if country_iso else None,
                    "year": year,
                    "component": record["aspect"],
                    "value": float(value),
                    "unit": record["unit"],
                    "lifecycle_stage": record["lifecycle_stage"],
                    "frequency": record["frequency"],
                    "dataset_id": record["dataset_id"],
                    "release_date": record.get("release_date"),
                    "source": "ea_api_timeseries",
                }
            )
    return pd.DataFrame(rows, columns=FACT_GAS_BALANCE_COLUMNS)


def build_fact_gas_balance(ea_api_raw_root: Path) -> tuple[pd.DataFrame, list[Path]]:
    """Returns (fact_gas_balance, snapshots_used). Empty DataFrame with the
    correct schema, and an empty snapshot list, if no pull has landed yet --
    reported by the caller as "empty pending the pull", not skipped.
    """
    snapshots = find_ea_series_snapshots(ea_api_raw_root)
    if not snapshots:
        return _empty_fact_gas_balance(), []
    frames = [read_one_snapshot(path) for path in snapshots]
    return pd.concat(frames, ignore_index=True), snapshots
