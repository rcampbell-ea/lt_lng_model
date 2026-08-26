"""
pull_ea_series.py
------------------
Session 3, build plan 3.4. For the operator to run, not this session
(CLAUDE.md, path 2: "pull scripts, for anything that lands on disk"). Reads
``data/raw/ea_api/202608/ea_api_mappings.txt``, takes the requested
``mapping_id``'s ``dataset_ids``, deduplicates them, and issues the request
against ``GET {EA_API_BASE_URL}/timeseries/`` using that mapping's own
``request_string`` template from the catalogue -- with the ``dataset_id``
parameter rebuilt from the deduplicated list, so the pull does not double
count series the catalogue lists twice (build plan 3.4, and
``docs/session_01_data_availability.md`` section 1, "duplicate ids within a
mapping").

The API key is read from the environment (``EA_API_KEY`` or
``MY_EA_API_KEY``) at call time and is never printed, logged, or written to
the manifest (CLAUDE.md, "credentials").

Writes the raw JSON response plus ``<mapping_id>_manifest.json`` (endpoint,
parameters with the key redacted, timestamp, content hash) to
``data/raw/ea_api/<vintage>/mapping_<id>/``.

Usage, one mapping per run, in the priority order build plan 3.4 names
(activate the ``lt_lng_flows`` conda environment first):

    python scripts/pull_ea_series.py --mapping-id 297 --vintage 202608
    python scripts/pull_ea_series.py --mapping-id 314 --vintage 202608
    python scripts/pull_ea_series.py --mapping-id 553 --vintage 202608
    python scripts/pull_ea_series.py --mapping-id 545 --vintage 202608
    python scripts/pull_ea_series.py --mapping-id 300 --vintage 202608
    python scripts/pull_ea_series.py --mapping-id 5 --vintage 202608
    python scripts/pull_ea_series.py --mapping-id 6 --vintage 202608

This session does not run any of the above.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.ingest.provenance import write_manifest  # noqa: E402

DEFAULT_BASE_URL = "https://api.energyaspects.com/data"
MAPPINGS_CATALOGUE_PATH = ROOT / "data" / "raw" / "ea_api" / "202608" / "ea_api_mappings.txt"

# Build plan 3.4 priority order, for reference in --help; not enforced, the
# operator names one mapping_id per invocation.
PRIORITY_MAPPINGS = {
    297: "Long term gas supply",
    314: "Long term total demand",
    553: "Long term losses",
    545: "Long term LNG imports and exports",
    300: "Long term prices",
    5: "Global LNG exports",
    6: "Global LNG imports",
}


def _resolve_api_key() -> str:
    key = os.environ.get("EA_API_KEY") or os.environ.get("MY_EA_API_KEY")
    if not key:
        raise RuntimeError(
            "EA API key not set. Set EA_API_KEY or MY_EA_API_KEY in the environment or "
            "project .env before running this script."
        )
    return key


def build_request(mapping_id: int, catalogue_path: Path) -> tuple[str, dict[str, str], list[int]]:
    """Read the mapping's request_string from the pinned mappings catalogue,
    for its date_from/date_to and filename parameters, but query by
    ``mapping_id`` rather than an explicit ``dataset_id`` list.

    The catalogue's own request_string builds a ``dataset_id`` CSV list,
    which for a large mapping (e.g. 553, "Long term losses", ~6,000+ ids
    after dedup) exceeds the server's URL length limit (HTTP 414). The
    ``/timeseries/`` endpoint accepts ``mapping_id`` directly (confirmed
    working during this project's API discovery -- see plan 3.2b) and the
    server performs its own deduplication server-side, so this avoids the
    URL-length failure entirely rather than chunking requests. distinct_ids
    is still returned, for the manifest's dataset-id-count field only; it is
    not sent as a request parameter.

    Raises if the mapping_id is not present in the catalogue.
    """
    import json as _json

    with catalogue_path.open(encoding="utf-8") as f:
        data = _json.load(f)

    for mappings in data.values():
        for mapping in mappings:
            if mapping["mapping_id"] == mapping_id:
                distinct_ids = sorted(set(mapping["dataset_ids"]))
                query_pairs = parse_qsl(
                    mapping["request_string"].lstrip("?"), keep_blank_values=True
                )
                params = {k: v for k, v in query_pairs if k != "dataset_id"}
                params["mapping_id"] = str(mapping_id)
                return "/timeseries/pagination/", params, distinct_ids

    raise ValueError(f"mapping_id {mapping_id} not found in {catalogue_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-id", type=int, required=True)
    parser.add_argument("--vintage", required=True, help="e.g. 202608")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--catalogue-path",
        type=Path,
        default=MAPPINGS_CATALOGUE_PATH,
        help="pinned ea_api_mappings.txt to read dataset_ids and request_string from",
    )
    args = parser.parse_args()

    import requests

    api_key = _resolve_api_key()
    path, params, distinct_ids = build_request(args.mapping_id, args.catalogue_path)
    url = f"{args.base_url}{path}"

    # /timeseries/pagination/ pages results (default records_per_page=5000,
    # one record per dataset_id). A mapping with more datasets than that
    # would silently truncate on a single request, so follow pagination.max_pages
    # from the first page rather than assume one page is everything.
    all_records: list[dict] = []
    page = 1
    max_pages = None
    while True:
        try:
            response = requests.get(
                url,
                params={**params, "api_key": api_key, "page": page},
                headers={"accept": "application/json"},
                timeout=120.0,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            # requests' own exception message embeds the full request URL,
            # api_key included (response.url / exc.request.url). Never let
            # that reach stdout, a log, or a re-raised exception -- redact
            # before reporting anything (CLAUDE.md, "credentials": never
            # printed, logged, or written anywhere).
            status = getattr(exc.response, "status_code", "unknown")
            raise RuntimeError(
                f"EA API request failed for mapping_id={args.mapping_id}: "
                f"HTTP {status} on {path} page {page} (query redacted). "
                f"Underlying error type: {type(exc).__name__}."
            ) from None
        records = response.json()
        if not isinstance(records, list):
            raise RuntimeError(
                f"Unexpected response shape from {path} for mapping_id="
                f"{args.mapping_id}: expected a list, got {type(records).__name__}."
            )
        all_records.extend(records)
        if not records:
            break
        max_pages = records[0].get("pagination", {}).get("max_pages", max_pages)
        if max_pages is None or page >= max_pages:
            break
        page += 1

    # The pinned mappings catalogue lists each dataset_id twice within a
    # mapping's own association data (confirmed: every dataset_id in every
    # mapping's dataset_ids array appears exactly twice in
    # ea_api_mappings.txt). Querying by mapping_id (rather than an explicit
    # deduplicated dataset_id CSV, which is what avoided this before the
    # 414-URL-too-long fix) means the server returns that duplication too --
    # confirmed live: mapping 5 returned dataset_id 130 twice, identical
    # records. Deduplicate by dataset_id here, keeping the first occurrence,
    # rather than let it become a silent PK violation downstream in
    # fact_gas_balance (dataset_id, year).
    seen_ids: set = set()
    deduped_records = []
    duplicate_count = 0
    for record in all_records:
        did = record.get("dataset_id")
        if did in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(did)
        deduped_records.append(record)
    payload = deduped_records

    out_dir = ROOT / "data" / "raw" / "ea_api" / args.vintage / f"mapping_{args.mapping_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    response_path = out_dir / "response.json"
    response_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # api_key is redacted from the recorded parameters; nothing here ever
    # writes, logs or prints the key value itself (CLAUDE.md, "credentials").
    redacted_params = {**params, "api_key": "<redacted>"}
    write_manifest(
        out_dir / f"mapping_{args.mapping_id}_manifest.json",
        {
            "endpoint": url,
            "parameters": redacted_params,
            "mapping_id": args.mapping_id,
            "distinct_dataset_id_count": len(distinct_ids),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "response_file": response_path.name,
            "byte_count": response_path.stat().st_size,
            "page_count": page,
            "raw_record_count": len(all_records),
            "duplicate_dataset_id_count": duplicate_count,
            "record_count": len(payload),
        },
    )
    print(
        f"Wrote {response_path} and its manifest "
        f"({len(payload)} records across {page} page(s), {duplicate_count} duplicate "
        f"dataset_id record(s) dropped, {len(distinct_ids)} distinct dataset ids expected)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
