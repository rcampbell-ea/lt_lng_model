"""
session6_outputs.py
--------------------
Session 6 deliverables: the xlsx workbook (surplus/deficit pivot plus the
long-form components sheet) and the self-contained Plotly HTML page. No
value is derived, interpreted or compared against outside knowledge here --
this module only reshapes and renders ``fact_net_gas_position`` as built by
``lt_lng_flows.model.net_gas_position`` and
``lt_lng_flows.pipe.net_pipe_position``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.offline as pyo

_NA_REP = ""  # a blank cell, never a zero (CLAUDE.md, "a null beats a plausible invented number")


def _with_country_name(df: pd.DataFrame, dim_country: pd.DataFrame) -> pd.DataFrame:
    names = dim_country[["country_iso2", "country_name_display"]]
    out = df.merge(names, on="country_iso2", how="left")
    cols = ["country_iso2", "country_name_display"] + [
        c for c in out.columns if c not in ("country_iso2", "country_name_display")
    ]
    return out[cols]


def write_xlsx(combined: pd.DataFrame, dim_country: pd.DataFrame, out_path: Path) -> None:
    """Sheet 1: one row per country, one column per year, surplus_deficit_bcm,
    sorted by |value| in the latest year present (countries with no value
    that year sort last -- they are not zero, they are unranked). Sheet 2:
    the long-form components table. Both carry the country's display name
    beside its ISO2 code, from dim_country -- never an ISO code alone."""
    all_countries = sorted(combined["country_iso2"].unique())
    all_years = sorted(combined["year"].unique())
    pivot = combined.pivot_table(
        index="country_iso2", columns="year", values="surplus_deficit_bcm", aggfunc="first"
    )
    # pivot_table drops an index/column entirely made of NaN (e.g. a country
    # that never has both supply and demand in the same year) -- reindex
    # back to every country and every year so "one row per country" holds
    # even when every one of its cells is blank.
    pivot = pivot.reindex(index=all_countries, columns=all_years)
    latest_year = max(all_years)
    sort_key = pivot[latest_year].abs()
    pivot = pivot.loc[sort_key.sort_values(ascending=False, na_position="last").index]
    pivot = pivot.reset_index()
    pivot = _with_country_name(pivot, dim_country)

    components = _with_country_name(
        combined[
            [
                "country_iso2",
                "year",
                "supply_bcm",
                "demand_bcm",
                "surplus_deficit_bcm",
                "net_pipe_bcm",
                "lng_net_bcm",
                "months_observed",
                "missing_side",
            ]
        ].sort_values(["country_iso2", "year"]),
        dim_country,
    )

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        pivot.to_excel(writer, sheet_name="surplus_deficit", index=False, na_rep=_NA_REP)
        components.to_excel(writer, sheet_name="components", index=False, na_rep=_NA_REP)


def _clean(value):
    """None (JSON null, renders as a Plotly gap), never NaN -- json.dumps
    would otherwise emit the non-standard literal 'NaN'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    return value


def _build_page_data(combined: pd.DataFrame, dim_country: pd.DataFrame) -> dict:
    named = _with_country_name(combined, dim_country)
    countries = (
        named[["country_iso2", "country_name_display"]]
        .drop_duplicates()
        .sort_values("country_name_display")
        .to_dict("records")
    )
    years = sorted(int(y) for y in combined["year"].unique())

    by_country: dict[str, dict[str, dict]] = {}
    for row in named.to_dict("records"):
        entry = by_country.setdefault(row["country_iso2"], {})
        entry[str(int(row["year"]))] = {
            "supply_bcm": _clean(row["supply_bcm"]),
            "demand_bcm": _clean(row["demand_bcm"]),
            "surplus_deficit_bcm": _clean(row["surplus_deficit_bcm"]),
            "net_pipe_bcm": _clean(row["net_pipe_bcm"]),
            "lng_net_bcm": _clean(row["lng_net_bcm"]),
            "months_observed": _clean(row["months_observed"]),
            "missing_side": _clean(row["missing_side"]),
        }

    return {"countries": countries, "years": years, "by_country": by_country}


def build_html(combined: pd.DataFrame, dim_country: pd.DataFrame, out_path: Path) -> None:
    """One self-contained HTML file: Plotly's JS bundle and every data value
    are inlined, so the page opens offline with no network call. Two views
    over the same table -- a year snapshot (world total plus the top 10
    surplus / top 10 deficit countries that year) and a per-country time
    series picker. The world total is the one derived figure on the page:
    sum(supply_bcm) - sum(demand_bcm) across whichever countries have both
    sides present in the selected year, using the same sign convention as
    every other supply-minus-demand figure here (positive = surplus). It is
    a plain sum of the table's own two input columns, not a comparison
    against net_pipe_bcm/lng_net_bcm or a residual -- nothing else on the
    page is derived, interpreted or compared against outside knowledge.
    """
    page_data = _build_page_data(combined, dim_country)
    plotly_js = pyo.get_plotlyjs()

    html = _PAGE_TEMPLATE.replace("__PLOTLY_JS__", plotly_js).replace(
        "__PAGE_DATA__", json.dumps(page_data)
    )
    out_path.write_text(html, encoding="utf-8")


_PAGE_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Surplus and deficit: EA supply minus EA demand</title>
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
  select, input[type=range], input[type=text] { font-size: 13px; }
  input[type=text] { padding: 3px 6px; }
  .plot { width: 100%; }
  .line-plot, .bar-plot { height: 500px; }
  .world-indicator {
    display: flex; gap: 32px; align-items: baseline; flex-wrap: wrap;
    margin: 12px 0 20px; padding: 12px 16px; background: #f5f5f5; border-radius: 4px;
  }
  .world-indicator .stat { display: flex; flex-direction: column; }
  .world-indicator .stat .label { font-size: 11px; color: #666; text-transform: uppercase; }
  .world-indicator .stat .value { font-size: 22px; font-weight: bold; }
  .world-indicator .stat .value.surplus { color: #2c7bb6; }
  .world-indicator .stat .value.deficit { color: #d7191c; }
  .world-indicator .note { font-size: 11px; color: #777; align-self: center; }
</style>
</head>
<body>

<h1>Surplus and deficit: EA supply minus EA demand</h1>
<div class="subtitle">bcm per country per year. Missing data is a gap, not a zero.</div>

<h2>Year snapshot: world total, top 10 surplus, top 10 deficit</h2>
<div class="controls">
  <label for="year-select">Year</label>
  <select id="year-select"></select>
</div>
<div id="world-indicator" class="world-indicator"></div>
<div id="year-plot" class="plot bar-plot"></div>

<h2>Country: supply, demand, surplus_deficit, net_pipe, lng_net over time</h2>
<div class="controls">
  <label for="country-select">Country</label>
  <select id="country-select"></select>
</div>
<div id="country-plot" class="plot line-plot"></div>

<script>
const DATA = __PAGE_DATA__;

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

const X_START = 2024;

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
  const hover = (label, field) => years.map(y => {
    const s = valueAt(iso2, y, "supply_bcm");
    const d = valueAt(iso2, y, "demand_bcm");
    const sTxt = s === null ? "n/a" : s.toFixed(2);
    const dTxt = d === null ? "n/a" : d.toFixed(2);
    return countryLabel(iso2) + "<br>Year: " + y + "<br>Supply: " + sTxt +
      " bcm<br>Demand: " + dTxt + " bcm";
  });

  const traces = [
    { name: "supply_bcm", x: years, y: series("supply_bcm"), mode: "lines",
      line: { color: "#2c7bb6" },
      text: hover(), hovertemplate: "%{text}<extra>supply_bcm</extra>" },
    { name: "demand_bcm", x: years, y: series("demand_bcm"), mode: "lines",
      line: { color: "#d7191c" },
      text: hover(), hovertemplate: "%{text}<extra>demand_bcm</extra>" },
    { name: "surplus_deficit_bcm", x: years, y: series("surplus_deficit_bcm"), mode: "lines",
      line: { color: "#222222", width: 2 },
      text: hover(), hovertemplate: "%{text}<extra>surplus_deficit_bcm</extra>" },
  ];

  const pipe = series("net_pipe_bcm");
  if (pipe.some(v => v !== null)) {
    traces.push({ name: "net_pipe_bcm", x: years, y: pipe, mode: "lines",
      line: { color: "#fdae61", dash: "dash" },
      text: hover(), hovertemplate: "%{text}<extra>net_pipe_bcm</extra>" });
  }
  const lng = series("lng_net_bcm");
  if (lng.some(v => v !== null)) {
    traces.push({ name: "lng_net_bcm", x: years, y: lng, mode: "lines",
      line: { color: "#abd9e9", dash: "dash" },
      text: hover(), hovertemplate: "%{text}<extra>lng_net_bcm</extra>" });
  }

  Plotly.react("country-plot", traces, {
    margin: { l: 60, r: 20, t: 10, b: 40 },
    xaxis: { title: "Year", range: [X_START, years[years.length - 1]] },
    yaxis: { title: "bcm", zeroline: true },
    legend: { orientation: "h", y: -0.2 },
  }, { responsive: true });
}

countrySelect.addEventListener("change", () => renderCountryPlot(countrySelect.value));
if (DATA.countries.length) {
  countrySelect.value = DATA.countries[0].country_iso2;
  renderCountryPlot(countrySelect.value);
}

// ---- Year snapshot: world total, top 10 surplus, top 10 deficit ----
const TOP_N = 10;
const yearSelect = document.getElementById("year-select");
const worldIndicator = document.getElementById("world-indicator");
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
      value: valueAt(c.country_iso2, year, "surplus_deficit_bcm"),
      supply: valueAt(c.country_iso2, year, "supply_bcm"),
      demand: valueAt(c.country_iso2, year, "demand_bcm"),
    }))
    .filter(r => r.value !== null);
}

function renderWorldIndicator(year, rows) {
  // Sum of supply and sum of demand across exactly the countries that have
  // both sides present in this year (the same set `rows` already is) --
  // not fixed at 78, since which countries have both can vary by year.
  const totalSupply = rows.reduce((sum, r) => sum + r.supply, 0);
  const totalDemand = rows.reduce((sum, r) => sum + r.demand, 0);
  const net = totalSupply - totalDemand;
  const cls = net >= 0 ? "surplus" : "deficit";
  const label = net >= 0 ? "World surplus" : "World deficit";

  worldIndicator.innerHTML =
    '<div class="stat"><span class="label">' + label + '</span>' +
    '<span class="value ' + cls + '">' + Math.abs(net).toFixed(1) + ' bcm</span></div>' +
    '<div class="stat"><span class="label">World supply</span>' +
    '<span class="value">' + totalSupply.toFixed(1) + ' bcm</span></div>' +
    '<div class="stat"><span class="label">World demand</span>' +
    '<span class="value">' + totalDemand.toFixed(1) + ' bcm</span></div>' +
    '<div class="note">Sum of supply minus sum of demand across the ' + rows.length +
    ' countries with both sides present in ' + year + '.</div>';
}

function renderYearPlot(year) {
  const all = countryRowsForYear(year);
  renderWorldIndicator(year, all);

  const sorted = all.slice().sort((a, b) => a.value - b.value);
  const deficits = sorted.slice(0, TOP_N); // most negative
  const surpluses = sorted.slice(-TOP_N).filter(r => !deficits.includes(r)); // most positive
  const rows = deficits.concat(surpluses).sort((a, b) => a.value - b.value);

  const colors = rows.map(r => (r.value >= 0 ? "#2c7bb6" : "#d7191c"));
  const hoverText = rows.map(r => {
    const sTxt = r.supply === null ? "n/a" : r.supply.toFixed(2);
    const dTxt = r.demand === null ? "n/a" : r.demand.toFixed(2);
    return r.label + "<br>Year: " + year + "<br>Surplus/deficit: " + r.value.toFixed(2) +
      " bcm<br>Supply: " + sTxt + " bcm<br>Demand: " + dTxt + " bcm";
  });

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
    margin: { l: 200, r: 40, t: 10, b: 40 },
    title: {
      text: "Top " + TOP_N + " deficit and top " + TOP_N + " surplus countries, " + year +
        " (" + rows.length + " of " + all.length + " countries with data that year shown)",
      font: { size: 12 },
    },
    xaxis: { title: "Surplus / deficit (bcm)", zeroline: true },
    yaxis: { automargin: true, tickfont: { size: 9 } },
    height: Math.max(500, rows.length * 22),
  }, { responsive: true });
}

yearSelect.addEventListener("change", () => renderYearPlot(parseInt(yearSelect.value, 10)));
if (DATA.years.length) {
  const latest = DATA.years[DATA.years.length - 1];
  yearSelect.value = latest;
  renderYearPlot(latest);
}
</script>
</body>
</html>
"""
