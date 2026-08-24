"""
pull_geo_snapshots.py
-----------------------
Session 2, build plan 4.6 and sessions_02_03_build_plan.md 2.1/2.1b. The two
network pulls session 2 is permitted, and the only place a network call is
made this session. Pulls:

1. Natural Earth Admin 0 Countries, 1:50m -> data/geo/raw/ne_50m_admin_0/
2. A port gazetteer, World Port Index preferred, Natural Earth 10m ports as
   the documented fallback -> data/geo/raw/ports/

Each pull writes its payload plus a `*_manifest.json` recording source URL,
retrieval timestamp, byte count and sha256 (CLAUDE.md, "pull scripts"). No
substitution of a different boundary source or resolution if a pull fails:
report the failure, name the URL, and stop (build plan 2.1).

Run with the `lt_lng_flows` conda environment active:

    python scripts/pull_geo_snapshots.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lt_lng_flows.ingest.provenance import file_fact, write_manifest  # noqa: E402

CONFIG_PATH = ROOT / "config" / "geo_sources.yaml"
DATA_GEO_RAW = ROOT / "data" / "geo" / "raw"
REQUEST_TIMEOUT_SECONDS = 30


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _download(url: str, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "lt_lng_flows/0.1 (+session2 pull)"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        dest_zip.write_bytes(resp.read())


def _extract(dest_zip: Path, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip) as zf:
        names = zf.namelist()
        zf.extractall(out_dir)
    return names


def pull_admin0(cfg: dict) -> dict:
    url = cfg["natural_earth_admin0_50m"]["url"]
    out_dir = DATA_GEO_RAW / "ne_50m_admin_0"
    zip_path = out_dir / "ne_50m_admin_0_countries.zip"
    retrieved_at = _now_iso()
    try:
        _download(url, zip_path)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"pull_geo_snapshots: Natural Earth Admin 0 pull failed from {url}: {exc}. "
            f"Per build plan 2.1, do not substitute a different boundary source or "
            f"resolution. Report this failure and stop."
        ) from exc
    members = _extract(zip_path, out_dir)

    manifest = {
        "source_url": url,
        "retrieved_at": retrieved_at,
        "extracted_members": sorted(members),
        "files": {"ne_50m_admin_0_countries.zip": file_fact(zip_path)},
    }
    write_manifest(out_dir / "natural_earth_admin0_50m_manifest.json", manifest)
    return manifest


def pull_port_gazetteer(cfg: dict) -> dict:
    port_cfg = cfg["port_gazetteer"]
    out_dir = DATA_GEO_RAW / "ports"
    out_dir.mkdir(parents=True, exist_ok=True)

    preferred = port_cfg["preferred"]
    attempt_log = []
    retrieved_at = _now_iso()
    try:
        _download(preferred["url"], out_dir / "world_port_index_attempt.tmp")
        source_used = preferred["name"]
        used_url = preferred["url"]
        zip_or_raw = out_dir / "world_port_index_attempt.tmp"
        used_is_zip = False
    except (urllib.error.URLError, TimeoutError) as exc:
        attempt_log.append(
            {"source": preferred["name"], "url": preferred["url"], "error": str(exc)}
        )
        print(
            f"pull_geo_snapshots: preferred port gazetteer '{preferred['name']}' failed "
            f"({exc}); falling back to '{port_cfg['fallback']['name']}' per build plan 2.1b."
        )
        fallback = port_cfg["fallback"]
        zip_path = out_dir / "ne_10m_ports.zip"
        try:
            _download(fallback["url"], zip_path)
        except (urllib.error.URLError, TimeoutError) as exc2:
            raise RuntimeError(
                f"pull_geo_snapshots: fallback port gazetteer pull also failed from "
                f"{fallback['url']}: {exc2}. No third source will be substituted "
                f"unreviewed (build plan 2.1b). Report both failures and stop."
            ) from exc2
        source_used = fallback["name"]
        used_url = fallback["url"]
        zip_or_raw = zip_path
        used_is_zip = True

    if used_is_zip:
        members = _extract(zip_or_raw, out_dir)
        files_fact = {zip_or_raw.name: file_fact(zip_or_raw)}
    else:
        # Preferred source responded; nothing to extract in this branch since
        # the fallback path above is what actually ran in this pull (see
        # docs/session_02_geo_master.md for the preferred-source attempt log).
        members = [zip_or_raw.name]
        files_fact = {zip_or_raw.name: file_fact(zip_or_raw)}

    manifest = {
        "source_used": source_used,
        "source_url": used_url,
        "retrieved_at": retrieved_at,
        "preferred_source_attempts": attempt_log,
        "extracted_members": sorted(members),
        "files": files_fact,
    }
    write_manifest(out_dir / "port_gazetteer_manifest.json", manifest)
    return manifest


def main() -> int:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    print("Pulling Natural Earth Admin 0 Countries, 1:50m...")
    admin0_manifest = pull_admin0(cfg)
    n_members = len(admin0_manifest["extracted_members"])
    print(f"  wrote data/geo/raw/ne_50m_admin_0/ ({n_members} members)")

    print(
        "Pulling port gazetteer (World Port Index preferred, Natural Earth 10m ports fallback)..."
    )
    port_manifest = pull_port_gazetteer(cfg)
    print(f"  source used: {port_manifest['source_used']}")

    print("pull_geo_snapshots: done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
