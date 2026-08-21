"""
ea_dataset_catalogue.py
------------------------
Session 1, build plan 4.5. Reads ``ea_api_mappings.txt``, a pinned snapshot
of the EA client API's ``dataset_mappings`` response, into long form: one row
per ``(mapping_id, dataset_id)``, with ``dataset_ids`` deduplicated within
each mapping. Duplication is reported, not silently absorbed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REQUIRED_MAPPING_KEYS = {"mapping_id", "name", "dataset_ids", "licensed"}
_LICENSED_TRUE = {"yes", "true"}
_LICENSED_FALSE = {"no", "false"}


def _parse_licensed(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _LICENSED_TRUE:
            return True
        if lowered in _LICENSED_FALSE:
            return False
    raise ValueError(f"ea_api_mappings.txt: unexpected 'licensed' value {value!r}")


def read_ea_dataset_catalogue(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (long_form_catalogue, per_mapping_dedup_report).

    ``long_form_catalogue`` columns: commodity_group, mapping_id, mapping_name,
    licensed, dataset_id. One row per distinct dataset_id within a mapping.

    ``per_mapping_dedup_report`` columns: commodity_group, mapping_id,
    mapping_name, raw_count, distinct_count, so the duplication within a
    mapping is visible rather than silently absorbed.
    """
    if not path.is_file():
        raise FileNotFoundError(f"ea_api_mappings.txt not found: {path}")

    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"{path.name}: expected a top-level object keyed by commodity group, "
            f"got {type(data).__name__}"
        )

    catalogue_rows: list[dict] = []
    dedup_rows: list[dict] = []
    for commodity_group, mappings in data.items():
        if not isinstance(mappings, list):
            raise ValueError(
                f"{path.name}: commodity group '{commodity_group}' is not a list "
                f"of mappings, got {type(mappings).__name__}"
            )
        for mapping in mappings:
            missing = REQUIRED_MAPPING_KEYS - set(mapping.keys())
            if missing:
                raise ValueError(
                    f"{path.name}: mapping {mapping.get('mapping_id', '?')} in "
                    f"'{commodity_group}' is missing keys {sorted(missing)}"
                )
            mapping_id = mapping["mapping_id"]
            mapping_name = mapping["name"]
            licensed = _parse_licensed(mapping["licensed"])
            dataset_ids = mapping["dataset_ids"]
            if not isinstance(dataset_ids, list):
                raise ValueError(
                    f"{path.name}: mapping {mapping_id} 'dataset_ids' is not a "
                    f"list, got {type(dataset_ids).__name__}"
                )
            distinct_ids = sorted(set(dataset_ids))
            dedup_rows.append(
                {
                    "commodity_group": commodity_group,
                    "mapping_id": mapping_id,
                    "mapping_name": mapping_name,
                    "raw_count": len(dataset_ids),
                    "distinct_count": len(distinct_ids),
                }
            )
            for dataset_id in distinct_ids:
                catalogue_rows.append(
                    {
                        "commodity_group": commodity_group,
                        "mapping_id": mapping_id,
                        "mapping_name": mapping_name,
                        "licensed": licensed,
                        "dataset_id": dataset_id,
                    }
                )

    catalogue = pd.DataFrame(catalogue_rows)
    dedup_report = pd.DataFrame(dedup_rows)
    return catalogue, dedup_report
