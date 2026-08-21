"""
area_node_proposal.py
-----------------------
Session 1, build plan 4.6b. Proposes, never applies, a mapping from EA's
cargo-tracking areas to the ``node_id`` values section 4.3 of the forecast
plan names for the four split countries (US, Canada, Russia, Australia).

A proposal is made only where an area's actual member-country list, read
from ``ea_ct_area_country``, is a single country matching a curated
candidate in ``config/area_node_candidates.yaml``, and only where the
candidate's node_id is one of the ids named in ``config/lng_nodes.yaml``.
Everything else -- a multi-country area, an area outside the curated
candidate list, or a candidate whose node_id the plan does not name -- is
left unresolved with the discrepancy stated in the note. No node_id is ever
invented.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml


def load_valid_node_ids(lng_nodes_config_path: Path) -> set[str]:
    with lng_nodes_config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    node_ids: set[str] = set()
    for ids in cfg["split_country_nodes"].values():
        node_ids.update(ids)
    return node_ids


def load_area_node_candidates(candidates_config_path: Path) -> dict[str, dict]:
    with candidates_config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {c["area_name"]: c for c in cfg["candidates"]}


def build_area_node_proposal(
    ea_ct_area: pd.DataFrame,
    ea_ct_area_country: pd.DataFrame,
    candidates_by_area_name: dict[str, dict],
    valid_node_ids: set[str],
) -> pd.DataFrame:
    rows = []
    for _, area in ea_ct_area.iterrows():
        area_id = area["area_id"]
        area_name = area["area_name"]
        member_countries = sorted(
            ea_ct_area_country.loc[
                ea_ct_area_country["area_id"] == area_id, "country_iso2"
            ].unique()
        )
        candidate = candidates_by_area_name.get(area_name)

        proposed_node_id = ""
        confidence = "none"

        if len(member_countries) > 1:
            note = (
                f"multi country area ({len(member_countries)} countries: "
                f"{', '.join(member_countries)}); a multi country area is not a node"
            )
        elif candidate is None:
            note = (
                "not among the split-country candidate areas named in build "
                "plan 4.6b; a single node country's node id is out of scope "
                "for this proposal"
            )
        else:
            expected = candidate["expected_country_iso2"]
            node_id = candidate["candidate_node_id"]
            if member_countries != [expected]:
                note = (
                    f"expected a single country {expected} for this candidate, "
                    f"found {member_countries or 'no countries'}"
                )
            elif node_id not in valid_node_ids:
                note = (
                    f"EA's taxonomy is finer than the plan's: no node id "
                    f"'{node_id}' is named in section 4.3; leaving unresolved "
                    f"rather than inventing one"
                )
            else:
                proposed_node_id = node_id
                confidence = "high"
                note = "unambiguous single country match to a section 4.3 node id"

        rows.append(
            {
                "area_id": area_id,
                "area_name": area_name,
                "suez_position": area["suez_position"],
                "country_iso2_list": "|".join(member_countries),
                "proposed_node_id": proposed_node_id,
                "confidence": confidence,
                "note": note,
            }
        )

    return pd.DataFrame(rows)
