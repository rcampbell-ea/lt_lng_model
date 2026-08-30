"""
session7_outputs.py
--------------------
Session 7 deliverable: a self-contained Plotly HTML page over
``fact_pipe_net_position``. No value is derived, interpreted or compared
against outside knowledge here -- this module only reshapes and renders the
table ``lt_lng_flows.pipe.pipe_flow_forecast`` already built. Every point
carries its ``basis`` (measured / assumed / explicit_zero / undecided) as a
marker colour and in its hover text, since which is which is the whole
point of this table -- a plain line chart that hid that distinction would
misrepresent it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.offline as pyo

_BASIS_COLOR = {
    "measured": "#2c7bb6",
    "assumed": "#fdae61",
    "explicit_zero": "#999999",
    "undecided": "#d7191c",
}


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


def _build_page_data(net_position: pd.DataFrame, dim_country: pd.DataFrame) -> dict:
    named = _with_country_name(net_position, dim_country)
    countries = (
        named[["country_iso2", "country_name_display"]]
        .drop_duplicates()
        .sort_values("country_name_display")
        .to_dict("records")
    )
    years = sorted(int(y) for y in net_position["year"].unique())

    by_country: dict[str, dict[str, dict]] = {}
    for row in named.to_dict("records"):
        entry = by_country.setdefault(row["country_iso2"], {})
        entry[str(int(row["year"]))] = {
            "net_pipe_bcm": _clean(row["net_pipe_bcm"]),
            "basis": row["basis"],
        }

    return {
        "countries": countries,
        "years": years,
        "by_country": by_country,
        "basis_color": _BASIS_COLOR,
    }


def build_html(net_position: pd.DataFrame, dim_country: pd.DataFrame, out_path: Path) -> None:
    """One self-contained HTML file: Plotly's JS bundle and every data value
    are inlined, so the page opens offline with no network call. Two views
    over the same table -- a year snapshot (top 10 net exporters, top 10 net
    importers that year, coloured by basis) and a per-country time series
    picker (a single net_pipe_bcm line, with each point's marker coloured by
    its own basis so a measured/assumed/undecided blend within one
    country's own history stays visible rather than being flattened into
    one colour)."""
    page_data = _build_page_data(net_position, dim_country)
    plotly_js = pyo.get_plotlyjs()

    html = _PAGE_TEMPLATE.replace("__PLOTLY_JS__", plotly_js).replace(
        "__PAGE_DATA__", json.dumps(page_data)
    )
    out_path.write_text(html, encoding="utf-8")


_PAGE_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Net pipe flow by country, 2008-2050</title>
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
  .legend-note .swatch {
    display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px;
  }
</style>
</head>
<body>

<h1>Net pipe flow by country, 2008-2050</h1>
<div class="subtitle">
  bcm per country per year, exports minus imports. No LNG number is netted against this
  (session 8) -- pipe only. A missing point is an undecided corridor, never a zero.
</div>
<div class="legend-note" id="legend-note"></div>

<h2>Year snapshot: top 10 net exporters, top 10 net importers</h2>
<div class="controls">
  <label for="year-select">Year</label>
  <select id="year-select"></select>
</div>
<div id="year-plot" class="plot bar-plot"></div>

<h2>Country: net_pipe_bcm over time, coloured by basis</h2>
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

// ---- Legend ----
const legendNote = document.getElementById("legend-note");
legendNote.innerHTML = Object.entries(DATA.basis_color).map(([basis, color]) =>
  '<span><span class="swatch" style="background:' + color + '"></span>' + basis + '</span>'
).join("");

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
  const values = years.map(y => valueAt(iso2, y, "net_pipe_bcm"));
  const bases = years.map(y => valueAt(iso2, y, "basis"));
  const colors = bases.map(b => DATA.basis_color[b] || "#cccccc");
  const hoverText = years.map((y, i) => {
    const v = values[i] === null ? "null (undecided)" : values[i].toFixed(2) + " bcm";
    return countryLabel(iso2) + "<br>Year: " + y + "<br>net_pipe_bcm: " + v +
      "<br>basis: " + (bases[i] || "n/a");
  });

  const trace = {
    name: "net_pipe_bcm",
    x: years,
    y: values,
    mode: "lines+markers",
    connectgaps: false,
    line: { color: "#bbbbbb", width: 1 },
    marker: { color: colors, size: 6 },
    text: hoverText,
    hovertemplate: "%{text}<extra></extra>",
  };

  Plotly.react("country-plot", [trace], {
    margin: { l: 60, r: 20, t: 10, b: 40 },
    xaxis: { title: "Year", range: [2008, years[years.length - 1]] },
    yaxis: { title: "net_pipe_bcm", zeroline: true },
    showlegend: false,
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
      value: valueAt(c.country_iso2, year, "net_pipe_bcm"),
      basis: valueAt(c.country_iso2, year, "basis"),
    }))
    .filter(r => r.value !== null);
}

function renderYearPlot(year) {
  const all = countryRowsForYear(year);
  const undecidedCount = DATA.countries.length - all.length;

  const sorted = all.slice().sort((a, b) => a.value - b.value);
  const importers = sorted.slice(0, TOP_N); // most negative net (net importer)
  const exporters = sorted.slice(-TOP_N).filter(r => !importers.includes(r));
  const rows = importers.concat(exporters).sort((a, b) => a.value - b.value);

  const colors = rows.map(r => DATA.basis_color[r.basis] || "#cccccc");
  const hoverText = rows.map(r =>
    r.label + "<br>Year: " + year + "<br>net_pipe_bcm: " + r.value.toFixed(2) +
    "<br>basis: " + r.basis
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
      text: "Top " + TOP_N + " net importers and top " + TOP_N + " net exporters, " + year +
        " (" + rows.length + " of " + all.length + " countries with a non-null value shown; " +
        undecidedCount + " undecided/null that year)",
      font: { size: 12 },
    },
    xaxis: { title: "net_pipe_bcm (exports minus imports)", zeroline: true },
    yaxis: { automargin: true, tickfont: { size: 9 } },
    height: Math.max(500, rows.length * 22),
  }, { responsive: true });
}

yearSelect.addEventListener("change", () => renderYearPlot(parseInt(yearSelect.value, 10)));
if (DATA.years.length) {
  const defaultYear = DATA.years.includes(2030) ? 2030 : DATA.years[DATA.years.length - 1];
  yearSelect.value = defaultYear;
  renderYearPlot(defaultYear);
}
</script>
</body>
</html>
"""
