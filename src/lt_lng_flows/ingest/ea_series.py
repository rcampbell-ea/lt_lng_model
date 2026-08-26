"""
ea_series.py
------------
Session 3, build plan 3.5. ``fact_gas_balance`` from whatever
``scripts/pull_ea_series.py`` snapshots exist under
``data/raw/ea_api/<vintage>/mapping_<id>/response.json``. Long form:
``country_iso2``, ``period``, ``year``, ``component``, ``value``, ``unit``,
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

Native resolution, not collapsed to year. A series' ``data`` object is
``{date: value}`` per plan 3.2b; this loader keeps each date as its own
``period`` row rather than aggregating to annual on its own initiative --
annual aggregation of a sub-annual balance component is a modelling choice
(which months constitute the "year" for a forecast series, whether to sum or
average) that belongs with whichever session builds the balance, not with
ingestion. ``year`` is carried alongside ``period`` as a convenience column
for annual-only filtering; it is not the primary key. The primary key is
``(dataset_id, period)`` -- mappings 5 and 6 ("Global LNG exports/imports")
are monthly frequency, so multiple rows per dataset share a year; using
``(dataset_id, year)`` as the key silently collided and lost rows until this
was caught against a real pull (see docs/session_03_ingestion.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

# Session 5, sessions_05_07_build_plan.md 4.1.A / session_05 task step 1: the
# API returns 15 metadata fields per dataset (confirmed against the pinned
# 202608 snapshots: aspect, aspect_subtype, category, category_subtype,
# country, country_iso, description, forecast_start_date, frequency,
# lifecycle_stage, region, release_date, source, sub_region, unit), plus the
# top-level dataset_id. This loader previously kept six. Every field the
# downstream session 5 build actually queries -- aspect_subtype (open
# question 1/pipeline flag), category_subtype (the only field distinguishing
# an LNG net_imports row, mapping 545, from a total-gas one, mapping 297),
# region/sub_region (lt_region derivation), description and
# forecast_start_date -- is promoted to a typed column here. Nothing is
# dropped: ``metadata_json`` carries the complete raw metadata dict
# byte-for-byte, so a field this loader does not yet type is never lost.
# ``mapping_id`` is not a metadata field at all -- it is not present anywhere
# in the response payload (confirmed against mapping_297/response.json) --
# it is recovered from the pinned snapshot's own directory name
# (``mapping_<id>/response.json``), which is how every pull script and every
# session doc names a mapping. Left null if a path does not follow that
# convention (e.g. a test fixture writing directly to a bare tmp_path).
FACT_GAS_BALANCE_COLUMNS = [
    "country_iso2",
    "period",
    "year",
    "component",
    "category",
    "value",
    "unit",
    "lifecycle_stage",
    "frequency",
    "dataset_id",
    "mapping_id",
    "aspect_subtype",
    "category_subtype",
    "region",
    "sub_region",
    "description",
    "forecast_start_date",
    "release_date",
    "source",
    "metadata_json",
]

_MAPPING_DIR_RE = re.compile(r"^mapping_(\d+)$")


def _mapping_id_from_path(path: Path) -> int | None:
    match = _MAPPING_DIR_RE.match(path.parent.name)
    return int(match.group(1)) if match else None


def _blank_to_null(value):
    """The API uses ``""`` for "not applicable" on optional metadata fields
    (e.g. ``aspect_subtype`` on a mapping 297 row) rather than omitting the
    key. Stored as null, not as an empty string, so it reads the same as any
    other missing value downstream and is never mistaken for a real, blank
    category."""
    return value if value not in (None, "") else None


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
    ``fact_gas_balance`` rows. Confirmed live response shape (this session,
    against real pulls -- see docs/session_03_ingestion.md): a list of
    per-dataset records, each ``{"pagination": {...}, "metadata": {...},
    "data": {date: value}, "dataset_id": int, "additional_fields": {...}}``.
    Dataset-level fields (``country_iso``, ``aspect``, ``unit``,
    ``frequency``, ``lifecycle_stage``, ``release_date``) live under
    ``metadata``, not at the record's top level; ``dataset_id`` is the one
    field that is top level. An object-wrapped response (``data``/
    ``results``/``datasets`` key) is also accepted defensively, in case a
    future pull ever comes back wrapped.

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

    required_top = {"dataset_id", "metadata"}
    required_metadata = {"aspect", "category", "unit", "frequency", "lifecycle_stage"}
    rows = []
    for record in records:
        missing_top = required_top - set(record.keys())
        if missing_top:
            raise ValueError(f"{path}: series record missing keys {sorted(missing_top)}: {record}")
        metadata = record["metadata"]
        missing_meta = required_metadata - set(metadata.keys())
        if missing_meta:
            raise ValueError(
                f"{path}: dataset {record['dataset_id']} metadata missing keys "
                f"{sorted(missing_meta)}: {metadata}"
            )
        country_iso = metadata.get("country_iso") or None
        if country_iso is not None and len(country_iso) != 2:
            raise ValueError(
                f"{path}: dataset {record['dataset_id']} has country_iso "
                f"{country_iso!r}, expected two characters or null (region/world aggregate)"
            )
        mapping_id = _mapping_id_from_path(path)
        metadata_json = json.dumps(metadata, sort_keys=True)
        series_data = record.get("data", {})
        for date_str, value in series_data.items():
            if value is None:
                continue
            period = str(date_str)
            year = int(period[:4])
            rows.append(
                {
                    "country_iso2": country_iso.upper() if country_iso else None,
                    "period": period,
                    "year": year,
                    "component": metadata["aspect"],
                    "category": metadata["category"],
                    "value": float(value),
                    "unit": metadata["unit"],
                    "lifecycle_stage": metadata["lifecycle_stage"],
                    "frequency": metadata["frequency"],
                    "dataset_id": record["dataset_id"],
                    "mapping_id": mapping_id,
                    "aspect_subtype": _blank_to_null(metadata.get("aspect_subtype")),
                    "category_subtype": _blank_to_null(metadata.get("category_subtype")),
                    "region": _blank_to_null(metadata.get("region")),
                    "sub_region": _blank_to_null(metadata.get("sub_region")),
                    "description": metadata.get("description"),
                    "forecast_start_date": metadata.get("forecast_start_date"),
                    "release_date": metadata.get("release_date"),
                    "source": "ea_api_timeseries",
                    "metadata_json": metadata_json,
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
