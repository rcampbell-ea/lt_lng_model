"""
oilx_flows.py
--------------
Session 3, build plan 3.4c. ``fact_lng_flow_baseline`` from whatever
``scripts/pull_oilx_flows.py`` snapshot exists under
``data/raw/oilx/<vintage>/flows_lng/response.json``. Country level per the
Prototype phasing decision (build plan section 3 top note): ``origin_iso2``,
``destination_iso2``, ``year``, ``bcm``, ``source``, ``release_date`` -- no
node ids, no port ids.

Field names follow plan 3.2c's documented ``/cargotracking/flows/lng``
response shape: ``OriginCountryCode``, ``DestinationCountryCode``,
``QuantityKT``/``QuantityCBM``/``QuantityMMBtu``, ``ReferenceDate``,
``Deleted``. PascalCase on the wire, renamed on read through this explicit
map per ``docs/session_01_data_availability.md`` 2.3 rule 4 -- never inline,
never left PascalCase downstream.

**Volume unit, unresolved.** Session 1 question 6 (what unit the flow
response actually reports, and the Mt-to-bcm 1.37 factor's applicability) is
open (see ``docs/session_03_definitions.md``): the response carries
``QuantityKT`` (kilotonnes), ``QuantityCBM`` (cubic metres, of LNG liquid,
not regasified gas) and ``QuantityMMBtu`` (energy) fields, and none of these
is a direct bcm-of-gas figure. This loader keeps whichever quantity fields
are present on the raw record and does **not** compute ``bcm`` by applying
an assumed conversion factor -- doing so would be exactly the fabrication
CLAUDE.md forbids. ``bcm`` is left null with the raw quantity fields
preserved alongside it until question 6 is settled against a live response.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Session 5, session_05 task step 1: the cargo-tracking flow record carries
# more fields than this loader mapped (confirmed against the pinned
# data/raw/oilx/202608/flows_lng/response.json: OriginCountryCode,
# DestinationCountryCode, ReferenceDate, QuantityKT, QuantityCBM,
# QuantityMMBtu, OriginSubCountryID, DestinationSubCountryID, Import --
# ``Deleted`` was mapped but does not appear on any record in the pinned
# snapshot). ``OriginSubCountryID``/``DestinationSubCountryID``/``Import``
# are not promoted to typed columns because nothing downstream this session
# queries them and the output grain (country-pair-year) does not have a
# single well-defined sub-country value to promote them to -- but they are
# never dropped: ``raw_records_json`` on the aggregated row carries the
# complete list of raw per-cargo records (byte for byte) that fed it, so a
# later session that needs sub-country detail (gate E) reads it from here
# rather than re-pulling.
FACT_LNG_FLOW_BASELINE_COLUMNS = [
    "origin_iso2",
    "destination_iso2",
    "year",
    "bcm",
    "quantity_kt",
    "quantity_cbm",
    "quantity_mmbtu",
    "source",
    "release_date",
    "raw_records_json",
]

_FIELD_MAP = {
    "OriginCountryCode": "origin_iso2",
    "DestinationCountryCode": "destination_iso2",
    "ReferenceDate": "reference_date",
    "QuantityKT": "quantity_kt",
    "QuantityCBM": "quantity_cbm",
    "QuantityMMBtu": "quantity_mmbtu",
    "Deleted": "deleted",
}


def _empty_fact_lng_flow_baseline() -> pd.DataFrame:
    return pd.DataFrame(columns=FACT_LNG_FLOW_BASELINE_COLUMNS)


def find_oilx_flow_snapshots(oilx_raw_root: Path) -> list[Path]:
    """Every ``response.json`` written by ``pull_oilx_flows.py`` under
    ``data/raw/oilx/<vintage>/flows_lng/``. Empty if the operator has not
    run the pull yet.
    """
    if not oilx_raw_root.is_dir():
        return []
    return sorted(oilx_raw_root.glob("*/flows_lng/response.json"))


def read_one_snapshot(path: Path) -> pd.DataFrame:
    """Parse one ``flows_lng/response.json`` into ``fact_lng_flow_baseline``
    rows, aggregated to (``origin_iso2``, ``destination_iso2``, ``year``).
    Rows flagged ``Deleted`` are excluded (a corrected/withdrawn cargo
    record, per the cargo-tracking API's revision model), not summed in and
    then silently offset.
    """
    if not path.is_file():
        raise FileNotFoundError(f"OilX flow snapshot not found: {path}")
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        records = payload.get("data") or payload.get("results")
        if records is None:
            raise ValueError(f"{path}: object response has neither 'data' nor 'results'")
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValueError(f"{path}: unexpected top-level JSON type {type(payload).__name__}")

    required = {"OriginCountryCode", "DestinationCountryCode", "ReferenceDate"}
    rows = []
    for record in records:
        missing = required - set(record.keys())
        if missing:
            raise ValueError(f"{path}: flow record missing keys {sorted(missing)}: {record}")
        if record.get("Deleted"):
            continue
        mapped = {out: record.get(raw) for raw, out in _FIELD_MAP.items()}
        origin = mapped["origin_iso2"]
        destination = mapped["destination_iso2"]
        if not origin or len(origin) != 2 or not destination or len(destination) != 2:
            raise ValueError(
                f"{path}: flow record has non two-character origin/destination: "
                f"{origin!r}/{destination!r}"
            )
        rows.append(
            {
                "origin_iso2": origin.upper(),
                "destination_iso2": destination.upper(),
                "year": int(str(mapped["reference_date"])[:4]),
                "bcm": None,
                "quantity_kt": mapped["quantity_kt"],
                "quantity_cbm": mapped["quantity_cbm"],
                "quantity_mmbtu": mapped["quantity_mmbtu"],
                "source": "oilx_cargotracking_flows_lng",
                "release_date": None,
                # Full raw record, byte for byte, including the fields this
                # loader does not type (OriginSubCountryID,
                # DestinationSubCountryID, Import) -- see module docstring.
                "raw_record": record,
            }
        )
    df = pd.DataFrame(rows, columns=[*FACT_LNG_FLOW_BASELINE_COLUMNS[:-1], "raw_record"])
    if df.empty:
        return df

    agg = df.groupby(["origin_iso2", "destination_iso2", "year", "source"], as_index=False).agg(
        quantity_kt=("quantity_kt", "sum"),
        quantity_cbm=("quantity_cbm", "sum"),
        quantity_mmbtu=("quantity_mmbtu", "sum"),
        raw_records_json=(
            "raw_record",
            lambda s: json.dumps(list(s), sort_keys=False, default=str),
        ),
    )
    agg["bcm"] = None
    agg["release_date"] = None
    return agg[FACT_LNG_FLOW_BASELINE_COLUMNS]


def build_fact_lng_flow_baseline(oilx_raw_root: Path) -> tuple[pd.DataFrame, list[Path]]:
    """Returns (fact_lng_flow_baseline, snapshots_used). Empty DataFrame
    with the correct schema, and an empty snapshot list, if no pull has
    landed yet.
    """
    snapshots = find_oilx_flow_snapshots(oilx_raw_root)
    if not snapshots:
        return _empty_fact_lng_flow_baseline(), []
    frames = [read_one_snapshot(path) for path in snapshots]
    return pd.concat(frames, ignore_index=True), snapshots
