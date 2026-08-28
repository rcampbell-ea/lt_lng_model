"""
pipe_flow_forecast.py
----------------------
Session 7. Builds ``fact_pipe_net_position``: net pipe bcm per
(``country_iso2``, ``year``), 2025-2050 plus history back to 2008 wherever
IEA GTF measures it, from ``config/pipeline_flows.yaml`` layered on top of
``fact_pipe_flow_hist`` (session 3, ``gtf_flows.build_fact_pipe_flow_hist``).

Two corridor sources feed the same shape (``origin_iso2``,
``destination_iso2``, ``year``, ``flow_bcm``, ``basis``):

- **measured corridors**: every (origin, destination) pair GTF actually
  observed, at its own observed value through its last observed year, then
  continued flat at a recent-year average (or a named override in
  ``measured_corridor_overrides``) out to ``horizon_end``. A corridor whose
  last observed year is stale (older than ``stale_year_threshold``) gets no
  continuation at all -- it is reported, not silently extrapolated from a
  value that may no longer reflect reality (the RU-UA trap: GTF simply
  stops carrying that pair after 2019, and flat-projecting its old ~29
  bcm/yr forward would be a fabrication, not a read of the data).
- **assumed corridors**: ``pipeline_flows.yaml``'s hand-listed pairs outside
  GTF coverage, projected from a stated current flow along a stated
  continuation path (flat/growing/declining/terminating), or left
  undecided where the analyst has not supplied a number.

GTF corridors with a pseudo-code endpoint (``XL`` "Liquefied Natural Gas",
``XN`` "Not Elsewhere Specified") are excluded before any of this runs: they
are LNG receipts or unspecified flows recorded at a GTF border point, not a
physical pipe corridor, and folding them into ``net_pipe_bcm`` would
contaminate the pipe/LNG separation session 6 built.

STEP 4 new connections (``config/pipeline_projects.yaml``) are not netted
here: none has a stated ``flow_bcma`` and ``start_year`` yet, so none has a
defensible year to begin contributing -- documented, not projected, until
an analyst fills them in.
"""

from __future__ import annotations

import pandas as pd

_BASIS_PRECEDENCE = {"undecided": 3, "assumed": 2, "measured": 1, "explicit_zero": 0}


def corridor_months_observed(
    gtf_long: pd.DataFrame, applied_crosswalk: pd.DataFrame
) -> pd.DataFrame:
    """(origin_iso2, destination_iso2, year, months_observed) from the raw
    monthly GTF rows -- ``fact_pipe_flow_hist`` alone throws month
    granularity away by summing it, so this is rebuilt from the same raw
    input net_pipe_position.py uses for its own, country-level
    months_observed."""
    xwalk = applied_crosswalk[applied_crosswalk["source_system"] == "iea_gtf"]
    lookup = xwalk.set_index("raw_value")["country_iso2"]

    df = gtf_long.copy()
    df["origin_iso2"] = df["exit_raw"].map(lookup)
    df["destination_iso2"] = df["entry_raw"].map(lookup)

    unresolved_exit = df.loc[df["origin_iso2"].isnull(), "exit_raw"].unique()
    unresolved_entry = df.loc[df["destination_iso2"].isnull(), "entry_raw"].unique()
    if len(unresolved_exit) or len(unresolved_entry):
        raise ValueError(
            f"corridor_months_observed: unresolved GTF Exit/Entry values -- "
            f"exit={sorted(unresolved_exit.tolist())}, entry={sorted(unresolved_entry.tolist())}"
        )
    return (
        df.groupby(["origin_iso2", "destination_iso2", "year"])["month_col"]
        .nunique()
        .rename("months_observed")
        .reset_index()
    )


def project_measured_corridors(
    fact_pipe_flow_hist: pd.DataFrame,
    months_observed: pd.DataFrame,
    real_country_codes: set[str],
    overrides: list[dict],
    default_continuation: dict,
    horizon_end: int,
    stale_year_threshold: int,
) -> tuple[pd.DataFrame, list[dict]]:
    """Returns (corridor timeseries, stale_corridors). ``stale_corridors``
    lists corridors whose last observed year is older than
    ``stale_year_threshold`` -- excluded from continuation entirely rather
    than flat-projected from a value that may not reflect current reality,
    per this module's docstring."""
    hist = fact_pipe_flow_hist[
        fact_pipe_flow_hist["origin_iso2"].isin(real_country_codes)
        & fact_pipe_flow_hist["destination_iso2"].isin(real_country_codes)
    ].copy()

    rows = [
        hist[["origin_iso2", "destination_iso2", "year", "bcm"]]
        .rename(columns={"bcm": "flow_bcm"})
        .assign(basis="measured")
    ]

    overrides_lookup = {(o["origin_iso2"], o["destination_iso2"]): o for o in overrides}
    stale_corridors: list[dict] = []

    for (origin, destination), grp in hist.groupby(["origin_iso2", "destination_iso2"]):
        last_year = int(grp["year"].max())
        if last_year < stale_year_threshold:
            stale_corridors.append(
                {
                    "origin_iso2": origin,
                    "destination_iso2": destination,
                    "last_observed_year": last_year,
                }
            )
            continue

        override = overrides_lookup.get((origin, destination))
        lookback_years = (
            override["lookback_years"] if override else default_continuation["lookback_years"]
        )

        mo = months_observed[
            (months_observed["origin_iso2"] == origin)
            & (months_observed["destination_iso2"] == destination)
        ]
        complete_years = set(mo.loc[mo["months_observed"] >= 12, "year"])
        candidate_years = sorted((y for y in grp["year"] if y in complete_years), reverse=True)[
            :lookback_years
        ]
        if not candidate_years:
            candidate_years = [last_year]
        continuation_value = grp.loc[grp["year"].isin(candidate_years), "bcm"].mean()

        if last_year < horizon_end:
            continuation_years = range(last_year + 1, horizon_end + 1)
            rows.append(
                pd.DataFrame(
                    {
                        "origin_iso2": origin,
                        "destination_iso2": destination,
                        "year": list(continuation_years),
                        "flow_bcm": continuation_value,
                        "basis": "assumed",
                    }
                )
            )

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["origin_iso2", "destination_iso2", "year"]).reset_index(drop=True)
    return out, stale_corridors


def _anchor_year(basis_year) -> int:
    """``basis_year`` is normally an int; ``pipeline_flows.yaml`` allows a
    string like "2013-2023 average" where no single year was published --
    the average's own end year anchors the continuation."""
    if isinstance(basis_year, int):
        return basis_year
    text = str(basis_year)
    if "-" in text:
        return int(text.split("-")[1].split()[0])
    return int(text)


def _value_at_year(current_flow: float, anchor_year: int, continuation: dict, year: int) -> float:
    path = continuation["path"]
    if path == "flat":
        return current_flow
    if path == "terminating":
        terminal_year = continuation["terminal_year"]
        if year >= terminal_year:
            return 0.0
        if year <= anchor_year:
            return current_flow
        frac = (year - anchor_year) / (terminal_year - anchor_year)
        return current_flow * (1 - frac)
    if path in ("growing", "declining"):
        target_flow = continuation["target_flow_bcma"]
        target_year = continuation["target_year"]
        if year >= target_year:
            return target_flow
        if year <= anchor_year:
            return current_flow
        frac = (year - anchor_year) / (target_year - anchor_year)
        return current_flow + (target_flow - current_flow) * frac
    raise ValueError(f"_value_at_year: unknown continuation path {path!r}")


def project_assumed_corridors(
    corridors_assumed: list[dict], horizon_start: int, horizon_end: int
) -> tuple[pd.DataFrame, list[dict]]:
    """Returns (corridor timeseries, undecided_corridors). A corridor with
    ``continuation.path == "undecided"`` (or no ``current_flow_bcma``)
    carries a null ``flow_bcm`` and ``basis == "undecided"`` for every
    horizon year -- never zero-filled -- and is also returned separately so
    the caller can name it in the session report."""
    years = list(range(horizon_start, horizon_end + 1))
    rows = []
    undecided = []

    for corridor in corridors_assumed:
        origin, destination = corridor["origin_iso2"], corridor["destination_iso2"]
        continuation = corridor["continuation"]
        current_flow = corridor.get("current_flow_bcma")

        if continuation["path"] == "undecided" or current_flow is None:
            undecided.append(
                {
                    "origin_iso2": origin,
                    "destination_iso2": destination,
                    "note": corridor.get("note"),
                    "source": corridor.get("source"),
                }
            )
            rows.append(
                pd.DataFrame(
                    {
                        "origin_iso2": origin,
                        "destination_iso2": destination,
                        "year": years,
                        "flow_bcm": None,
                        "basis": "undecided",
                    }
                )
            )
            continue

        anchor_year = _anchor_year(corridor["basis_year"])
        values = [_value_at_year(current_flow, anchor_year, continuation, y) for y in years]
        rows.append(
            pd.DataFrame(
                {
                    "origin_iso2": origin,
                    "destination_iso2": destination,
                    "year": years,
                    "flow_bcm": values,
                    "basis": "assumed",
                }
            )
        )

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["origin_iso2", "destination_iso2", "year"]).reset_index(drop=True)
    return out, undecided


def check_corridor_adjacency(
    corridors: list[tuple[str, str]], dim_country_adjacency: pd.DataFrame
) -> list[tuple[str, str]]:
    """Corridors with neither geometric adjacency nor a signed-off override
    row in ``dim_country_adjacency`` -- the same check build plan session 3
    added (``pipe_checks.check_gtf_adjacency``), applied here to the
    hand-listed ``corridors_assumed`` pairs rather than to GTF's own. Does
    not raise: flagged pairs are real, named links (subsea pipelines,
    multi-country transit corridors) reported in the session doc, not data
    errors."""
    pairs = set(map(tuple, dim_country_adjacency.values.tolist()))
    return [(o, d) for o, d in corridors if (o, d) not in pairs and (d, o) not in pairs]


def net_country_position(
    corridor_timeseries: pd.DataFrame,
    modelled_countries: list[str],
    zero_countries: list[str],
    horizon_start: int,
    horizon_end: int,
    history_start: int,
) -> pd.DataFrame:
    """(country_iso2, year, net_pipe_bcm, basis) for every modelled country
    over 2025-``horizon_end``, plus history back to ``history_start`` for
    any country a measured corridor actually touches that far back.
    ``net_pipe_bcm`` is exports minus imports, summed over every corridor
    touching that country that year; ``basis`` is the least-certain basis
    among those touching corridors (undecided > assumed > measured >
    explicit_zero) -- a country blending a measured and an assumed corridor
    in the same year is reported ``assumed``, not silently ``measured``.
    A country/year with no touching corridor at all gets ``net_pipe_bcm``
    null and no row unless it is in ``zero_countries``, in which case it is
    an explicit, stated zero, not an absence.
    """
    exports = corridor_timeseries.rename(
        columns={"origin_iso2": "country_iso2", "flow_bcm": "export_bcm"}
    )[["country_iso2", "year", "export_bcm", "basis"]]
    imports = corridor_timeseries.rename(
        columns={"destination_iso2": "country_iso2", "flow_bcm": "import_bcm"}
    )[["country_iso2", "year", "import_bcm", "basis"]]

    touches = pd.concat(
        [
            exports.rename(columns={"export_bcm": "value"}).assign(direction="export"),
            imports.rename(columns={"import_bcm": "value"}).assign(direction="import"),
        ],
        ignore_index=True,
    )

    def _agg(group: pd.DataFrame) -> pd.Series:
        values = pd.to_numeric(group["value"], errors="coerce")
        signed = values.where(group["direction"] == "export", -values)
        worst_basis = max(group["basis"], key=lambda b: _BASIS_PRECEDENCE[b])
        net = pd.NA if signed.isnull().any() else signed.sum()
        return pd.Series({"net_pipe_bcm": net, "basis": worst_basis})

    netted = touches.groupby(["country_iso2", "year"]).apply(_agg).reset_index()

    frames = [netted[netted["country_iso2"].isin(modelled_countries)]]

    touched = set(map(tuple, netted[["country_iso2", "year"]].itertuples(index=False, name=None)))
    zero_rows = [
        {"country_iso2": c, "year": y, "net_pipe_bcm": 0.0, "basis": "explicit_zero"}
        for c in zero_countries
        for y in range(history_start, horizon_end + 1)
        if (c, y) not in touched
    ]
    frames.append(pd.DataFrame(zero_rows))

    out = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["country_iso2", "year"])
        .reset_index(drop=True)
    )

    horizon_years = set(range(horizon_start, horizon_end + 1))
    have = set(map(tuple, out[["country_iso2", "year"]].itertuples(index=False, name=None)))
    missing = [(c, y) for c in modelled_countries for y in horizon_years if (c, y) not in have]
    if missing:
        raise ValueError(
            f"net_country_position: {len(missing)} modelled country-year cells have no corridor "
            f"and are not in zero_countries -- add a corridor or an explicit_zero entry, do not "
            f"leave a silent gap. First few: {sorted(missing)[:10]}"
        )

    return out
