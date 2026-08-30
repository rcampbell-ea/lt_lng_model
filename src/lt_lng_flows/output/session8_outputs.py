"""
session8_outputs.py
--------------------
Session 8 deliverable: a self-contained Plotly HTML page over
``fact_lng_net_position`` joined against its two inputs
(``fact_net_gas_position.surplus_deficit_bcm``,
``fact_pipe_net_position.net_pipe_bcm``). No value is derived, interpreted
or compared against outside knowledge here -- this module only reshapes and
renders tables already built by ``lt_lng_flows.model.lng_net_position`` and
its upstream sessions. Built before the calculation exists, per the session
8 task: this is the inspection instrument, not a deliverable at the end --
it gets regenerated on every later session that changes a number, and a
correct run today (no analyst flow values on file) renders every country's
lng_net_bcm as a gap, which is the point, not a failure.

Follows ``session7_outputs.py`` exactly as a pattern: Plotly JS and every
data value inlined so the page opens offline with no network call, gaps via
``_clean``/``connectgaps: false`` rather than a fabricated zero, and the
x-axis range taken from the data itself rather than a hardcoded start year
(session 7's own page hardcoded ``[2008, ...]``; this page takes
``years[0]`` instead).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.offline as pyo


def _with_country_name(df: pd.DataFrame, dim_country: pd.DataFrame) -> pd.DataFrame:
    names = dim_country[["country_iso2", "country_name_display"]]
    out = df.merge(names, on="country_iso2", how="left")
    cols = ["country_iso2", "country_name_display"] + [
        c for c in out.columns if c not in ("country_iso2", "country_name_display")
    ]
    return out[cols]


def _clean(value):
    """None (JSON null, renders as a Plotly gap), never NaN -- json.dumps
    would otherwise emit the non-standard literal 'NaN'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    return value


def _build_page_data(
    lng_net_position: pd.DataFrame,
    fact_net_gas_position: pd.DataFrame,
    fact_pipe_net_position: pd.DataFrame,
    dim_country: pd.DataFrame,
) -> dict:
    combined = (
        lng_net_position[["country_iso2", "year", "lng_net_bcm"]]
        .merge(
            fact_net_gas_position[["country_iso2", "year", "surplus_deficit_bcm"]],
            on=["country_iso2", "year"],
            how="outer",
        )
        .merge(
            fact_pipe_net_position[["country_iso2", "year", "net_pipe_bcm"]],
            on=["country_iso2", "year"],
            how="outer",
        )
    )
    named = _with_country_name(combined, dim_country)
    countries = (
        named[["country_iso2", "country_name_display"]]
        .drop_duplicates()
        .sort_values("country_name_display")
        .to_dict("records")
    )
    years = sorted(int(y) for y in combined["year"].dropna().unique())

    by_country: dict[str, dict[str, dict]] = {}
    for row in named.to_dict("records"):
        entry = by_country.setdefault(row["country_iso2"], {})
        entry[str(int(row["year"]))] = {
            "surplus_deficit_bcm": _clean(row.get("surplus_deficit_bcm")),
            "net_pipe_bcm": _clean(row.get("net_pipe_bcm")),
            "lng_net_bcm": _clean(row.get("lng_net_bcm")),
        }

    n_countries = len(countries)
    latest_year = years[-1] if years else None
    n_null_latest_year = sum(
        1
        for c in countries
        if by_country.get(c["country_iso2"], {}).get(str(latest_year), {}).get("lng_net_bcm")
        is None
    )

    return {
        "countries": countries,
        "years": years,
        "by_country": by_country,
        "n_countries": n_countries,
        "latest_year": latest_year,
        "n_null_latest_year": n_null_latest_year,
    }


def build_html(
    lng_net_position: pd.DataFrame,
    fact_net_gas_position: pd.DataFrame,
    fact_pipe_net_position: pd.DataFrame,
    dim_country: pd.DataFrame,
    out_path: Path,
) -> None:
    """Two views over the same joined table: a per-country time series
    picker with all three series (surplus_deficit_bcm, net_pipe_bcm,
    lng_net_bcm) on one axis -- the view that exposes the error class this
    session exists to prevent, since pipe alone made a number look merely
    large while pipe against the country's own surplus made it impossible
    -- and a year snapshot, top 10 net exporters and top 10 net importers by
    lng_net_bcm, sorted horizontal bars, following session 7's pattern.
    """
    page_data = _build_page_data(
        lng_net_position, fact_net_gas_position, fact_pipe_net_position, dim_country
    )
    plotly_js = pyo.get_plotlyjs()

    html = _PAGE_TEMPLATE.replace("__PLOTLY_JS__", plotly_js).replace(
        "__PAGE_DATA__", json.dumps(page_data)
    )
    out_path.write_text(html, encoding="utf-8")


_PAGE_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Derived LNG net position, surplus minus pipe</title>
<script>__PLOTLY_JS__</script>
<style>
  body {
    font-family: Arial, Helvetica, sans-serif; margin: 0;
    padding: 16px 24px 40px; color: #222;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  h2 { font-size: 15px; margin: 28px 0 8px; border-top: 1px solid #ccc; padding-top: 16px; }
  .subtitle { color: #555; font-size: 13px; margin-bottom: 20px; }
  .controls { margin-bottom: 8px; font-size: 13px; }
  .controls label { margin-right: 6px; }
  select { font-size: 13px; }
  .plot { width: 100%; }
  .line-plot, .bar-plot { height: 500px; }
  .legend-note {
    display: flex; gap: 18px; align-items: center; flex-wrap: wrap;
    margin: 12px 0 20px; padding: 10px 16px; background: #f5f5f5; border-radius: 4px;
    font-size: 12px;
  }
</style>
</head>
<body>

<h1>Derived LNG net position: surplus_deficit_bcm minus net_pipe_bcm</h1>
<div class="subtitle" id="subtitle"></div>
<div class="legend-note">
  <span>lng_net_bcm = surplus_deficit_bcm - net_pipe_bcm, per country per year. A gap is a
  country with no analyst-entered pipe number yet -- never a fabricated zero.</span>
</div>

<h2>Country: surplus, pipe and derived LNG net over time</h2>
<div class="controls">
  <label for="country-select">Country</label>
  <select id="country-select"></select>
</div>
<div id="country-plot" class="plot line-plot"></div>

<h2>Year snapshot: top 10 net exporters, top 10 net importers (lng_net_bcm)</h2>
<div class="controls">
  <label for="year-select">Year</label>
  <select id="year-select"></select>
</div>
<div id="year-plot" class="plot bar-plot"></div>

<script>
const DATA = __PAGE_DATA__;

document.getElementById("subtitle").textContent =
  DATA.n_countries + " countries in scope" +
  (DATA.latest_year === null ? "" :
    "; " + DATA.n_null_latest_year + " of " + DATA.n_countries +
    " carry no derived LNG number in " + DATA.latest_year + " (undecided pipe corridors).");

function valueAt(iso2, year, field) {
  const c = DATA.by_country[iso2];
  if (!c) return null;
  const y = c[String(year)];
  if (!y) return null;
  return y[field];
}

function countryLabel(iso2) {
  const c = DATA.countries.find(c => c.country_iso2 === iso2);
  return c ? c.country_name_display + " (" + iso2 + ")" : iso2;
}

// ---- Country picker ----
const countrySelect = document.getElementById("country-select");
DATA.countries.forEach(c => {
  const opt = document.createElement("option");
  opt.value = c.country_iso2;
  opt.textContent = c.country_name_display + " (" + c.country_iso2 + ")";
  countrySelect.appendChild(opt);
});

function renderCountryPlot(iso2) {
  const years = DATA.years;
  const series = (field) => years.map(y => valueAt(iso2, y, field));
  const hover = (field, label) => years.map(y => {
    const v = valueAt(iso2, y, field);
    const vTxt = v === null ? "null" : v.toFixed(2) + " bcm";
    return countryLabel(iso2) + "<br>Year: " + y + "<br>" + label + ": " + vTxt;
  });

  const traces = [
    { name: "surplus_deficit_bcm", x: years, y: series("surplus_deficit_bcm"),
      mode: "lines+markers",
      connectgaps: false, line: { color: "#2c7bb6" },
      text: hover("surplus_deficit_bcm", "surplus_deficit_bcm"),
      hovertemplate: "%{text}<extra></extra>" },
    { name: "net_pipe_bcm", x: years, y: series("net_pipe_bcm"), mode: "lines+markers",
      connectgaps: false, line: { color: "#fdae61" },
      text: hover("net_pipe_bcm", "net_pipe_bcm"),
      hovertemplate: "%{text}<extra></extra>" },
    { name: "lng_net_bcm", x: years, y: series("lng_net_bcm"), mode: "lines+markers",
      connectgaps: false, line: { color: "#222222", width: 2 },
      text: hover("lng_net_bcm", "lng_net_bcm"),
      hovertemplate: "%{text}<extra></extra>" },
  ];

  Plotly.react("country-plot", traces, {
    margin: { l: 60, r: 20, t: 10, b: 40 },
    xaxis: { title: "Year", range: [years[0], years[years.length - 1]] },
    yaxis: { title: "bcm", zeroline: true },
    legend: { orientation: "h", y: -0.2 },
  }, { responsive: true });
}

countrySelect.addEventListener("change", () => renderCountryPlot(countrySelect.value));
if (DATA.countries.length) {
  countrySelect.value = DATA.countries[0].country_iso2;
  renderCountryPlot(countrySelect.value);
}

// ---- Year snapshot: top 10 net exporters, top 10 net importers ----
const TOP_N = 10;
const yearSelect = document.getElementById("year-select");
DATA.years.forEach(y => {
  const opt = document.createElement("option");
  opt.value = y;
  opt.textContent = y;
  yearSelect.appendChild(opt);
});

function countryRowsForYear(year) {
  return DATA.countries
    .map(c => ({
      iso2: c.country_iso2,
      label: countryLabel(c.country_iso2),
      value: valueAt(c.country_iso2, year, "lng_net_bcm"),
    }))
    .filter(r => r.value !== null);
}

function renderYearPlot(year) {
  const all = countryRowsForYear(year);
  const nullCount = DATA.countries.length - all.length;

  const sorted = all.slice().sort((a, b) => a.value - b.value);
  const importers = sorted.slice(0, TOP_N); // most negative net (net importer)
  const exporters = sorted.slice(-TOP_N).filter(r => !importers.includes(r));
  const rows = importers.concat(exporters).sort((a, b) => a.value - b.value);

  const colors = rows.map(r => (r.value >= 0 ? "#2c7bb6" : "#d7191c"));
  const hoverText = rows.map(r =>
    r.label + "<br>Year: " + year + "<br>lng_net_bcm: " + r.value.toFixed(2)
  );

  const trace = {
    type: "bar",
    orientation: "h",
    y: rows.map(r => r.label),
    x: rows.map(r => r.value),
    marker: { color: colors },
    text: hoverText,
    hovertemplate: "%{text}<extra></extra>",
  };

  Plotly.react("year-plot", [trace], {
    margin: { l: 200, r: 40, t: 30, b: 40 },
    title: {
      text: DATA.countries.length + " countries in scope, " + year + ": " +
        rows.length + " with a derived LNG number shown (top " + TOP_N + " exporters/importers), " +
        nullCount + " null (no analyst pipe number yet)",
      font: { size: 12 },
    },
    xaxis: { title: "lng_net_bcm (positive = net exporter)", zeroline: true },
    yaxis: { automargin: true, tickfont: { size: 9 } },
    height: Math.max(500, rows.length * 22),
  }, { responsive: true });
}

yearSelect.addEventListener("change", () => renderYearPlot(parseInt(yearSelect.value, 10)));
if (DATA.years.length) {
  const defaultYear = DATA.latest_year !== null
    ? DATA.latest_year : DATA.years[DATA.years.length - 1];
  yearSelect.value = defaultYear;
  renderYearPlot(defaultYear);
}
</script>
</body>
</html>
"""
