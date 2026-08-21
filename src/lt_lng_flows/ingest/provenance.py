"""
provenance.py
-------------
Shared helpers for the manifests that are the only tracked provenance record
for the gitignored contents of ``data/raw`` (CLAUDE.md, "data model"; build
plan 4.6d). A manifest is a plain dict of file-level facts: name, byte count,
sha256, and whatever counts or shape assertions the caller made against it.
It never records a credential, a path outside the repository, or a value
read from ``.env``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_fact(path: Path) -> dict:
    """Filename, byte count and sha256 for one file. No path outside the repo."""
    return {
        "filename": path.name,
        "byte_count": path.stat().st_size,
        "sha256": sha256_of_file(path),
    }


def write_manifest(path: Path, manifest: dict) -> None:
    if not path.name.endswith("_manifest.json"):
        raise ValueError(
            f"manifest filename must end '_manifest.json' (build plan 4.6d), got {path.name!r}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
