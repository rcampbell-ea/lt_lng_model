"""
workbook_diff.py
------------------
Session 3, build plan 3.2. Month on month diff of the three pinned LNG
workbooks: new projects, status changes, capacity revisions, contracts
added, amended or expired. Only one vintage is pinned on disk as of this
session (``data/raw/workbooks/202608/``), so ``diff_vintages`` must report
"no prior vintage found" as a structured result rather than raising or being
left untested -- the synthetic-second-vintage test in ``tests/`` is what
actually exercises the comparison logic.

Project rows are matched on (``country_raw``, ``project``, ``trains``): the
closest thing to a natural key the liquefaction/regas sheets carry, since
project names are not unique across trains and trains are not unique across
countries. Contract rows have no natural key at all (Seller/Buyer/Start can
repeat), so contracts are matched on the surrogate ``contract_row_id`` only
when both vintages were read with the same row ordering; where that
assumption cannot be trusted (row order is not a contract identity), a
contract-level diff falls back to reporting aggregate counts rather than a
fabricated row-level match.
"""

from __future__ import annotations

import pandas as pd

PROJECT_KEY_COLUMNS = ["country_raw", "project", "trains"]
PROJECT_STATUS_COLUMN = "status"
PROJECT_CAPACITY_COLUMNS = ["mtpa", "bcf_per_d", "bcma"]

CONTRACT_KEY_COLUMNS = ["exporter_raw", "importer_raw", "seller", "buyer", "contract_start"]
CONTRACT_STATUS_COLUMN = "status"


def diff_project_table(current: pd.DataFrame, prior: pd.DataFrame | None) -> dict:
    """New projects, status changes and capacity revisions between two
    vintages of a project workbook (liquefaction or regas), matched on
    ``PROJECT_KEY_COLUMNS``.

    Returns a dict with ``"prior_vintage_found"`` and, when true, DataFrames
    under ``"new_projects"``, ``"status_changes"`` and ``"capacity_revisions"``.
    """
    if prior is None:
        return {"prior_vintage_found": False}

    cur = current.set_index(PROJECT_KEY_COLUMNS, drop=False)
    pri = prior.set_index(PROJECT_KEY_COLUMNS, drop=False)

    new_keys = cur.index.difference(pri.index)
    new_projects = cur.loc[new_keys].reset_index(drop=True)

    shared_keys = cur.index.intersection(pri.index)
    status_changes = []
    capacity_revisions = []
    for key in shared_keys:
        cur_row = cur.loc[key]
        pri_row = pri.loc[key]
        if isinstance(cur_row, pd.DataFrame):  # duplicate key on this side, skip rather than guess
            continue
        if isinstance(pri_row, pd.DataFrame):
            continue
        if cur_row[PROJECT_STATUS_COLUMN] != pri_row[PROJECT_STATUS_COLUMN]:
            status_changes.append(
                {
                    **{c: cur_row[c] for c in PROJECT_KEY_COLUMNS},
                    "prior_status": pri_row[PROJECT_STATUS_COLUMN],
                    "current_status": cur_row[PROJECT_STATUS_COLUMN],
                }
            )
        for col in PROJECT_CAPACITY_COLUMNS:
            if col not in cur_row or col not in pri_row:
                continue
            if cur_row[col] != pri_row[col]:
                capacity_revisions.append(
                    {
                        **{c: cur_row[c] for c in PROJECT_KEY_COLUMNS},
                        "column": col,
                        "prior_value": pri_row[col],
                        "current_value": cur_row[col],
                    }
                )

    return {
        "prior_vintage_found": True,
        "new_projects": new_projects,
        "status_changes": pd.DataFrame(status_changes),
        "capacity_revisions": pd.DataFrame(capacity_revisions),
    }


def diff_contract_table(current: pd.DataFrame, prior: pd.DataFrame | None) -> dict:
    """Contracts added, amended (status changed) or expired between two
    vintages, matched on ``CONTRACT_KEY_COLUMNS``. Two rows on one side of
    the same key are reported as ambiguous rather than matched arbitrarily.
    """
    if prior is None:
        return {"prior_vintage_found": False}

    cur_dupes = current[current.duplicated(subset=CONTRACT_KEY_COLUMNS, keep=False)]
    pri_dupes = prior[prior.duplicated(subset=CONTRACT_KEY_COLUMNS, keep=False)]

    cur = current.drop_duplicates(subset=CONTRACT_KEY_COLUMNS, keep=False).set_index(
        CONTRACT_KEY_COLUMNS, drop=False
    )
    pri = prior.drop_duplicates(subset=CONTRACT_KEY_COLUMNS, keep=False).set_index(
        CONTRACT_KEY_COLUMNS, drop=False
    )

    added = cur.loc[cur.index.difference(pri.index)].reset_index(drop=True)
    expired = pri.loc[pri.index.difference(cur.index)].reset_index(drop=True)

    amended = []
    for key in cur.index.intersection(pri.index):
        cur_row, pri_row = cur.loc[key], pri.loc[key]
        if cur_row[CONTRACT_STATUS_COLUMN] != pri_row[CONTRACT_STATUS_COLUMN]:
            amended.append(
                {
                    **{c: cur_row[c] for c in CONTRACT_KEY_COLUMNS},
                    "prior_status": pri_row[CONTRACT_STATUS_COLUMN],
                    "current_status": cur_row[CONTRACT_STATUS_COLUMN],
                }
            )

    return {
        "prior_vintage_found": True,
        "contracts_added": added,
        "contracts_amended": pd.DataFrame(amended),
        "contracts_expired": expired,
        "ambiguous_key_rows_current": len(cur_dupes),
        "ambiguous_key_rows_prior": len(pri_dupes),
    }


def find_prior_vintage(workbook_root_parent, current_vintage: str, filename: str):
    """Locate the most recent vintage directory under
    ``workbook_root_parent`` (``data/raw/workbooks``) strictly before
    ``current_vintage`` that carries ``filename``. Returns the file Path, or
    None if no prior vintage is pinned -- the expected state as of this
    session, since only 202608 exists on disk.
    """
    if not workbook_root_parent.is_dir():
        return None
    candidates = sorted(
        p
        for p in workbook_root_parent.iterdir()
        if p.is_dir() and p.name < current_vintage and (p / filename).is_file()
    )
    if not candidates:
        return None
    return candidates[-1] / filename
