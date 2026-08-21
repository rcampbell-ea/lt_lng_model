"""
country_master.py
-------------------
Session 1, build plan 4.3 and 4.4. Builds the minimal ``dim_country`` for
this session (country_iso2, country_name, region, is_real_country) from a
pinned ISO 3166-1 snapshot plus the six pseudo codes, and proposes — never
applies — an alias resolution for every raw country-like string found in
4.2.

No network call reaches an ISO source at import or at build time (CLAUDE.md,
"the three data access paths"). See ``docs/session_01_country_key.md`` for
why the ISO list here is an authored static snapshot rather than a package
pull, given session 1's no-network constraint.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

REQUIRED_ISO_COLUMNS = {"country_iso2", "country_name", "region"}
ZZ_CODE = "ZZ"


def load_pseudo_codes(pseudo_codes_config_path: Path) -> dict:
    with pseudo_codes_config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_dim_country(iso_csv_path: Path, pseudo_codes_config_path: Path) -> pd.DataFrame:
    """Real countries from the pinned ISO 3166-1 snapshot, plus the six
    pseudo codes, all with ``is_real_country = False``. Raises if the pinned
    file is missing an expected column, or if any code collides.
    """
    if not iso_csv_path.is_file():
        raise FileNotFoundError(f"pinned ISO 3166-1 snapshot not found: {iso_csv_path}")

    # keep_default_na=False: "NA" (Namibia's ISO2) must not be read as a null.
    real = pd.read_csv(iso_csv_path, dtype=str, keep_default_na=False, na_values=[])
    missing = REQUIRED_ISO_COLUMNS - set(real.columns)
    if missing:
        raise ValueError(f"{iso_csv_path.name}: missing expected columns {sorted(missing)}")
    real = real[["country_iso2", "country_name", "region"]].copy()
    real["is_real_country"] = True

    pseudo_cfg = load_pseudo_codes(pseudo_codes_config_path)
    pseudo_rows = [
        {
            "country_iso2": code,
            "country_name": meta["meaning"],
            "region": None,
            "is_real_country": False,
        }
        for code, meta in pseudo_cfg["pseudo_codes"].items()
    ]
    pseudo = pd.DataFrame(pseudo_rows)

    dim = pd.concat([real, pseudo], ignore_index=True)

    if dim["country_iso2"].isnull().any():
        raise ValueError("dim_country: null country_iso2 present")
    if dim["country_iso2"].duplicated().any():
        dupes = sorted(dim.loc[dim["country_iso2"].duplicated(), "country_iso2"].unique())
        raise ValueError(f"dim_country: duplicate country_iso2 codes {dupes}")
    bad_codes = [
        c for c in dim["country_iso2"] if not (len(c) == 2 and c.isalpha() and c.isupper())
    ]
    if bad_codes:
        raise ValueError(f"dim_country: codes not two uppercase letters: {bad_codes}")

    return dim.reset_index(drop=True)


class AliasResolver:
    """Exact-match-only alias resolution for build plan 4.4.

    High confidence is granted only for:
      - an exact, case-insensitive match on ``country_iso2`` (any code in
        ``dim_country`` except ZZ, which is never proposed);
      - an exact, case-insensitive match to a configured pseudo-code alias
        (e.g. "Portfolio" -> XP);
      - an exact, case-insensitive match on ``country_name`` for a real
        country.

      Everything else is ``method = "unresolved"``, ``confidence = "none"``,
      ``proposed_iso2 = ""``. No substring, edit-distance or similarity-score
      matching of any kind.
    """

    def __init__(self, dim_country: pd.DataFrame, pseudo_code_aliases: dict[str, str]):
        self._iso2_set = {code.upper() for code in dim_country["country_iso2"]}
        real = dim_country[dim_country["is_real_country"]]
        name_map: dict[str, str] = {}
        for _, row in real.iterrows():
            key = row["country_name"].strip().lower()
            if key in name_map and name_map[key] != row["country_iso2"]:
                raise ValueError(
                    f"dim_country: country_name {row['country_name']!r} maps to "
                    f"more than one country_iso2 ({name_map[key]}, {row['country_iso2']})"
                )
            name_map[key] = row["country_iso2"]
        self._name_map = name_map
        self._pseudo_aliases = {k.strip().lower(): v for k, v in pseudo_code_aliases.items()}
        if any(v == ZZ_CODE for v in self._pseudo_aliases.values()):
            raise ValueError("pseudo_code_aliases config must never alias to ZZ")

    def resolve(self, raw_value: str) -> dict:
        stripped = raw_value.strip()
        upper = stripped.upper()
        lower = stripped.lower()

        if upper != ZZ_CODE and upper in self._iso2_set:
            return {
                "proposed_iso2": upper,
                "confidence": "high",
                "method": "exact_iso2",
                "note": "",
            }
        if lower in self._pseudo_aliases:
            return {
                "proposed_iso2": self._pseudo_aliases[lower],
                "confidence": "high",
                "method": "pseudo_code",
                "note": "",
            }
        if lower in self._name_map:
            return {
                "proposed_iso2": self._name_map[lower],
                "confidence": "high",
                "method": "exact_name",
                "note": "",
            }
        if upper == ZZ_CODE:
            return {
                "proposed_iso2": "",
                "confidence": "none",
                "method": "unresolved",
                "note": "raw value is literally ZZ; ZZ is never written as a proposal",
            }
        return {
            "proposed_iso2": "",
            "confidence": "none",
            "method": "unresolved",
            "note": "",
        }


def build_alias_crosswalk_proposed(
    raw_country_strings: pd.DataFrame,
    dim_country: pd.DataFrame,
    pseudo_code_aliases: dict[str, str],
    known_trap_notes: dict[str, str] | None = None,
) -> pd.DataFrame:
    """One row per distinct (source_system, raw_value) from ``raw_country_strings``.

    ``known_trap_notes`` optionally attaches a documentation note (never a
    code) to a raw_value that is a documented EA name variant (build plan
    4.5 traps) even when it is left unresolved, so a human reviewer sees the
    hint without the build guessing on their behalf.
    """
    known_trap_notes = known_trap_notes or {}
    resolver = AliasResolver(dim_country, pseudo_code_aliases)

    pairs = (
        raw_country_strings[["source_system", "raw_value"]]
        .drop_duplicates()
        .sort_values(["source_system", "raw_value"])
        .reset_index(drop=True)
    )

    rows = []
    for _, pair in pairs.iterrows():
        result = resolver.resolve(pair["raw_value"])
        if result["method"] == "unresolved" and not result["note"]:
            trap_note = known_trap_notes.get(pair["raw_value"], "")
            result = {**result, "note": trap_note}
        rows.append(
            {
                "source_system": pair["source_system"],
                "raw_value": pair["raw_value"],
                "proposed_iso2": result["proposed_iso2"],
                "confidence": result["confidence"],
                "method": result["method"],
                "note": result["note"],
            }
        )
    return pd.DataFrame(rows)
