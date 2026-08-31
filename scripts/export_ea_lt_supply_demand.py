"""
export_ea_lt_supply_demand.py
------------------------------
EA long-term natural gas supply and demand, one CSV, nothing derived. Reads
whichever `ea_series.py`-parseable snapshots are pinned under
`data/raw/ea_api/<vintage>/mapping_297` (supply) and `mapping_314` (demand),
applies the filters established for this export (config/export_constants.yaml),
and writes `data/output/ea_lt_gas_supply_demand.csv`.

Default run: no network call. Reads the newest pinned vintage under
`data/raw/ea_api/` and writes the CSV. Runs from PyCharm's green arrow with
no arguments.

`--refresh`: pulls mappings 297 and 314 fresh via `scripts/pull_ea_series.py`
into a new vintage directory first, then writes the CSV from that vintage.

Every filter value and expected count (country counts, year spans,
observations per series) lives in config/export_constants.yaml, not inline
here (CLAUDE.md, "numbers, failure and provenance"). A future vintage whose
shape does not match those expectations fails loudly, printing expected vs.
actual, rather than being written silently.

No value in the output CSV originates from anywhere but the EA API response
itself: no estimate, no interpolation, no gap-fill, no unit conversion, no
derived column. Supply and demand sit side by side; a country-year missing
from a series is an empty cell, never a zero.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.ingest import ea_series  # noqa: E402

EA_API_RAW_ROOT = ROOT / "data" / "raw" / "ea_api"
CONSTANTS_PATH = ROOT / "config" / "export_constants.yaml"
DIM_COUNTRY_PATH = ROOT / "data" / "geo" / "dim_country.parquet"
OUTPUT_PATH = ROOT / "data" / "output" / "ea_lt_gas_supply_demand.csv"
PULL_SCRIPT_PATH = ROOT / "scripts" / "pull_ea_series.py"

_VINTAGE_RE = re.compile(r"^\d{6,8}$")


def load_constants(path: Path = CONSTANTS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_latest_vintage(ea_api_raw_root: Path) -> str:
    """The newest vintage directory name (e.g. "202608") under
    data/raw/ea_api/. Newest by name, since the vintage naming convention
    (YYYYMM) sorts chronologically as a string.
    """
    if not ea_api_raw_root.is_dir():
        raise RuntimeError(f"No EA API raw root found at {ea_api_raw_root}")
    vintages = sorted(
        p.name for p in ea_api_raw_root.iterdir() if p.is_dir() and _VINTAGE_RE.match(p.name)
    )
    if not vintages:
        raise RuntimeError(f"No pinned EA API vintage directory found under {ea_api_raw_root}")
    return vintages[-1]


def refresh_vintage(vintage: str, mapping_ids: tuple[int, ...] = (297, 314)) -> None:
    """Calls scripts/pull_ea_series.py for each mapping, pinning a new
    vintage directory. Raises, naming the mapping, if a pull fails."""
    for mapping_id in mapping_ids:
        result = subprocess.run(
            [
                sys.executable,
                str(PULL_SCRIPT_PATH),
                "--mapping-id",
                str(mapping_id),
                "--vintage",
                vintage,
            ],
            cwd=ROOT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"scripts/pull_ea_series.py failed for mapping_id={mapping_id} "
                f"(exit code {result.returncode})"
            )


def _dataset_level(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates("dataset_id")[
        ["dataset_id", "category", "aspect_subtype", "unit", "country_iso2"]
    ]


def filter_series(df: pd.DataFrame, spec: dict, label: str) -> tuple[pd.DataFrame, list[str]]:
    """Applies this export's filters for one series (supply or demand) and
    returns (filtered_rows, exclusion_report_lines). Filtering happens at
    dataset level first so one dataset's exclusion reason is not duplicated
    once per row/period.
    """
    exclusions: list[str] = []
    mapping_id = spec["mapping_id"]
    datasets = _dataset_level(df)

    cat_ok = datasets["category"] == spec["category"]
    if (~cat_ok).any():
        for category, count in datasets.loc[~cat_ok, "category"].value_counts().items():
            exclusions.append(
                f"mapping {mapping_id} ({label}): {count} dataset(s) excluded, "
                f"category={category!r} != {spec['category']!r}"
            )
    candidates = datasets.loc[cat_ok]

    if spec.get("aspect_subtype") is not None:
        subtype_ok = candidates["aspect_subtype"] == spec["aspect_subtype"]
        if (~subtype_ok).any():
            for subtype, count in (
                candidates.loc[~subtype_ok, "aspect_subtype"].value_counts(dropna=False).items()
            ):
                exclusions.append(
                    f"mapping {mapping_id} ({label}): {count} dataset(s) excluded, "
                    f"aspect_subtype={subtype!r} != {spec['aspect_subtype']!r}"
                )
        candidates = candidates.loc[subtype_ok]

    unit_ok = candidates["unit"] == spec["unit"]
    country_ok = candidates["country_iso2"].notnull()

    if (~unit_ok).any():
        for unit, count in candidates.loc[~unit_ok, "unit"].value_counts().items():
            ids = sorted(candidates.loc[~unit_ok & (candidates["unit"] == unit), "dataset_id"])
            exclusions.append(
                f"mapping {mapping_id} ({label}): {count} dataset(s) excluded, "
                f"unit={unit!r} != {spec['unit']!r} (dataset_id: {ids})"
            )
    if (~country_ok).any():
        ids = sorted(candidates.loc[~country_ok, "dataset_id"])
        exclusions.append(
            f"mapping {mapping_id} ({label}): {len(ids)} dataset(s) excluded, "
            f"country_iso2 blank (dataset_id: {ids})"
        )

    included_ids = set(candidates.loc[unit_ok & country_ok, "dataset_id"])
    filtered_rows = df[df["dataset_id"].isin(included_ids)]
    return filtered_rows, exclusions


def assert_shape(df: pd.DataFrame, spec: dict, label: str) -> None:
    """Fails loudly, naming expected vs. actual, if a pinned vintage does not
    match the shape this export's filters were established against
    (CLAUDE.md: "fail loudly"; task instruction: "it does not adapt
    silently")."""
    actual_countries = df["country_iso2"].nunique()
    actual_min_year = int(df["year"].min())
    actual_max_year = int(df["year"].max())
    obs_per_series = df.groupby("dataset_id").size()
    actual_obs = sorted(obs_per_series.unique().tolist())

    problems = []
    if actual_countries != spec["expected_countries"]:
        problems.append(f"countries: expected {spec['expected_countries']}, got {actual_countries}")
    if actual_min_year != spec["expected_min_year"]:
        problems.append(f"min year: expected {spec['expected_min_year']}, got {actual_min_year}")
    if actual_max_year != spec["expected_max_year"]:
        problems.append(f"max year: expected {spec['expected_max_year']}, got {actual_max_year}")
    if actual_obs != [spec["expected_obs_per_series"]]:
        problems.append(
            f"observations per series: expected uniformly {spec['expected_obs_per_series']}, "
            f"got distinct value(s) {actual_obs}"
        )
    if problems:
        raise AssertionError(
            f"{label} ({spec['mapping_id']}) shape mismatch: " + "; ".join(problems)
        )


def build_output_table(
    supply: pd.DataFrame, demand: pd.DataFrame, dim_country: pd.DataFrame
) -> pd.DataFrame:
    supply_years = supply[["country_iso2", "year", "value"]].rename(columns={"value": "supply_bcm"})
    demand_years = demand[["country_iso2", "year", "value"]].rename(columns={"value": "demand_bcm"})

    merged = pd.merge(supply_years, demand_years, on=["country_iso2", "year"], how="outer")

    unmapped = sorted(set(merged["country_iso2"]) - set(dim_country["country_iso2"]))
    if unmapped:
        raise ValueError(
            f"country_iso2 code(s) not present in dim_country.parquet: {unmapped} "
            "(CLAUDE.md: an unmapped code raises, it is not silently dropped)"
        )

    real_country_codes = set(dim_country.loc[dim_country["is_real_country"], "country_iso2"])
    pseudo = sorted(set(merged["country_iso2"]) - real_country_codes)
    if pseudo:
        raise ValueError(
            f"country_iso2 code(s) flagged is_real_country=False in dim_country.parquet: "
            f"{pseudo} (CLAUDE.md: 'pseudo codes are not countries' -- a ZZ/XP/XM/... reaching "
            "output is a bug, not a category)"
        )

    duplicate_keys = merged[merged.duplicated(["country_iso2", "year"], keep=False)]
    if not duplicate_keys.empty:
        raise ValueError(
            f"duplicate (country_iso2, year) row(s) after merge: "
            f"{sorted(set(zip(duplicate_keys['country_iso2'], duplicate_keys['year'])))} "
            "(each series must contribute at most one value per country-year)"
        )

    both_null = merged["supply_bcm"].isnull() & merged["demand_bcm"].isnull()
    if both_null.any():
        raise ValueError(
            f"{both_null.sum()} row(s) have neither a supply nor a demand value after the outer "
            "merge -- a row must be backed by at least one source series, never fabricated"
        )

    merged = merged.merge(
        dim_country[["country_iso2", "country_name_display"]].rename(
            columns={"country_name_display": "country_name"}
        ),
        on="country_iso2",
        how="left",
    )
    merged = merged.sort_values(["country_iso2", "year"]).reset_index(drop=True)
    return merged[["country_iso2", "country_name", "year", "supply_bcm", "demand_bcm"]]


def summarize(table: pd.DataFrame) -> dict:
    has_supply = table["supply_bcm"].notnull()
    has_demand = table["demand_bcm"].notnull()
    supply_countries = set(table.loc[has_supply, "country_iso2"])
    demand_countries = set(table.loc[has_demand, "country_iso2"])
    return {
        "rows_written": len(table),
        "supply_only_countries": sorted(supply_countries - demand_countries),
        "demand_only_countries": sorted(demand_countries - supply_countries),
        "both_countries": sorted(supply_countries & demand_countries),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="pull mappings 297 and 314 fresh into a new vintage before exporting",
    )
    args = parser.parse_args()

    constants = load_constants()
    supply_spec = constants["series"]["supply"]
    demand_spec = constants["series"]["demand"]

    if args.refresh:
        vintage = datetime.now(UTC).strftime("%Y%m%d")
        print(f"--refresh: pulling mappings 297 and 314 into vintage {vintage}")
        refresh_vintage(vintage)
    else:
        vintage = find_latest_vintage(EA_API_RAW_ROOT)
        print(f"Using pinned vintage {vintage} (no network call)")

    supply_path = (
        EA_API_RAW_ROOT / vintage / f"mapping_{supply_spec['mapping_id']}" / "response.json"
    )
    demand_path = (
        EA_API_RAW_ROOT / vintage / f"mapping_{demand_spec['mapping_id']}" / "response.json"
    )
    supply_raw = ea_series.read_one_snapshot(supply_path)
    demand_raw = ea_series.read_one_snapshot(demand_path)

    supply_filtered, supply_exclusions = filter_series(supply_raw, supply_spec, "supply")
    demand_filtered, demand_exclusions = filter_series(demand_raw, demand_spec, "demand")

    assert_shape(supply_filtered, supply_spec, "supply")
    assert_shape(demand_filtered, demand_spec, "demand")

    dim_country = pd.read_parquet(DIM_COUNTRY_PATH)
    table = build_output_table(supply_filtered, demand_filtered, dim_country)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT_PATH, index=False, na_rep="")

    summary = summarize(table)
    print(f"Rows written: {summary['rows_written']}")
    print(
        f"Countries with supply only ({len(summary['supply_only_countries'])}): "
        f"{summary['supply_only_countries']}"
    )
    print(
        f"Countries with demand only ({len(summary['demand_only_countries'])}): "
        f"{summary['demand_only_countries']}"
    )
    print(f"Countries with both ({len(summary['both_countries'])}): {summary['both_countries']}")
    print("Excluded datasets:")
    for line in [*supply_exclusions, *demand_exclusions]:
        print(f"  {line}")
    print(
        "  mapping 553 (Long term losses): entire mapping out of scope, not pulled "
        "(per task instruction, own_use)"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
