"""
verify_env.py
--------------
Session 0 gate. Exit 0 means proceed; anything else means the environment is
not yet safe to build on. Six checks, each catching something that would
otherwise fail silently much later (see Appendix A.4 of the build plan):

1. Python version.
2. Every required import, with the version it resolved to.
3. DuckDB really rejects an unmapped foreign key.
4. searoute resolves a known lane to a plausible distance, and reports units.
5. pandas and geopandas interoperate on the installed pairing.
6. Expected environment variable names are present. Presence only, never a
   value.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REQUIRED_IMPORTS = [
    "pandas",
    "numpy",
    "pyarrow",
    "duckdb",
    "scipy",
    "openpyxl",
    "yaml",
    "dotenv",
    "geopandas",
    "shapely",
    "pyproj",
    "pyogrio",
    "networkx",
    "pandera",
    "plotly",
    "searoute",
    "shooju",
]

REQUIRED_ENV_VARS = [
    "MY_SHOOJU_USERNAME",
    "MY_SHOOJU_API_KEY",
    "MY_EA_API_KEY",
    "UPSTREAM_DIR",
    "WORKBOOK_ROOT",
]


def check_python_version() -> bool:
    ok = sys.version_info[:2] == (3, 12)
    print(f"[1] python version: {sys.version.split()[0]} {'OK' if ok else 'FAIL (expected 3.12)'}")
    return ok


def check_required_imports() -> bool:
    ok = True
    for name in REQUIRED_IMPORTS:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", "unknown")
            print(f"[2] import {name}: OK ({version})")
        except ImportError as exc:
            print(f"[2] import {name}: FAIL ({exc})")
            ok = False
    return ok


def check_duckdb_foreign_key() -> bool:
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE dim_country (country_iso2 VARCHAR PRIMARY KEY)")
    con.execute(
        "CREATE TABLE fact_flow (country_iso2 VARCHAR, "
        "FOREIGN KEY (country_iso2) REFERENCES dim_country(country_iso2))"
    )
    con.execute("INSERT INTO dim_country VALUES ('FR')")
    try:
        con.execute("INSERT INTO fact_flow VALUES ('ZZ')")
        print("[3] duckdb foreign key rejection: FAIL (unmapped code was accepted)")
        return False
    except duckdb.ConstraintException:
        print("[3] duckdb foreign key rejection: OK (ConstraintException raised)")
        return True
    finally:
        con.close()


def check_searoute() -> bool:
    try:
        import searoute as sr
    except ImportError as exc:
        print(f"[4] searoute: FAIL ({exc})")
        return False

    origin = [-93.87, 29.75]  # Sabine Pass
    destination = [139.75, 35.65]  # Tokyo
    route = sr.searoute(origin, destination)
    distance_km = route.properties["length"]
    distance_nm = distance_km / 1.852
    ok = 8000 < distance_nm < 11000
    print(
        f"[4] searoute Sabine Pass -> Tokyo: {distance_km:.0f} km "
        f"({distance_nm:.0f} nm, units returned by package: km) "
        f"{'OK' if ok else 'FAIL (implausible distance)'}"
    )
    return ok


def check_pandas_geopandas_interop() -> bool:
    try:
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import Point

        df = pd.DataFrame(
            {"country_iso2": ["FR", "DE"], "lon": [2.35, 13.4], "lat": [48.86, 52.52]}
        )
        gdf = gpd.GeoDataFrame(
            df, geometry=[Point(xy) for xy in zip(df.lon, df.lat)], crs="EPSG:4326"
        )
        ok = len(gdf) == 2 and gdf.crs is not None
        print(f"[5] pandas/geopandas interop: {'OK' if ok else 'FAIL'}")
        return ok
    except Exception as exc:
        print(f"[5] pandas/geopandas interop: FAIL ({exc})")
        return False


def check_env_vars() -> bool:
    import os

    if Path(".env").is_file():
        from dotenv import load_dotenv

        load_dotenv(".env")

    ok = True
    for name in REQUIRED_ENV_VARS:
        present = name in os.environ and os.environ[name] != ""
        print(f"[6] env var {name}: {'set' if present else 'NOT SET'}")
        if not present:
            ok = False
    return ok


def main() -> int:
    checks = [
        check_python_version(),
        check_required_imports(),
        check_duckdb_foreign_key(),
        check_searoute(),
        check_pandas_geopandas_interop(),
        check_env_vars(),
    ]
    if all(checks):
        print("\nverify_env: PASS")
        return 0
    print("\nverify_env: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
