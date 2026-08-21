"""
ea_cargo_tracking.py
----------------------
Session 1, build plan 4.6. Reads the two EA cargo tracking taxonomy files.
Both are JSON with the shape ``{"data": [...], "success": ...}``; ``success``
is checked and dropped, never carried into the output.

These files carry ISO2 natively (``Countries[].Code`` / ``Country``), so
they are never name-matched: a code absent from ``dim_country`` raises and
names it, rather than being added silently (that check runs in
``geo_checks.py`` once ``dim_country`` exists).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

_VALID_SUEZ_POSITIONS = {"East", "West"}


def _load_success_json(path: Path) -> list:
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError(f"{path.name}: expected an object with a 'data' key")
    success = payload.get("success")
    if success not in (True, "true", "success", 1):
        raise ValueError(f"{path.name}: 'success' was {success!r}, not a success value")
    return payload["data"]


def slugify(name: str) -> str:
    """ASCII lower snake case, per CLAUDE.md identifier rules."""
    ascii_name = name.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        raise ValueError(f"area name {name!r} slugified to an empty string")
    return slug


def read_ea_ct_areas(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (ea_ct_area, ea_ct_area_country).

    ``ea_ct_area``: area_id, area_name, area_slug, suez_position (east/west).
    ``ea_ct_area_country``: one row per (area_id, country_iso2, port_id),
    exploded from ``Countries[].Ports``. A country listed twice within the
    same area's ``Countries`` array raises, naming the area and country.
    """
    records = _load_success_json(path)

    area_rows: list[dict] = []
    area_country_rows: list[dict] = []
    for area in records:
        required = {"ID", "Name", "SuezPosition", "Countries"}
        missing = required - set(area.keys())
        if missing:
            raise ValueError(f"{path.name}: area is missing keys {sorted(missing)}: {area}")

        area_id = area["ID"]
        suez_raw = area["SuezPosition"]
        if suez_raw not in _VALID_SUEZ_POSITIONS:
            raise ValueError(
                f"{path.name}: area {area_id} ('{area['Name']}') has "
                f"SuezPosition {suez_raw!r}, expected one of {_VALID_SUEZ_POSITIONS}"
            )
        area_rows.append(
            {
                "area_id": area_id,
                "area_name": area["Name"],
                "area_slug": slugify(area["Name"]),
                "suez_position": suez_raw.lower(),
            }
        )

        seen_codes: set[str] = set()
        for country in area["Countries"]:
            code = country["Code"]
            if code in seen_codes:
                raise ValueError(
                    f"{path.name}: area {area_id} ('{area['Name']}') lists "
                    f"country {code!r} more than once"
                )
            seen_codes.add(code)
            for port_entry in country["Ports"]:
                if not isinstance(port_entry, int):
                    raise ValueError(
                        f"{path.name}: area {area_id} country {code} has a "
                        f"non integer port entry {port_entry!r}; the areas "
                        f"file is not expected to carry the sub-country "
                        f"object shape seen in ea_ct_country_ports.txt"
                    )
                area_country_rows.append(
                    {"area_id": area_id, "country_iso2": code, "port_id": port_entry}
                )

    return pd.DataFrame(area_rows), pd.DataFrame(area_country_rows)


def read_ea_ct_country_ports(path: Path) -> tuple[pd.DataFrame, dict]:
    """Return (ea_ct_country_port, raw_shape_report).

    ``ea_ct_country_port``: one row per (country_iso2, port_id), primary key.
    Most ``Ports`` entries are integers; some are objects of the form
    ``{"SubCountry": n, "Ports": [ids]}``, which explode into one row per
    inner port id with ``sub_country_id`` set. Both shapes are handled.

    ``raw_shape_report`` carries the counts asserted in build plan 4.6:
    distinct country codes, raw (unexploded) port-list entries, and the
    number of sub-country objects encountered.
    """
    records = _load_success_json(path)

    rows: list[dict] = []
    raw_entry_count = 0
    sub_country_object_count = 0
    seen_pairs: set[tuple[str, int]] = set()
    for entry in records:
        required = {"Country", "Ports"}
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(
                f"{path.name}: country entry is missing keys {sorted(missing)}: {entry}"
            )
        code = entry["Country"]
        for port_entry in entry["Ports"]:
            raw_entry_count += 1
            if isinstance(port_entry, int):
                pairs = [(code, port_entry, None)]
            elif isinstance(port_entry, dict):
                sub_required = {"SubCountry", "Ports"}
                sub_missing = sub_required - set(port_entry.keys())
                if sub_missing:
                    raise ValueError(
                        f"{path.name}: country {code} has a sub-country object "
                        f"missing keys {sorted(sub_missing)}: {port_entry}"
                    )
                sub_country_object_count += 1
                sub_country_id = port_entry["SubCountry"]
                pairs = [(code, pid, sub_country_id) for pid in port_entry["Ports"]]
            else:
                raise ValueError(
                    f"{path.name}: country {code} has an unexpected port "
                    f"entry type {type(port_entry).__name__}: {port_entry!r}"
                )
            for country_iso2, port_id, sub_country_id in pairs:
                key = (country_iso2, port_id)
                if key in seen_pairs:
                    raise ValueError(f"{path.name}: duplicate (country_iso2, port_id) pair {key}")
                seen_pairs.add(key)
                rows.append(
                    {
                        "country_iso2": country_iso2,
                        "port_id": port_id,
                        "sub_country_id": sub_country_id,
                    }
                )

    df = pd.DataFrame(rows)
    report = {
        "distinct_country_codes": df["country_iso2"].nunique() if not df.empty else 0,
        "raw_port_list_entries": raw_entry_count,
        "sub_country_objects": sub_country_object_count,
        "exploded_row_count": len(df),
    }
    return df, report
