"""
pull_oilx_flows.py
--------------------
Session 3, build plan 3.4b. For the operator to run, not this session
(CLAUDE.md, path 2). Separate API from the EA data service, distinct base
URL per plan 3.2c: ``https://api.energyaspects.com/oilx/v2/``. Pulls
``GET /cargotracking/flows/lng`` for the last three full years plus the
current-year nowcast, ``grade_level=false`` to collapse LNG grades to one row
per country pair per date, and one consistent ``import`` basis (see
``docs/session_01_data_availability.md`` 2.3, rule 1: omitting ``import``
mixes export- and import-dated rows and double counts the same physical
flow).

**Key naming, an open item.** ``EA_API_KEY``/``MY_EA_API_KEY`` is documented
for the ``.../data`` base (plan A.5, ``ea_client.py``). Plan 3.2c says OilX
is "distinct base URL, same api_key auth pattern" and "possibly a distinct
key" -- but no OilX-specific variable name is set in this project's ``.env``
or documented in ``.env.example`` as of this session (checked directly; see
``docs/session_03_ingestion.md``). This script therefore tries
``OILX_API_KEY`` first, for a distinct key if one is ever provisioned, and
falls back to ``EA_API_KEY``/``MY_EA_API_KEY``, on the theory (unconfirmed)
that OilX access rides the same account key as the data API. Confirm which
is actually correct before the first real pull and update ``.env.example``
and this script's key resolution if it is wrong -- this session cannot
confirm it without making the call itself, which it does not do.

Writes the raw JSON response plus ``flows_lng_manifest.json`` to
``data/raw/oilx/<vintage>/flows_lng/``.

Usage (activate the ``lt_lng_flows`` conda environment first), example for a
202608 vintage pull covering 2023-2026 (three full years 2023-2025 plus the
2026 nowcast):

    python scripts/pull_oilx_flows.py --vintage 202608 \\
        --start-date 2023-01-01 --end-date 2026-12-31 --import-basis import

This session does not run this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.ingest.provenance import write_manifest  # noqa: E402

DEFAULT_BASE_URL = "https://api.energyaspects.com/oilx/v2/"


def _resolve_api_key() -> tuple[str, str]:
    """Returns (key, env_var_name_used). Tries OILX_API_KEY first (a
    possible distinct OilX key, per plan 3.2c), then falls back to the data
    API's own EA_API_KEY / MY_EA_API_KEY -- see the module docstring's "open
    item" note on why this is a fallback rather than a confirmed name.
    """
    if os.environ.get("OILX_API_KEY"):
        return os.environ["OILX_API_KEY"], "OILX_API_KEY"
    if os.environ.get("EA_API_KEY"):
        return os.environ["EA_API_KEY"], "EA_API_KEY"
    if os.environ.get("MY_EA_API_KEY"):
        return os.environ["MY_EA_API_KEY"], "MY_EA_API_KEY"
    raise RuntimeError(
        "No API key found. Set OILX_API_KEY (preferred, if OilX uses a distinct key) "
        "or EA_API_KEY / MY_EA_API_KEY in the environment or project .env before "
        "running this script."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vintage", required=True, help="e.g. 202608")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--import-basis",
        choices=["import", "export"],
        default="import",
        help="build plan 3.4/5.2: import basis matches the importer-side balance identity; "
        "pull export basis separately as the cross check per "
        "docs/session_01_data_availability.md 2.3 rule 1",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    import requests

    api_key, key_var_used = _resolve_api_key()
    url = f"{args.base_url.rstrip('/')}/cargotracking/flows/lng"
    params = {
        "range": f"{args.start_date},{args.end_date}",
        "grade_level": "false",
        # The API's `import` parameter is boolean (True = ReferenceDate is an
        # import date, False = export date), not the string "import"/"export"
        # --import-basis takes on the CLI -- confirmed by the HTTP 422 this
        # produced when passed as the choice string directly.
        "import": "true" if args.import_basis == "import" else "false",
        "api_key": api_key,
    }

    # /cargotracking/flows/lng pages results (default page_size 10000). A
    # multi-year range can exceed one page; per the endpoint's own docs
    # (plan 3.2c), keep following `token` until it is absent or `data` is
    # empty, or a multi-year pull silently truncates with no warning.
    all_rows: list[dict] = []
    page_params: dict[str, str] = dict(params)
    page_count = 0
    while True:
        try:
            response = requests.get(
                url,
                params=page_params,
                headers={"accept": "application/json"},
                timeout=120.0,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            # requests' own exception message embeds the full request URL,
            # api_key included. Never let that reach stdout, a log, or a
            # re-raised exception (CLAUDE.md, "credentials").
            status = getattr(exc.response, "status_code", "unknown")
            raise RuntimeError(
                f"OilX API request failed: HTTP {status} on /cargotracking/flows/lng "
                f"page {page_count + 1} (query redacted). "
                f"Underlying error type: {type(exc).__name__}."
            ) from None
        page = response.json()
        page_count += 1
        rows = page.get("data") or []
        all_rows.extend(rows)
        token = page.get("token")
        if not token or not rows:
            break
        # Per the endpoint's docs: when `token` is specified, all other
        # parameters are ignored, so a continuation request carries only
        # api_key and token.
        page_params = {"api_key": api_key, "token": token}

    payload = {"data": all_rows, "success": True, "page_count": page_count}

    out_dir = ROOT / "data" / "raw" / "oilx" / args.vintage / "flows_lng"
    out_dir.mkdir(parents=True, exist_ok=True)
    response_path = out_dir / "response.json"
    response_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    redacted_params = {**params, "api_key": "<redacted>"}
    write_manifest(
        out_dir / "flows_lng_manifest.json",
        {
            "endpoint": url,
            "parameters": redacted_params,
            "api_key_env_var_used": key_var_used,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "response_file": response_path.name,
            "byte_count": response_path.stat().st_size,
            "page_count": page_count,
            "row_count": len(all_rows),
        },
    )
    print(
        f"Wrote {response_path} and its manifest "
        f"({len(all_rows)} rows across {page_count} page(s), key resolved from {key_var_used})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
