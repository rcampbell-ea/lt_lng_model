# Long Term LNG Flows Forecast: Build Plan

Version 1.5, drafted 2026-08-21. Planning document. No pipeline code is written in this session.

Changes from v1.4:
- Appendix B added: unit conversion and reference conditions, treated as a standing data integrity risk. EA's volume basis is assumed to be undocumented, so the appendix sets out how to identify it from data we already hold rather than from metadata.

Changes from v1.3:
- Sections 3.4 to 3.6 added. The IEA Gas Trade Flows file supplies the European pipeline baseline, which v1.2 listed as the largest unsourced input. Its border point basis also settles the physical versus beneficial origin question in 5.4.
- IGU World LNG Report 2026 recorded as a regional cross check, and its 4.91 Mt of 2025 re-exports as a magnitude check on the reload netting.
- Eurostat confirmed reachable and usable through its public API, on a declared origin basis, so complementary to IEA rather than duplicative. APEC EGEDA confirmed to have no API and to be a balance database rather than a trade matrix.
- Pseudo codes XL and XN added for the two non-country values in the GTF country columns.

Changes from v1.2:
- Appendix A added: the environment specification, including verified package compatibility facts and the setup runbook. The build itself happens in a local Claude Code session against the PyCharm interpreter, so the appendix specifies what that session creates rather than shipping it.
- Build location and tooling decisions recorded: separate project from `upstream`, DuckDB enforcing keys, Shooju reached via the upstream MCP server through a launcher.
- Session 0 added to the build sequence.

Changes from v1.1:
- Pipeline gas is now a modelled stage, not an inherited assumption. Section 5 is new and sits ahead of the LNG allocation in the build order, per the pipeline first sequential decision.
- Baseline is put on a net of reloads basis, with the netting rule specified.
- Horizon fixed at 2025 to 2050. Retired liquefaction excluded.
- Map view dropped from the deliverable, which reduces the role of the ArcGIS layer to an optional cross check.
- Remaining geography questions deferred, listed in 4.9 so they are not lost.

## 1. Objective

Produce an annual, country-to-country LNG flow matrix for 2025 to 2050, consistent with the EA Long Term gas supply and demand forecast.

Sequencing, now fixed: build a bilateral pipeline gas view first, derive each country's residual LNG call from its gas balance, then allocate that call across supplier countries. Pipeline is not a side calculation. In the later years of the horizon it is the main determinant of how much LNG a country needs at all, so it has to be settled before the LNG matrix is allocated.

Phase 1 deliverable: a self contained HTML view (Plotly) of the matrices and the diagnostics, so the numbers can be reviewed before any write back to Shooju.

## 2. Decisions register

| Decision | Choice |
|---|---|
| Horizon | 2025 to 2050, annual |
| Granularity | Country to country, with region rollup as a view |
| Sequencing | Pipeline first, sequential. Pipe matrix, then derived LNG call, then LNG allocation |
| LNG allocation | Contract first hybrid: contracts, then netback, then bounded RAS |
| Import basis | Net of reloads and re-exports. Not net of a country's own liquefaction exports, see 5.5 |
| Baseline flows | EA bilateral flow data plus ship tracking, via the client API |
| Seed netting | Reloads netted pro rata across each country's inbound corridors |
| Units | bcm. Mt to bcm factor 1.37 from the contracts workbook cover row |
| Geographic key | ISO 3166-1 alpha-2 |
| Geographic attributes | Natural Earth Admin 0, public domain. ArcGIS layer optional cross check only |
| Sub-country detail | Coastal basin sub-nodes for US, Canada, Russia, Australia. Confirmed as the eventual design. Deferred past v0: country-level nodes first, splits added only if a country-level baseline shows the aggregation actually hides something material. See 4.3c and section 11 |
| Materiality threshold | Full node/port/route detail is built only for the top 25 net-long and top 25 net-short jurisdictions by EA LT gas balance (~90%+ of each pool); everything else rolls into a per-side `other` node. Never a filter on data coverage. See 4.3c |
| Prototype phasing | v0 runs country-level throughout: no node splits, no `dim_port`, no `fact_route_distance`. Node/port/route precision is added after v0 output shows where it's needed, not before |
| Europe aggregate | Candidate demand-block node for the freight/allocation layer, membership undecided (EU27, EU27+UK, or +Balkans, with Turkey possibly held out as a transit hub rather than folded in). Open for sign-off, not built until the allocation layer needs it |
| Freight distance | Maritime network primary, great circle plus canal multiplier fallback, method flagged |
| Region taxonomy | Derived empirically from the region values on the LT demand series, mappings 314 and 550 to 560, and tested to be a partition. Not taken from the API `region` field wholesale, which mixes geographic, OECD, OPEC and Suez schemes in one field and is not standardised. All other EA groupings become tags, not columns |
| Retired capacity | Excluded. Assumed irrelevant to 2025 to 2050 |
| Scenarios | One central case. Scenario switches built in but unused in phase 1 |
| Prices | LT hub price forecasts from the API, so netback is economic not distance only |
| Status weights | No canonical EA source. Set as documented house assumptions in config |
| Deliverable | Plotly HTML, files only. No map. No Shooju write back in phase 1 |
| Mapping 545 status | EA's incumbent "Long term LNG imports and exports" forecast, being replaced by this project. Benchmark only for the 5.6 divergence diagnostic while it remains incumbent; never an input, never ground truth to reconcile toward. See 5.2 |
| Write-back target | The model's output is designed to reduce to mapping 545's exact 103-series grain (52 `net_exports` + 51 `net_imports`, dual role handled per 5.7) so it can eventually replace those series in Shooju under the same or an agreed convention. Regional aggregates (e.g. mapping 545's "North West Europe" row) are not stable in EA's metadata and are out of scope for now. See 10 |
| Geo master scope | Inside the LT LNG repo, extractable later |
| Build location | Local Claude Code session against the PyCharm conda environment. Cowork used for design, review and diagnostics |
| Project location | `C:\Users\robert.campbell\PycharmProjects\lt_lng_flows`, separate from `upstream`, its own git repo and conda env |
| Storage and joins | DuckDB over parquet, with PRIMARY KEY and FOREIGN KEY declared, so a bad key raises at insert rather than joining to NULL |
| Shooju access | Upstream's existing MCP server, reached through a launcher that restores its working directory. Credentials stay in the upstream `.env` on the local machine |
| Environment | Conda, conda-forge only, python 3.12. Specification in Appendix A |
| Pipe baseline, Europe | IEA Gas Trade Flows, border point level, physical directional crossings. See 3.4 |
| Pipe baseline, rest of world | Not sourced. No historical base in GTF for Asian or American pipe. Gap to be stated, see 3.4 |
| Beneficial origin cross check | Eurostat `nrg_ti_gas`, public API, declared origin basis. See 3.6 |
| Region rollup cross check | IGU World LNG Report 2026 regional trade matrix, third party, see 3.5 |
| APEC EGEDA | No API. Manual download only if wanted, and it is a balance database not a trade matrix |
| Unit conversion | Reference conditions treated as unknown until identified empirically, not assumed from documentation. See Appendix B |

## 3. Data inventory

### 3.1 Provided in the project, refreshed monthly

`202608_LNG_contracts_database.xlsx`, sheet `Global LNG Contract Database`, header row 3, 1074 contract rows, 27 columns. Distribution that matters for method design:

- Status: Current 512, Future 356, Expired 206
- Delivery type: DES 525, FOB 474, DES/FOB 48, dash 26, Undeclared 1
- Destination flexibility: Flexible 527, Fixed 521, dash 26
- Agreement Type: SPA 1009, HOA 37, MOU 25, other 3
- Export country: 31 values, of which `Portfolio` is 204 rows
- Import country: 61 values, of which `Multiple` is 305 rows

`202608_LNG_liquefaction_projects.xlsx`, sheet `Global Liquefaction Database`, header row 4, 617 project or train rows, 39 countries, start years 1964 to 2036. Status: Active 221, Planned 168, Cancelled 110, Under Construction 59, Postponed 19, Advanced Development 19, Retired 18, Commissioning 2, Probable 1.

`202608_LNG_regas_projects.xlsx`, sheet `Global Regas Database`, header row 4, 615 rows, 78 countries. Status: Active 285, Planned 124, Cancelled 92, Under Construction 42, Advanced Development 30, Postponed 21, Retired 16, Commissioning 5.

Both project workbooks carry an `ISO 2-letter code` column, so the geo master has a native key to join on. That column is still validated rather than trusted.

All three sheets report a max row of roughly 3500 because of trailing formatting. Ingestion trims on all null rows rather than trusting the sheet dimension.

These files are the monthly source of truth for capacity and contracts and are not fully replicated on Shooju, so they are pinned by vintage like any other input. Ingestion reads `data/raw/workbooks/YYYYMM/`, parses the vintage from the filename prefix, hashes each file into the run manifest, and produces a month on month diff report: new projects, status changes, capacity revisions, contracts added, amended or expired. That diff is worth reading in its own right, since a status change from Planned to Under Construction moves the forecast.

Source location for the monthly refresh is not yet decided. Design against the versioned local raw folder and settle the source later.

### 3.2 From the EA client API and Shooju

To be catalogued in session 1, with series identifiers documented as they are confirmed:

1. LT gas balance by country, annual, to 2050: demand, domestic production, pipeline imports, pipeline exports, LNG imports, storage movements, own use and losses. Exact component definitions matter as much as the values, see 5.2.
2. LT pipeline trade. Whether the dataset carries country pair detail, country level net only, or region level only is unknown and is part of session 1 discovery. The answer determines how much of section 5 is ingestion and how much is modelling.
3. Historical bilateral LNG flows.
4. Ship tracking data. Two uses beyond the baseline: identifying reload and transhipment cargoes for the net basis conversion, and calibrating the destination choice model in the LNG allocation on observed diversion behaviour rather than on assumption.
5. LT hub price forecasts, for the netback.

Access: the org registry has a `Shooju` connector and an `energyaspects dev` connector. Neither is enabled in this chat, so neither is usable until toggled on in the chat's connector settings. The API reference at developer.energyaspects.com is closed to automated fetching by URL, but its individual doc pages can be pasted in directly, and were: see 3.2b for the endpoint map that came out of that.

### 3.2b EA Data Service REST API: endpoint map and the workflow that avoids re-discovery

Base URL `https://api.energyaspects.com/data`. Auth is `api_key` as a query
parameter on every call, read from `MY_EA_API_KEY` in `.env` (A.5). This is a
plain REST API, distinct from Shooju and reachable without the MCP connector,
discovered empirically because the reference site rejects automated crawling
but not a pasted page. Four endpoints matter, and three of them look like they
should return data and do not:

| Endpoint | Returns | Use it for |
|---|---|---|
| `GET /datasets/timeseries/pagination?mapping_id=` | Metadata only, one row per `dataset_id`: `description`, `country`, `country_iso`, `region`, `aspect`, `category`, `category_subtype`, `unit`, `frequency`, `lifecycle_stage`, `licensed` | Scoping a mapping before pulling anything: which rows are real countries (`country_iso` populated) versus region or world aggregates (blank), what units and categories are mixed in under one `mapping_id` |
| `GET /datasets/timeseries/{dataset_id}` | Metadata for one dataset, plus its `release_dates` history | Checking a single series' revision history. Not a bulk tool |
| `GET /metadata/timeseries` | The full enum of valid values for every metadata field (`category`, `aspect`, `region`, ...) | Confirming a filter value is spelled the way the API expects, before using it on `/timeseries/` |
| `GET /timeseries/?mapping_id=&category=&aspect=&geography=&date_from=&date_to=` | Metadata **and** a `data` object of `{date: value}` per matching dataset | The only endpoint that returns actual figures. Everything above is reconnaissance for this one |

**The mistake this corrects.** A `mapping_id` is a bucket, not a clean
concept: mapping 314, `Long term total demand`, holds 953 series covering
`oil_products`, `NGLs`, `liquids` and `natural_gas` together, all under one
name, and 15% of its rows are region or world aggregates sitting alongside
the country rows with no country populated. Querying it by natural language
(the EA MCP's `get_timeseries_data`, semantic search) or by pulling every
`dataset_id` in the mapping blind returns a mixture of countries and
aggregates, and of gas and non-gas series, with no reliable way to separate
them after the fact. The fix is always the same order: **call the pagination
endpoint first**, filter its metadata (`country_iso` non-blank, `category =
natural_gas`, whatever the question needs) to get the exact `dataset_id`s or
metadata filter values wanted, **then** call `/timeseries/` with those exact
filters plus a date range. Metadata reconnaissance before the data pull, not
instead of it and not skipped.

Worked example, this is exactly how
`crosswalks/gas_balance_materiality_2026.csv` was built: `GET
/datasets/timeseries/pagination?mapping_id=297` and `...?mapping_id=314`
established that supply (297) is already all-gas and mostly country rows,
while demand (314) needed an explicit `category=natural_gas` filter to strip
out the oil products and NGLs series bundled into the same mapping. Then `GET
/timeseries/?mapping_id=297&date_from=2026-01-01&date_to=2026-12-31` and the
same for 314 with `category=natural_gas` added returned the actual bcm
figures used to rank countries. See 4.3c for what the ranking was for.

### 3.2c OilX cargo tracking API: the source for 3.2 items 3 and 4

A separate API from 3.2b, different base URL, same `api_key` auth pattern.
Base `https://api.energyaspects.com/oilx/v2/`. This is what answers 3.2 item
3 (historical bilateral LNG flows) and item 4 (ship tracking, for reload and
STS detection).

| Endpoint | Returns | Use it for |
|---|---|---|
| `GET/POST /cargotracking/flows/lng` | Pre-aggregated flow rows: `OriginCountryCode`, `DestinationCountryCode`, `GradeID`, `Import` (date basis flag), `QuantityKT`/`QuantityCBM`/`QuantityMMBtu`, `ReferenceDate`, `Deleted` | The Layer 0 seed matrix (7). Confirmed working: `range=YYYY-01-01,YYYY-12-31`, `grade_level=false` to collapse LNG grades to one row per country pair per date, one consistent `import` filter value to avoid double counting the same physical flow under both its export- and import-dated rows |
| `GET /cargotracking/lng` | Vessel-level voyage rows: `IMO`, `VoyageID`, `LoadCountryCode`/`LoadPortID`/`LoadDate`, `DischargeCountryCode`/`DischargePortID`/`DischargeDate`, `load_sts`/`discharge_sts` (`include`/`exclude`/`only`), `Deleted` | Reload and transhipment detection for the net-basis conversion in Layer 0, and calibrating the netback softmax temperature on observed diversion behaviour (7, Layer 3) |
| `GET /metadata/cargotracking/cargotypes` | `ID → Name`, `Taxonomy` (`CargoType`/`CargoSubType`) | Resolving `GradeID`/`CargoTypeID`. LNG itself is `CargoType` 211100, rich/lean grades are `CargoSubType`s under it |
| `GET /metadata/geoassets` | `ID → Name, Type` (Port, Refinery, Shipyard, Dock, ...) | Resolving `LoadPortID`/`DischargePortID`. No coordinates — does not close gate B, but is EA's own port-name vocabulary (from cargo tracking, not project workbook plant names), a better exact-match source than what session 2 used if gate B is ever reopened |
| `GET /metadata/cargotracking/areas` | Shipping-area `ID → Name`, `SuezPosition` (East/West), and a `Countries → Ports` list per area | A ready-made input for the `suez_open`/`suez_closed_cape` routing scenarios in 4.7, if and when route-level work resumes |
| `GET /metadata/cargotracking/countryports` | `Country → Ports`, with sub-country splits for `US` (PADD-based, 7 rows), `CA` (13 provinces), `CN`, `CL` only | Candidate evidence for gate E's US/Canada halves only — confirmed the same US/CA/CN/CL-only coverage already recorded in `session_01_data_availability.md` question 7. No coverage for Russia or Australia, and PADD/province granularity still needs a reviewed crosswalk onto `us_gulf`/`us_east`/etc., not a direct mapping (Alaska in particular isn't its own PADD). Deferred along with the rest of gate E per the Prototype phasing decision |
| `GET /metadata/cargotracking/vessels` | `IMO → Name, Class, Type, YearBuilt` | Resolving `IMO` on `/cargotracking/lng` rows; vessel class is a secondary candidate input for the freight/charter-rate assumptions in section 7 |

`/metadata/cargotracking/grades` (crude oil API gravity/sulphur) and
`/metadata/companies` exist but are out of scope: the former is crude
quality, not LNG; the latter resolves buyer/supplier/charterer company IDs on
`/cargotracking/lng`, not needed unless a future session analyses cargo
counterparties.

GET is the default choice for both cargo-tracking calls: it matches every
other pull script's request-building style in this project, and this
project's pulls are broad snapshots (a date range, at most a few filters),
not narrow enough to need enumerating long ID lists that would risk hitting
a URL length limit. POST exists on `/cargotracking/flows/lng` for the case
that changes.

### 3.3 Not yet sourced

1. Pipeline interconnector capacity by country pair, with commissioning years, reverse flow capability and availability. Does EA maintain a pipeline equivalent of the liquefaction workbook? If not, this has to be assembled, and it is the largest new data task in v1.2.
2. Long term pipeline supply contracts and take or pay terms, where known.
3. Freight cost assumptions: charter rate and fuel price path, to convert distance into a freight cost for the netback. Whether these exist in the LT dataset is a session 1 question.
4. Retirement or plant life assumptions for liquefaction trains that reach end of life inside the horizon, see open question 6.

### 3.4 IEA Gas Trade Flows, `Export_GTF_IEA_202606.xlsx`

Added to the project 2026-08-21. This is the most important new input in v1.4, because it is the pipeline baseline the plan had listed as unsourced.

Shape: sheet `GTF_data`, 267 rows, one per directional border point. Columns: Borderpoint, Exit, Entry, MAXFLOW (Mm3/h), then 213 monthly columns from Oct-08 to Jun-26. Units are million cubic metres, gas measured at 15 degrees Celsius and 760 mm Hg. A `NOTES` sheet carries revision history and per country caveats and must be read as part of ingestion, not skipped.

Content: 233 pipeline border point rows and 34 LNG terminal rows. Directional pairs appear twice where the link is bidirectional, for instance Badajoz Spain to Portugal and Portugal to Spain.

What it does and does not give us:

- **It is physical border flow data, directional, at border point level.** This is exactly the measurement basis the plan chose in 5.4, so that default is now supported by the data rather than only by argument.
- **It does not give bilateral LNG origins.** The 34 LNG rows carry Exit as the literal string `Liquefied Natural Gas`, which is a mode, not a place. So the file gives LNG arrivals by terminal and country, useful for regas utilisation and for the net import basis, but the LNG matrix baseline still needs the EA bilateral flow and ship tracking data.
- **Coverage is Europe plus adjacent suppliers**, 40 exit and 41 entry values including Algeria, Libya, Tunisia, Morocco, Russia, Belarus, Ukraine, Georgia, Iran, Turkiye and Syria. There is no Asian or American pipeline history, so Power of Siberia, Central Asia to China and the Americas have no historical base in this file. For those the pipe view is forecast only, which is a gap to state rather than paper over.

Traps, all from the NOTES sheet, each needing handling in ingestion:

1. **Virtual border points break the time series.** Flows have been reallocated over time into VIP Iberico (from Oct 2012), Virtualys, VIP BENE, VIP-TH and Bras-Petange. A border point level series is therefore not continuous. Aggregate to country pair before any modelling use, and never treat a single border point as a stable series.
2. **Netherlands publication discontinued from January 2019.** A major transit country with an incomplete series for the most recent seven years. This must be flagged in the baseline, not silently averaged.
3. **Norway and the UK report St Fergus differently from January 2014.** Bilateral reporting is asymmetric, so the pipe matrix cannot assume symmetry between a pair.
4. **Country attribution changes inside history.** Ruggel exit flows were remapped from Austria to Liechtenstein following historical revision.
5. **Data not fully collected April to September 2009**, and the March 2026 addition of a `Not Elsewhere Specified` LNG entry into Germany has historical revisions still pending.
6. **Two non-country values in country columns**: `Liquefied Natural Gas` and `Not Elsewhere Specified`. These need pseudo codes, see 4.4.
7. **Name variants for the alias table**: `Republic of Türkiye`, `Iran, Islamic Republic`, `Moldova, Republic`, `Slovak Republic`, `Czech Republic`, `Isle Of Man`, `Liechtenstein`.
8. **Reference conditions.** 15 degrees Celsius and 760 mm Hg is not the only convention in use. Converting to bcm and comparing against the LT dataset requires knowing the LT reference conditions, since the difference between a 15 and a 0 degree basis is material, not rounding. Session 1 question.

### 3.5 IGU World LNG Report 2026

Also in the project. Gives global LNG trade of 437.0 Mt in 2025, up 25.7 Mt, across 24 exporting and 50 importing markets, and a region by region trade matrix for 2025 against 2024 (Table 3.1, sourced to Rystad Energy).

Use it as an **independent cross check on the region rollup** of our matrix, not as the country level baseline: the published matrix is regional, it is a third party estimate rather than EA's own, and the report notes its interregional figures exclude re-exports.

Two numbers from it are directly useful now. Re-export trade of 4.91 Mt in 2025 is a magnitude check on the reload netting in layer 0, and it is small enough to confirm that netting pro rata rather than modelling reloads explicitly is proportionate. North America to Europe at 74.1 Mt in 2025, up from 46.3 Mt, is the largest single corridor change in the matrix and a useful test of whether our netback allocation can reproduce that kind of swing.

### 3.6 Public statistical sources: what is reachable

**Eurostat: yes, directly usable.** Verified live against the dissemination API. `nrg_ti_gas` (annual) and `nrg_ti_gasm` (monthly), imports of natural gas by partner country, dimensions freq, siec, partner, unit, reporting country and time, 167 partner entities, units million cubic metres and terajoules GCV, last updated 24 June 2026. Public REST API, JSON-stat, no key or registration, filterable by dimension and time.

The important caveat is measurement basis, not access. Eurostat partner country imports are on a **declared origin** basis, so a German import series shows large volumes from the Netherlands and Belgium that are transit and re-declaration rather than Dutch or Belgian production. That is a different measurement from the IEA border flow data, and combining the two naively would either double count or contradict. Treat Eurostat as a cross check and as a source for the beneficial origin view described in 5.4, and keep IEA GTF as the physical border basis. Also confirm whether the `siec` dimension separates LNG from pipeline gas before using it for either purpose.

**APEC EGEDA: no, not programmatically.** No documented API. Access is through web query pages, publication downloads and a members only area, and the public pages do not state coverage years or terms of use. Separately, EGEDA is an energy balance database by economy rather than a bilateral trade database, so even with access it would inform the Asia Pacific demand and production side of the gas balance, not the flow matrix. If we want it, the practical route is a manual download of the published annual tables, which you or the local session can do; it is not something to automate against a query form.

## 4. Geographic single source of truth

### 4.1 Purpose and the one rule

One table defines what a country is for this model. Everything else joins to it.

No table in the pipeline may carry a country name string as a key. Names exist only as display attributes and only in the master. Every fact table carries `country_iso2`, and every raw name string from every source resolves to a code through a single reviewed alias table.

This matters more in v1.2 than it did in v1.1, because the pipeline layer adds transit countries, adjacency relationships and a second set of source systems with their own naming conventions.

### 4.2 Sources

1. **ISO 3166-1 alpha-2** is the code authority. The master does not invent codes for real places.
2. **Natural Earth Admin 0 Countries**, 1:50m, is the attribute and geometry backbone. Explicit public domain, carries ISO alpha-2 and alpha-3, continent, region and subregion, and polygon geometry sufficient for centroids, coastline proximity and land adjacency. This is what the model computes against.
3. **ArcGIS Living Atlas World Countries Generalized** is retained as an optional boundary and centroid cross check, pinned as a snapshot. With the map dropped from the deliverable there is no display requirement, so the earlier licence question is largely moot: we are not redistributing Esri geometry. If a map is wanted later the layer is already pinned and Esri attribution is added at that point.

Field schemas are discovered at build time by querying the service and reading the actual field list, not assumed from documentation. The ArcGIS Hub page does not publish its schema, so this is not optional.

### 4.3 Table design

Codes, node identifiers and file names are lower snake case ASCII, no spaces or symbols, so they are safe as Shooju series ID components and as Windows paths. ISO codes are stored uppercase.

`dim_country`. Primary key `country_iso2`.

| Column | Notes |
|---|---|
| country_iso2 | PK, exactly two uppercase A to Z characters |
| country_iso3 | ISO 3166-1 alpha-3 |
| country_name_display | Human readable |
| country_name_slug | lower snake case ASCII, for identifiers and file names |
| is_real_country | False for the pseudo codes in 4.4 |
| continent, un_subregion | From Natural Earth |
| lt_region | Canonical region, derived from the LT demand series per 4.3b. Null until the LT demand series pull (mappings 314, 550-560) lands; session 3 built the derivation and partition test but ran before that pull, so it stays null pending it |
| is_landlocked | Hard error if a landlocked country appears as an LNG exporter or importer |
| role_lng | importer, exporter, both, or none. Drives which axis a country appears on |
| role_pipe | importer, exporter, transit, both, or none |
| centroid_lat, centroid_lon | Pole of inaccessibility, so the point sits inside the polygon |
| geo_source, geo_snapshot_date, geo_snapshot_sha256 | Lineage |

### 4.3b Regions are derived and tested, and EA's other groupings are tags

`lt_region` is not read from a static source and is not read from the API
`region` field wholesale. That field mixes four incompatible schemes in one
column: geography (AFR, AP, AMERICAS, EUR, FSU, LATAM, ME, NA), OECD membership,
OPEC groupings, and Suez position, plus WORLD. Qatar is simultaneously ME,
NON_OECD, OPEC, OPEC_PLUS and EAST_OF_SUEZ, so the field is a tag vocabulary and
cannot be a single-valued canonical column. `sub_region` has the same problem
across its 73 values, which include PADDs, US power markets, shale basins,
refining hubs, Chinese provinces and `Minor_*` residual buckets.

**Derivation.** Take the distinct `(country_iso, region)` pairs appearing on the
series in the LT demand mappings: 314 `Long term total demand` and the eleven
sector mappings 550 to 560. That set is the taxonomy, because it is what EA's own
published series are grouped on, and therefore what the derived LNG call in 5.6
has to be compared against.

**Test, do not trust.** Every real country appears exactly once, and every
country with `role_lng` or `role_pipe` other than `none` appears at all. If the
set is a partition it becomes `lt_region`. If it is not, the build stops and
lists the offenders. Nothing is resolved by picking a winner.

**Open decision.** A country may carry a geographic region on one sector's series
and an OECD or OPEC value on another's. The proposed rule is to keep only the
geographic subset and route the rest to tags, but this is a judgement about EA's
data and is for sign off rather than a code default. Until it is signed off, a
multi-valued country is reported, not resolved.

**Everything else becomes a tag.** `dim_country_region_tag`, key
`(country_iso2, scheme, tag_value)`, many to many. `scheme` takes
`ea_api_region`, `ea_api_sub_region`, `ea_workbook_region`, `ea_supply_area`,
`ea_demand_area`, `padd`, `oecd`, `opec`, `suez`. Every EA grouping stays
available for filtering and for reconciling to an EA aggregate series, with no
pretence that any of them is the hierarchy. A rollup declares its scheme, and a
scheme may only be used for a rollup if it passes the partition test above.

**Provenance.** `lt_region` is a derived artefact, so the manifest records which
mappings it came from, the vintage, and the partition test result. If EA
reorganises its regions between vintages, the vintage diff surfaces it rather
than silently moving countries between rollups.

`geo_country_geometry`. GeoParquet keyed on `country_iso2`, holding model geometry. Kept out of the dimension table so that stays small and diffable.

`dim_country_adjacency`. New in v1.2. Key (`country_iso2_a`, `country_iso2_b`), derived from the geometry as shared land border, plus a manual override file for cases geometry gets wrong or where a border exists but no pipeline crossing does. This is the skeleton the pipeline network is built on: a pipe flow between two countries with no shared border and no named subsea link is a data error.

`dim_supply_node`, `dim_demand_node`. Primary key `node_id`, foreign key `country_iso2`. The freight level of the LNG model; country stays the reporting level. Confirmed splits:

| Country | Nodes |
|---|---|
| US | us_gulf, us_east, us_west, us_alaska |
| Canada | ca_east, ca_west |
| Russia | ru_yamal, ru_baltic, ru_sakhalin, ru_arctic_other |
| Australia | au_west, au_north, au_east |
| All others | one node, `node_id` equal to the country slug |

Node to country aggregation must be exact, and is tested. v0 populates `node_id` equal to the country slug for every country, including the four split ones; the table above is the target design, applied once justified by a country-level v0 baseline. See the Prototype phasing decision in section 2.

`dim_port`. Representative load and discharge port per node, with coordinates. Roughly 40 load ports and 60 to 80 discharge ports, curated as a reviewed CSV. A list that size is more reliable than geocoding 1,232 project rows, and can be extended to terminal level later without schema change.

`fact_route_distance`. Key (`origin_node`, `destination_node`, `routing_scenario`). Columns: distance_nm, transit_days, method (`network` or `great_circle_multiplier`), canal_used, computed_at, code_version. Precomputed and cached, never calculated inside an allocation loop.

`xwalk_country_alias`. Key (`source_system`, `raw_value`) mapping to `country_iso2`. `source_system` distinguishes the three workbooks, the LT dataset, the bilateral flow source, the ship tracking source and the pipeline capacity source, because the same raw string can mean different things in different systems. Many to one only. Any raw value not present raises an error and names the offender. Nothing is dropped silently.

`xwalk_project_node`. Maps liquefaction and regas project rows to `node_id`. Only needed for the four split countries, so a short file. Proposed assignments plus confidence flags, then signed off.

### 4.3c Materiality threshold for node, port and route detail

Not every jurisdiction needs full node, port and route-distance resolution.
Building precise geometry, a curated port and a maritime route for a country
that moves a few tenths of a bcm a year buys nothing the model can use, and
each one added multiplies the review burden on gates B and E in
`sessions_02_03_build_plan.md`. This threshold decides which jurisdictions get
that detail. It is a precision decision, not a coverage one: nothing below the
threshold is dropped from `dim_country`, from the alias crosswalk, or from any
workbook-derived fact table, only from bespoke port and geometry work.

**Method.** Rank countries by net gas position, `supply − demand`, from EA's
LT gas supply (mapping 297) and LT total demand filtered to `category =
natural_gas` (mapping 314; that mapping also carries oil products, NGLs and
liquids demand for the same countries, which are out of scope here). Both
queried at the country level from the live `/timeseries/` endpoint
(`country_iso` populated; region and world aggregate rows excluded). This
position is a whole-of-market number: it nets pipe trade and LNG trade
together, so a pure pipeline country can rank as material with `role_lng =
none` (Turkmenistan, Uzbekistan and Azerbaijan do, on the export side;
Hungary, Czechia and Austria do, on the import side). That is expected, not a
defect: this threshold governs the freight and node layer that the whole gas
balance in section 5 feeds, not LNG exposure on its own.

**Threshold, as run.** On the 2026 vintage of the pinned snapshot: 52
countries net-long, 55 net-short. The top 25 net-long covered 96.3% of the
total net-long pool; the top 25 net-short covered 93.1% of the total
net-short pool. Checked on one forecast year, not across the full 2025 to
2050 horizon, and accepted at that: the model does not need per-year
reconfirmation of which countries are material to be useful, and re-running
this exercise every session defeats the point of writing it down. The full
ranked list, with each country's tier, is
`crosswalks/gas_balance_materiality_2026.csv`, provenance in the manifest
alongside it.

**Rule.** A country in the combined top-25-long/top-25-short set, or one that
carries a `role_lng` or `role_pipe` other than `none` from the workbooks or
GTF (so a real, if small, regas terminal, liquefaction project or pipe
corridor is never excluded for being immaterial), gets its own
`dim_supply_node`/`dim_demand_node`, is in scope for `dim_port` curation, and
needs `fact_route_distance` computed. Everything else rolls into a per-side
`other` node for freight and allocation purposes.

**Absence is a stronger signal than materiality.** A jurisdiction with no EA
LT supply or demand series at all, checked directly against mappings 297 and
314 rather than inferred from a workbook role, needs no LNG or pipe modelling
regardless of what a project workbook says about it. This is how Gibraltar
(a real regas importer per the workbook, but absent from both LT series) and
Kosovo (no LNG or pipe role in any source) closed as out of scope rather than
staying open pending a boundary-source pull or an invented classification.
See `sessions_02_03_build_plan.md` section 0, gates C and D.

### 4.4 Pseudo codes for non geographic pools

`Portfolio` and `Multiple` are not countries and never enter `dim_country` as real ones, but they cannot be dropped either, being 204 and 305 contract rows. They take codes from the ISO 3166-1 user assigned range, which exists precisely so private schemes do not collide with future real assignments.

| Code | Meaning | is_real_country |
|---|---|---|
| XP | Portfolio seller pool, origin unspecified | False |
| XM | Multiple or unspecified destination | False |
| XR | Reload or transhipment origin, if modelled explicitly | False |
| XL | The literal `Liquefied Natural Gas` value in the IEA GTF Exit and Entry columns. A mode, not a place | False |
| XN | `Not Elsewhere Specified`, as used in IEA GTF | False |
| ZZ | Unknown. Error trapping only. A ZZ in any output is a bug |

Avoid XK, which is already used de facto for Kosovo.

LT dataset aggregates such as EU, Other Europe or World are not countries either. They live in `dim_aggregate` with an explicit member list, and the model reconciles to country series rather than to aggregates.

### 4.5 Known ISO2 traps, each with a test

1. Natural Earth writes `ISO_A2` as -99 for several entities, and in some vintages that has included France and Norway alongside the expected Kosovo, Northern Cyprus and Somaliland. Use `ISO_A2_EH` where present and patch the remainder from the ISO list. A silent -99 is a silently dropped country.
2. EA name variants: UK maps to GB; South Korea to KR; Turkey and Turkiye both to TR; UAE to AE; Trinidad and Tobago to TT; Myanmar and Burma both to MM.
3. Congo. CD and CG are different countries with similar names. Fuzzy matching here is a real error.
4. Territories that are not their parent state: Curacao is CW, Puerto Rico is PR, Gibraltar is GI. Whether the LT dataset separates them or folds them into the parent changes how the balance reconciles.
5. Taiwan is TW regardless of how third party layers label it.
6. The `ISO 2-letter code` already in the two project workbooks is validated against the master. Where the workbook code and the alias resolution of the country name disagree, that is a data quality flag to report, not something to silently resolve in favour of either side.

### 4.6 Snapshot pinning and versioning

Public geographic layers change without notice, and a boundary or field rename appearing mid project would move forecast numbers with no visible cause.

- Pull each source once into `data/geo/raw/`, recording source URL, query parameters, retrieval timestamp and payload sha256 in a manifest.
- The model reads only the pinned snapshot. No live service calls at runtime, so the pipeline is reproducible and runs offline.
- Refreshing is an explicit versioned act: bump `geo_master_version`, regenerate, diff country list, centroids, adjacency and node assignments against the previous version, review the diff.
- Alias and node crosswalks are CSV in the repo, so their history is reviewable in ordinary diffs.

### 4.7 Distance calculation

- Primary: maritime network route between representative ports, using a public sea route network such as the `searoute` package built on MarNet, so distances follow shipping lanes and canal transits rather than crossing land.
- Fallback: haversine between ports plus a fixed multiplier by routing case, used only where the network fails to resolve a lane.
- Every row carries its method, so a validation summary can report the share of corridors, volume weighted, resting on the fallback. A material share is a thing to fix, not to accept.
- Routing scenarios are first class even though phase 1 runs one central case: `panama_open`, `panama_constrained`, `suez_open`, `suez_closed_cape`.

### 4.8 Validation of the geo master

Run before any modelling code:

1. `country_iso2` unique, two uppercase letters, every real code present in ISO 3166-1.
2. Every raw name string in every source resolves through `xwalk_country_alias`. Unresolved values fail the build and are listed.
3. Alias table many to one within each source system. A raw value mapping to two codes fails.
4. Every real country has geometry, and its stored point falls inside its own polygon.
5. Node to country aggregation reproduces country totals exactly, for capacity and for flows.
6. Every node has a port with a valid coordinate within a set distance of the coastline.
7. `fact_route_distance` has no nulls for any corridor the model uses, all distances positive, symmetric routings agree both ways.
8. No landlocked country appears as an LNG exporter or importer.
9. Adjacency is symmetric, and every modelled pipe corridor has either adjacency or an explicit named subsea link.
10. No `ZZ` anywhere in any output.
11. Snapshot hashes match the manifest. A changed source without a version bump fails the build.

### 4.9 Deferred geography questions

Parked at your request, recorded so they are not lost. None blocks session 2.

1. Whether EA maintains an internal country master we should conform to rather than build alongside.
2. Whether any exporter beyond the four confirmed splits needs sub-nodes.
3. Terminal level coordinates, if freight precision later proves insufficient at port level.
4. Whether the geo master is eventually extracted as shared EA reference data.

## 5. Country gas balance and the pipeline layer

New in v1.2, and the stage that now sits between the LT data and the LNG allocation.

### 5.1 Why it comes first

A country's LNG requirement is a residual: what demand is left after domestic production and pipeline supply. Out to 2030 the pipeline picture is largely known infrastructure and existing contracts. From the mid 2030s it is not, and a single project decision moves the LNG call by tens of bcm. Power of Siberia 2, Central Asia to China line D, TANAP and TAP expansion, TAPI, East Med, Nigeria to Morocco, Argentina into Brazil and Chile, and any restoration of Russian pipe into Europe are each large enough to change which LNG projects are needed at all. Inheriting a pipeline view implicitly means those judgements are buried. Making it a stage means they are written down, in one config file, and can be argued with.

Central case is a single view, per your decision. But it is an explicit view.

### 5.2 The balance identity

Per country, per year, in bcm, with sign conventions fixed in code:

```
net_lng_imports = gas_demand
                + pipe_exports
                + own_use_and_losses
                + net_storage_injection
                - domestic_production
                - pipe_imports
```

Two things must be pinned down in session 1 before this is implemented, because getting either wrong biases every derived LNG call in the same direction:

1. **Component definitions.** Is LT demand gross inland consumption or final consumption? Are own use, flaring and shrinkage inside demand or separate? Is production marketed or gross? Annual storage should net close to zero but may not in a build or draw year.
2. **Whether the LT dataset already publishes LNG imports by country.** It almost certainly does. That series is then not an input but a benchmark, and the divergence between it and our derived call is the single most important diagnostic in the model. See 5.6.

**This series is mapping 545, "Long term LNG imports and exports," already pulled and pinned (`data/raw/ea_api/202608/mapping_545/`, 103 records, confirmed live).** It is EA's own existing LNG forecast, being replaced by this project: this model's eventual deliverable is expected to supersede it, via the Shooju write-back named in 11.12 and the decisions register. It is a benchmark for the divergence diagnostic in 5.6 for as long as it remains the incumbent, never an input the derived call is built from or conformed to, and never ground truth to reconcile toward. A future session updating this series (or the write-back replacing it) does not change 5.6's method, only which forecast the divergence is measured against.

### 5.3 Pipeline data model

- `dim_pipe_route`. Key (`origin_iso2`, `destination_iso2`). Attributes: route_name, is_subsea, transit_countries, reverse_flow_capable, FK to adjacency.
- `fact_pipe_capacity`. Key (`origin_iso2`, `destination_iso2`, `year`). Technical capacity bcma, availability factor, commissioning year, status, source.
- `fact_pipe_contract`. Long term supply and take or pay commitments where known, expanded annually like LNG contracts.
- `fact_pipe_flow_hist`. Historical bilateral border flows.
- `fact_pipe_flow_forecast`. The output, with provenance per cell.
- `config/pipeline_projects.yaml`. Every prospective project in the central case: assumed commissioning year, capacity, ramp, availability, and a source note per line. This file is the pipeline view, in one reviewable place.

### 5.4 Physical border flows, not beneficial origin

The design point that separates pipeline modelling from LNG modelling: pipe gas crosses transit countries. Ukraine, Turkey, Belarus, Slovakia, Austria, Germany and Morocco all move gas that is neither theirs nor destined for them.

Default: model **physical border flows** between adjacent countries. That is what the gas balance identity needs, since a transit country's pipe imports and pipe exports both rise and its net position is unchanged. A separate derived view attributes flows back to originating producer, for reporting and for the netback comparison against LNG. Both are produced; the balance uses the physical one.

The alternative, modelling origin to destination directly, is tempting because it looks like the LNG matrix, but it breaks the balance identity for every transit country and cannot be validated against border flow data.

The IEA GTF file in 3.4 settles this. It is border point level, directional, and measures physical crossings, so the physical basis is what we can actually validate a forecast against. The beneficial origin view is then derived, and Eurostat `nrg_ti_gas` in 3.6 is the natural cross check on it, being a declared origin series. Two bases, two sources, each used for what it measures. Open question 3 in section 12 is therefore answered unless you disagree.

### 5.5 Method

- **P0 baseline.** Historical bilateral border flows. Seed choice needs regional judgement rather than a blanket rule: a three year average is reasonable for Asia, but for Europe 2021 to 2024 spans a structural break, so the seed there should start from the post 2022 regime, not average across it. Set the regime start year in config per region.
- **P1 capacity envelope.** Technical capacity by pair by year from `fact_pipe_capacity`, with availability factors, reverse flow capability and commissioning ramps from `pipeline_projects.yaml`.
- **P2 producer export capability.** An exporter cannot pipe out more than its production less its own demand less its other exports. This bound comes from the LT dataset and is often tighter than pipe capacity, particularly for Algeria, Iran and Turkmenistan.
- **P3 allocation.** Merit order rather than netback. Pipe gas is low marginal cost and contractually committed, so flow equals the minimum of available capacity, contracted or commercially expected volume, and the importer's remaining need after domestic production. Route choice matters where multiple paths exist, Russia into Europe and Norway's landing points being the obvious cases, and is resolved on capacity and cost of transit.
- **P4 reconciliation.** If the LT dataset publishes country level pipe imports and exports, reconcile the matrix to those margins with the same bounded RAS used for LNG. If it publishes only regional totals, the matrix defines country level pipe trade and the regional totals become the constraint.
- **P5 derive the LNG call.** Apply 5.2 per country per year.

### 5.6 The reconciliation problem this creates, stated plainly

Pipeline first sequential means we derive the LNG call rather than take it. Our derived call will not equal the LT dataset's own LNG import series. That gap is not a nuisance, it is the main output of this stage and needs handling rather than smoothing:

1. **Report it, per country, per year**, in absolute bcm and as a percentage, in the HTML diagnostics. A country where our pipe view differs materially from the LT model's implied one is a conversation with the LT team, not a number to quietly overwrite.
2. **Global closure.** Summed across countries, the derived LNG call will not equal global LNG supply either. A bounded global reconciliation step closes the gap while preserving country ranking, and reports the size of the adjustment. If that adjustment is large, the pipeline view diverges from the house view and should be reviewed before the LNG matrix is trusted.
3. **Negative residuals.** For some countries the identity will imply negative LNG imports. Sometimes that is legitimate, sometimes it is a definitional error in the balance components. The rule: never silently clamp to zero. Flag, list, and require a decision. Silent clamping is how a definitional error becomes an invisible forecast bias.
4. **Tolerance and escalation.** A configured tolerance band per country, with anything outside it raised in the validation report rather than absorbed.

### 5.7 Net of what, precisely

Worth stating because it is an easy place to talk past each other. "Net imports" here means net of reloads and re-exports. It does not mean net of a country's own liquefaction exports.

So a dual role country such as Malaysia, the US, Indonesia or the UAE appears on both axes of the LNG matrix: as a row, with a row total equal to its LNG exports from its liquefaction plants, and as a column, with a column total equal to its own net LNG imports. Bintulu exporting while Peninsular Malaysia imports is two flows, not one net number. Netting across roles would produce negative column totals and break a non negative matrix, so the model does not do it. `role_lng` in `dim_country` carries this.

Confirmation welcome, since this reading determines the shape of the matrix.

## 6. LNG data model, keys and joins

Star schema on the geo master. Parquet intermediates, explicit keys. Project instruction stands: no plaintext or fuzzy joins without approval.

- `dim_liq_project`. PK `liq_project_id`, a surrogate of country_iso2 plus normalised project slug plus train. FKs `country_iso2`, `node_id`.
- `dim_regas_project`. Same pattern.
- `fact_contract`. One row per contract per year of its life, expanded from Contract Start and Contract End with part year weighting. FKs `exporter_iso2`, `importer_iso2` (possibly XP or XM before allocation), `liq_project_id`.
- `fact_liq_capacity`, `fact_regas_capacity`. Project by year, nameplate bcma with ramp applied.
- `fact_lt_balance`. Country by year, the components in 5.2.
- `fact_lt_price`. Hub by year, with `xwalk_hub_country` mapping hubs to the importers they price.
- `fact_flow_baseline`, `fact_flow_forecast`. exporter_iso2, importer_iso2, origin_node, destination_node, year, bcm, provenance layer.

Remaining join hazard: contracts `Liquefaction project` to liquefaction database `Project`. The contracts file uses composite labels such as `Bintulu LNG (Train 1-9)` and `Texas LNG Brownsville (Train 1-2)`, with embedded newlines, while the liquefaction file is one train per row. This needs a reviewed many to one crosswalk `xwalk_contract_liqproject.csv`, generated once with proposed matches and confidence flags, then signed off. Unmatched contracts fall back to country level supply rather than being guessed.

## 7. LNG method

### Layer 0: baseline, on a net basis

Build the seed matrix from historical bilateral flows, sourced from OilX
`/cargotracking/flows/lng` (base `api.energyaspects.com/oilx/v2/`, confirmed
working: annual country-pair aggregates, `grade_level=false` to collapse LNG
grades, one consistent `import` basis to avoid double counting), averaged
over the last three available years, so a single outage does not become
structure. Then convert gross to net: identify reload and transhipment
volumes from the ship tracking data (`/cargotracking/lng`, vessel-level, via
its `load_sts`/`discharge_sts` filters) and subtract them pro rata across
each country's inbound corridors, in proportion to each corridor's share of
that country's arrivals. Spain's reloads reduce its inbound corridors
proportionally, the matrix reconciles to net imports, and every remaining
corridor still traces to a real cargo origin.

v0 runs this layer at country level throughout (`fact_lng_flow_baseline`,
`origin_iso2`/`destination_iso2` rather than node ids), per the Prototype
phasing decision in section 2. Node-level baselines are a later pass once
country-level output justifies the split.

Record the residual against LT historical totals as a shrinkage term covering boil off, heel, bunkering and statistical difference. Carry it rather than forcing an exact balance.

### Layer 1: capacity envelope

From `fact_liq_capacity`, an annual exporter side bound at node and country level:

- Status weights: Active and Commissioning 1.0, Under Construction 1.0 from start date, Advanced Development a probability, Planned lower, Postponed lower still, Cancelled and Retired 0. No canonical EA source exists, so these are documented house assumptions in `config/status_weights.yaml`, set once for the central case.
- Ramp: full utilisation reached over roughly 12 to 24 months, so a part year factor in the start year and a ramp factor in the next.
- Utilisation: plateau utilisation by country or project type, typically 85 to 100 percent of nameplate.
- Retired trains excluded entirely per your decision. Separate question in section 12 on trains that reach end of life inside the horizon, some of which started in the 1960s and 1970s.

The regas workbook gives the importer side bound the same way. Rarely binding for mature importers, frequently binding for small emerging ones, which is exactly where naive allocation goes wrong.

The envelope constrains the matrix. It does not set the totals. An envelope below a country's LT export total is a flag to report, not a number to override.

### Layer 2: contracted flows with a fixed destination

Expand contracts to annual volumes. Select, per year, contracts that are not Expired, live in that year, have Destination flexibility Fixed, and resolve to real codes on both sides. Weight by agreement type: SPA 1.0, HOA and MOU a probability, since neither is firm. Aggregate to exporter, importer, year. These become the hard floor.

### Layer 3: flexible, portfolio and multiple destination volumes

1. Flexible contracts with real codes both sides: destination is the central expectation but diversion is allowed, so a soft prior rather than a floor.
2. Real origin, importer XM: origin fixed, destination allocated by netback subject to remaining need and regas headroom.
3. Portfolio, exporter XP, 204 rows: allocate origin across the seller's equity liquefaction positions where the seller is identifiable from the liquefaction workbook Company field, otherwise across the exporter pool in proportion to uncommitted capacity, then allocate destination as in case 2.

Netback is delivered price minus freight, with prices from `fact_lt_price` and freight from `fact_route_distance` times the charter and fuel assumptions. Allocation uses a softmax or proportional share on netback rather than winner takes all, which keeps the matrix realistic and stops flows oscillating between years.

The softmax temperature, which controls how sharply volume follows netback, should be calibrated on observed diversion behaviour in the ship tracking data rather than picked. This is the most valuable thing the tracking data does for the model beyond the baseline.

### Layer 4: residual and reconciliation

Row and column sums will not match the targets after layers 2 and 3. Close with a bounded iterative proportional fit:

- Locked cells: layer 2 flows fixed, or bounded below at contracted level.
- Upper bounds: liquefaction and regas envelopes, plus zero on structurally impossible corridors, meaning sanctions, no active regas that year, no export capability that year, landlocked.
- Zero seeding: a corridor with no history and no contract can open, but only where the netback prior gives it non trivial weight. Without this rule IPF can never move a structural zero and new trade routes never appear.
- Column targets are the derived LNG calls from 5.5, not the LT LNG series. The difference is reported per 5.6.
- Convergence to tolerance on both margins, capped iterations, and any non converging year reported rather than silently returned half balanced.

Every cell carries the layer that set it, so any number traces to a contract, a netback allocation or a balancing residual.

### Layer 5: smoothing

Optional post step limiting year on year corridor change to a plausible band, since real reallocation of flexible volumes is smoother than independent per year optimisation implies.

## 8. Validation

Every run produces a report that fails loudly rather than warning quietly. Beyond the geo suite in 4.8:

**Pipeline and balance**

1. Gas balance closes per country per year within tolerance, using LT components and the derived LNG call.
2. No pipe flow above capacity times availability; none on a corridor without adjacency or a named subsea link.
3. Exporter pipe volumes within production less domestic demand less other exports.
4. Transit consistency: a transit country's net position is unaffected by throughput.
5. Derived LNG call versus the LT LNG series, per country per year, absolute and percentage, with tolerance breaches escalated.
6. Global closure: derived global LNG call against global LNG supply, with the size of the reconciliation adjustment reported.
7. Negative LNG residuals listed, never clamped silently.

**LNG matrix**

8. Row sums against exporter totals, column sums against derived calls, residual per country per year.
9. No cell above its corridor bound, no negative cells, no flow into a country with no active regas that year.
10. Contract coverage: contracted share of each exporter's volume by year. A share above capacity means double counting between the contract stack and the project stack.
11. Continuity: corridors moving more than a threshold year on year, and corridors appearing or disappearing entirely.
12. Freight coverage: share of volume, weighted, whose distance came from the great circle fallback.
13. Reload netting: net basis seed reconciles to gross history less identified reloads.

**Backtest**

14. Run the full chain on a past year using only information available then, and compare to realised flows. Report mean absolute error on the top 30 corridors, and separately on the top 30 pipe corridors.

**Reproducibility**

15. Fixed seed, no wall clock dependency, run manifest recording input hashes, workbook vintage, geo master version, API pull timestamps and config version.

## 9. Architecture and repository shape

Config driven Python, no notebook logic in the pipeline, Windows safe paths throughout. Standalone project, not part of `upstream`.

```
lt_lng_flows/
  config/                  model_config.yaml, status_weights.yaml,
                           pipeline_projects.yaml, freight_assumptions.yaml
  crosswalks/              xwalk_country_alias.csv, xwalk_project_node.csv,
                           xwalk_contract_liqproject.csv, xwalk_hub_country.csv,
                           dim_port.csv, pipe_route_overrides.csv
  src/lt_lng_flows/geo/       country master, nodes, adjacency, routing
  src/lt_lng_flows/ingest/    workbook readers, workbook diff, EA API and shooju pulls
  src/lt_lng_flows/pipe/      pipe capacity, pipe allocation, gas balance
  src/lt_lng_flows/model/     liq capacity, contracts, netback, RAS balancing
  src/lt_lng_flows/validate/  geo checks, pipe checks, model checks, report
  src/lt_lng_flows/output/    plotly html view
  scripts/                 verify_env.py and other entry points
  tools/                   shooju_mcp_launcher.py
  data/geo/raw/            pinned geo snapshots plus manifest
  data/geo/                country_master, geometry, adjacency, route_distance
  data/raw/                api pulls, workbooks/YYYYMM/
  data/interim/            parquet
  data/output/             duckdb file, matrices, html
  tests/
```

Storage: parquet for interchange, a single DuckDB file as the working store. Every table declares its primary key, and every fact table declares foreign keys to `dim_country` and to the node tables. This is what makes the integrity rules in section 4 enforceable rather than aspirational: an unmapped country code raises a constraint error at insert instead of silently joining to NULL or multiplying rows. Verified behaviour, see Appendix A.

Secrets: credentials from environment variables or a local `.env` that is git ignored, per the project instruction. No key material in config, code, notebooks or committed data. A `.env.example` documents variable names only. Gitleaks runs as a pre-commit hook as the backstop.

Environment specification, package compatibility and the setup runbook are in Appendix A.

## 10. Phase 1 output

**Write-back target schema, confirmed against the pinned mapping 545 snapshot
(2026-08-26).** The eventual Shooju write-back (11.12) is not a distant
integration detail; it is the aim, and it fixes the grain the model's output
must reduce to. Mapping 545 is 103 series: 52 `net_exports` (one per country
with LNG exports) and 51 `net_imports` (one per country with LNG imports,
plus one regional aggregate, "North West Europe," carrying no
`country_iso`). 49 countries carry both series -- the same dual-role
structure 5.7 already specifies (a country's `net_exports` is its row total,
`net_imports` its column total, independent of each other, never netted
against one another). So this model's bilateral matrix does not need a new
reduction step invented for write-back: `net_exports_bcm[country, year]` is
the row sum of that country's LNG exports, `net_imports_bcm[country, year]`
is the column sum net of reloads per 5.7, and both already fall out of the
matrix the allocation layer (7) produces. The one regional aggregate in the
103 ("North West Europe") is not stable in EA's own metadata (confirmed by
you, 2026-08-26) and is not evidence for the Europe demand-block node
question in the decisions register -- do not use it to settle that, and do
not chase regional aggregates generally at this stage.

One self contained HTML file, Plotly plus inline CSS and JS, EA branded, no map:

- Year selector, exporter by importer LNG matrix heatmap in bcm.
- Sortable, filterable flat table of exporter, importer, year, bcm, provenance layer.
- Corridor time series: pick exporter and importer, see the annual path to 2050.
- Pipeline matrix on the same pattern, physical border flows.
- Balance panel per country per year: demand, production, pipe in, pipe out, derived LNG call, LT LNG series, and the gap between the last two. This is the panel that will get the most use.
- Diagnostics: margin residuals, global closure adjustment, negative residual list, freight fallback share.

## 11. Session sequence

0. **Environment.** Create the project folder and the conda environment, wire up the Shooju MCP launcher, and pass the verification gate. Runs locally in Claude Code, not in Cowork, because it needs a shell on the machine that holds the credentials. Specification in Appendix A. Gate: `python scripts/verify_env.py` exits 0 and `pytest` passes.
1. **API discovery.** Authenticate, catalogue LT balance components and their exact definitions, pipeline trade granularity, bilateral LNG flows, ship tracking, hub prices, freight assumptions. Deliverable: a data availability and definitions note. No modelling. Runs locally through the Shooju MCP server, or in Cowork if the org Shooju and energyaspects connectors are enabled in the chat.
2. **Geo master.** `dim_country`, nodes, ports, adjacency, alias crosswalk, route distances, pinned snapshots, geo test suite. Deliverable: master plus a coverage report showing every raw country string in every source resolving to a code.
3. **Ingestion.** Workbook readers with vintage pinning and the month on month diff, API pulls, LT balance tables, remaining crosswalks with proposed matches for sign off.
4. **Pipeline capacity and projects.** Assemble `fact_pipe_capacity` and `pipeline_projects.yaml`. This is the stage most likely to need external data and your judgement.
5. **Pipeline forecast and gas balance.** P0 to P5, producing the pipe matrix and the derived LNG call, with the divergence report against the LT LNG series. Review gate: the LNG allocation should not be built on a pipe view that has not been looked at.
6. **LNG baseline.** Seed matrix, gross to net reload conversion, shrinkage term.
7. **LNG capacity envelope.** Status weights, ramps, node level bounds.
8. **Contract stack.** Annual expansion, layer 2 floors, layer 3 priors.
9. **Allocation and balancing.** Netback with tracking calibrated temperature, bounded RAS, provenance tagging.
10. **Validation and backtest.**
11. **HTML view.**
12. Later phase: Shooju write back under an agreed series ID convention, targeting mapping 545's 103-series grain (net_exports/net_imports per country, replacing that incumbent forecast) -- see 10 and the decisions register.

Sessions 1 and 2 can run in parallel with 4, since the pipeline capacity assembly is mostly independent of the geo build.

**v0 target:** sessions 3 and 5 through 7 run country-level only, per the
Prototype phasing decision in section 2. Session 2's node and port
deliverables stay built (already done, not wasted) but stay unused by the
model until a later session's country-level baseline output justifies
drawing on them.

**Session 3 status:** passed its gate country-level, per
`docs/session_03_ingestion.md`. Workbook fact tables, `fact_pipe_flow_hist`
(GTF), the workbook diff module, both pull scripts, and the
`fact_gas_balance`/`fact_lng_flow_baseline`/implied-pipe-diagnostic loaders
are built and tested against fixtures. `fact_gas_balance`,
`fact_lng_flow_baseline`, `lt_region` and the implied-pipe diagnostic are
correctly empty pending the two operator-run pulls (`scripts/pull_ea_series.py`,
`scripts/pull_oilx_flows.py`) — nothing fabricated in their place. Session 5
cannot produce real numbers until those pulls land.

## 12. Open questions

Answered in v1.1 and now closed: API route, bilateral flow availability, region taxonomy, sub-node splits, net basis, retired capacity, scenario count, price availability, workbook refresh, map. Remaining:

1. Does EA maintain a pipeline interconnector capacity database, equivalent to the liquefaction workbook? If not, what is the accepted source, and who owns the project by project view in `pipeline_projects.yaml`?
2. Confirm 5.7: dual role countries appear on both axes, with "net" meaning net of reloads only, not net of their own liquefaction exports.
3. Physical border flows as the pipeline default, per 5.4, with beneficial origin as a derived view. The IEA GTF data now supports this. Confirm or push back.
4. When our derived LNG call diverges from the LT dataset's LNG import series (mapping 545, being replaced by this project, see 5.2), which governs? My assumption: our derived call drives the matrix, the divergence is reported, and a material gap triggers a conversation rather than an override.
5. Are freight assumptions, charter rates and fuel prices available in the LT dataset, or do we set them in config?
6. Liquefaction trains reaching end of life inside 2025 to 2050. Excluding Retired is settled, but the workbook has active trains with start years in the 1960s and 1970s. Apply a plant life rule, source retirement dates, or assume indefinite operation in the central case?
7. Storage: is annual net storage movement material enough in the LT dataset to carry in the balance, or can it be assumed zero?
8. Who signs off `status_weights.yaml` and `pipeline_projects.yaml`? These two files are the model's judgement, and they should have a named owner rather than defaulting to whoever wrote them.
9. Reference conditions. IEA GTF is million cubic metres at 15 degrees Celsius and 760 mm Hg. What basis does the LT dataset use, and is it documented anywhere? Assume it is not, and see Appendix B for how we identify it from the data instead.
10. Non European pipeline history. GTF has no Asian or American coverage, so Power of Siberia, Central Asia to China, and South American pipe have no historical base. Accept a forecast only treatment for those corridors, or source history separately?
11. Netherlands GTF series stops in January 2019. For a major transit country that is a seven year hole in the most recent history. Substitute source, modelled estimate, or carry as a known gap?
12. Is the IEA GTF file a monthly subscription export like the three workbooks? If so it joins the vintage pinning and diff process in 3.1.

## 13. Main risks

- **Pipeline first is the right sequencing and also the main new risk.** Deriving the LNG call rather than taking it means every definitional error in the gas balance lands directly in LNG demand, and errors of that kind are systematic rather than random. Mitigated by pinning component definitions in session 1, by the divergence report against the LT LNG series, and by refusing to silently clamp negative residuals.
- **Pipeline capacity data does not yet exist in hand** and may not exist in EA in usable form. This is now on the critical path in a way it was not in v1.1.
- **The later years carry judgement, not data.** From the mid 2030s the pipe view is a set of assumptions about specific projects. Putting them in one config file with per line source notes makes them arguable; it does not make them right.
- **Contract to project mapping is dirty** enough that fuzzy matching would corrupt origin allocation. Mitigated by the reviewed crosswalk and country level fallback.
- **Portfolio and Multiple are 204 and 305 of 1074 contracts.** Close to half the contract book has an unspecified origin or destination, so the netback allocation does most of the work, and its calibration against tracking data matters more than the contract stack does.
- **Double counting between the contract stack and the totals** is easy to introduce and hard to see. The margin diagnostics exist to make it visible.
- **Monthly workbook drift.** Three files refreshed monthly, not fully on Shooju, with no decided source location. Mitigated by vintage pinning and the diff report, but the source needs settling before this runs unattended.
- **A public geo layer changing shape mid project** would move numbers invisibly. Mitigated by snapshot pinning, hash checks and versioned regeneration.

---

# Appendix A: environment specification

Session 0 of the build sequence. This appendix specifies what the local Claude Code session creates; it is not itself the environment. The build happens locally because it needs a shell on the machine that holds the credentials, and because the environment should be created and tested by whatever will actually run it.

Target: `C:\Users\robert.campbell\PycharmProjects\lt_lng_flows`, a clean conda environment, separate from `upstream`, with Shooju access working through upstream's existing MCP server.

## A.1 Verified compatibility facts

Smoke tested together in a Linux sandbox on 2026-08-21. Versions are what was actually exercised, not what documentation claims.

| Package | Version | Note |
|---|---|---|
| pandas | 3.0.5 | interoperates with geopandas 1.1.4. Nothing in this project needs pandas 3 features, so 2.3.* is an acceptable fallback if conda-forge lags on Windows |
| numpy | 2.4.6 | |
| geopandas | 1.1.4 | conda-forge only on Windows, never pip |
| shapely | 2.1.2 | conda-forge only |
| pyproj | 3.7.2 | conda-forge only |
| duckdb | 1.5.5 | foreign key enforcement confirmed: an unmapped code raises `ConstraintException` on insert |
| searoute | 1.6.0 | pip only. Resolved Sabine Pass to Tokyo at 9,326 nm, consistent with Panama routing. **Returns length in km, not nm.** Convert explicitly |
| shooju | 3.8.16 | pip only. Legacy `setup.py` fails on modern build tooling with `AttributeError: install_layout`. Fix: `pip install --no-build-isolation shooju==3.8.16` |
| pandera | 0.32.1 | dataframe level schema checks, complementing the DuckDB constraints |
| plotly | 6.9.0 | |
| networkx | 3.6.1 | pipeline network and route graph |
| scipy | 1.17.1 | RAS and IPF |

Two rules that cause most Windows geospatial breakage:

1. **conda-forge only.** Do not mix in `defaults`.
2. **Geospatial packages come from conda, never pip.** Pip on Windows pulls incompatible GEOS and PROJ binaries.

## A.2 Environment file

`environment.yml`, python 3.12, channel conda-forge only:

```yaml
name: lt_lng_flows
channels: [conda-forge]
dependencies:
  - python=3.12
  # core data
  - pandas=3.0.*
  - numpy=2.*
  - pyarrow=25.*
  - python-duckdb=1.5.*
  - scipy=1.*
  # excel and config
  - openpyxl=3.1.*
  - pyyaml=6.*
  - python-dotenv=1.*
  # geospatial, conda not pip
  - geopandas=1.1.*
  - shapely=2.1.*
  - pyproj=3.7.*
  - pyogrio
  - networkx=3.*
  # validation and output
  - pandera=0.32.*
  - plotly=6.*
  # tooling
  - pytest=9.*
  - pytest-cov
  - ruff=0.16.*
  - pre-commit
  - pip
  - pip:
      - searoute==1.6.0
      - shooju==3.8.16
      - mcp            # only if the shooju launcher runs on this interpreter
```

Supporting files: `pyproject.toml` with a src layout, ruff configured with the `PTH` rules so pathlib is enforced over `os.path` and Windows paths stay sane, pytest pointed at `tests/`. `.gitignore` excluding `.env`, `data/**`, `.idea/` and generated outputs. `.pre-commit-config.yaml` running ruff, gitleaks and a large file guard.

## A.3 Setup runbook

1. Create the project folder and initialise git.
2. `conda env create -f environment.yml` then `conda activate lt_lng_flows`. If solving is slow, install `conda-libmamba-solver` in base and set it as the solver.
3. If the shooju install fails, retry with `--no-build-isolation`.
4. `pip install -e .` and `pre-commit install`.
5. Copy `.env.example` to `.env` and fill it in. Before filling it, check the variable names upstream actually uses and match them, so one set of credentials serves both projects. Confirm the file is ignored with `git check-ignore -v .env`.
6. **Gate:** `python scripts/verify_env.py` exits 0, and `pytest` passes. Nothing else starts until both hold.
7. PyCharm: set the interpreter to the existing `lt_lng_flows` conda env, mark `src` as Sources Root, set the default test runner to pytest.

## A.4 The verification gate

`scripts/verify_env.py` is worth having as a first class script rather than a manual checklist, because three of its checks catch failures that are otherwise silent until much later:

1. Python version.
2. Every required import, with the version it resolved to.
3. **DuckDB really rejects an unmapped foreign key.** The data model depends on this. If a future DuckDB version relaxed it, every integrity guarantee in section 4 would quietly become decorative.
4. **searoute resolves a known lane to a plausible distance**, and reports the units it returned. This is the check that catches the km versus nm trap.
5. pandas and geopandas interoperate on the installed pairing.
6. Expected environment variable **names** are present. Reports set or not set only, never a value.

Exit code 0 means proceed.

## A.5 Environment variables

`.env.example` documents names only:

```
SHOOJU_SERVER, SHOOJU_USER, SHOOJU_KEY
EA_API_BASE_URL, EA_API_KEY
UPSTREAM_DIR        absolute path to the upstream project
WORKBOOK_ROOT       folder holding monthly workbook vintages
```

The shooju names above are the client library's conventional ones. Upstream already holds working credentials, so the local session should read the names it actually uses and align, rather than introducing a second convention.

Credentials are read at runtime by code, from the environment or the gitignored `.env`, and are never printed, logged, committed or echoed. `verify_env.py` reports set or not set, by name only.

An agent session may decline to execute an authenticated call itself, even where the key resolves from the environment. Do not plan the build around one that will. Live access is needed in exactly two places: API discovery, and the raw pull that writes `data/raw/`. Both run either through a credentialed MCP server, as A.6 arranges for Shooju, or by the operator running the script with the session working from the resulting snapshot. Everything downstream reads pinned snapshots per section 9 and needs no credential at all.

## A.6 Shooju MCP access, and the failure mode to avoid

Upstream's `.mcp.json` runs a **stdio** server, `python tools/shooju_mcp_server.py`, with `env: {}`, so it inherits credentials from the environment and resolves paths relative to the upstream working directory.

Two consequences:

1. A stdio server runs as a subprocess of whatever runs the client. It is reachable from a local Claude Code session and is not reachable from a Cowork session in a cloud container. That is by design, not misconfiguration.
2. Pointing a new project's `.mcp.json` straight at that script would run it with a different working directory. The realistic failure is not a crash but a silent one: the server starts and cannot find its credentials or its relative config.

So the new project gets `tools/shooju_mcp_launcher.py`, which resolves the upstream directory from `UPSTREAM_DIR` with a hard coded default, changes to it, puts it on `sys.path`, and then executes upstream's server. It supports a `--check` flag that verifies the target resolves without starting the server. Credentials stay in the upstream `.env` on the local machine; the launcher never reads or copies them.

If the upstream server imports upstream package modules, those must be importable on whichever interpreter runs the launcher. Preferred fix: point the `command` at the upstream conda environment's `python.exe` directly. Fallback: `pip install -e` the upstream project into this environment, accepting the coupling.

## A.7 Config files created empty of judgement

Four config files are created in session 0 with structure but no invented numbers, so that later sessions cannot mistake a placeholder for a view:

- `model_config.yaml`. Horizon, units, seed years and the Europe regime break, capacity utilisation and ramp, balancing tolerances, and `clamp_negative_lng_residuals: false`, which must stay false per 5.6. The netback softmax temperature is left null because it is calibrated on tracking data, not chosen.
- `status_weights.yaml`. Liquefaction, regas and agreement type weights. Firm statuses set to 1.0 and cancelled to 0.0; every judgemental value marked for review, with an owner field left null.
- `pipeline_projects.yaml`. One entry per prospective project, with capacity, start year, ramp, availability and source all null, to be filled from house view or a cited source. Seeded with the projects that matter to the later years: Power of Siberia 2, Central Asia to China line D, TANAP and TAP expansion, TAPI, East Med, Nigeria to Morocco, Argentina into Brazil, and an explicit entry for any Russia into Europe restoration, so the central case has to state a position rather than leave one implicit.
- `freight_assumptions.yaml`. Vessel reference, charter rate, bunker price, canal costs, port time. All null pending the session 1 answer on whether the LT dataset already publishes these.

## A.8 Project conventions file

A short `CLAUDE.md` in the new project, carrying the invariants rather than the method: ISO2 as the only country key; no fuzzy or plaintext joins without approval; foreign keys enforced by the database; ASCII lower snake case identifiers for Shooju and Windows safety; secrets in `.env` only; fail loudly with no silent clamping or dropping; no live external calls at model runtime; every numeric value in config rather than code; provenance recorded on every output cell.


---

# Appendix B: unit conversion and reference conditions

Recorded as a standing data integrity risk, not a task. It needs handling in session 1 and a permanent guard in the code.

## B.1 The problem

Gas volumes are meaningless without a reference condition, and the sources we are combining do not share one.

- IEA Gas Trade Flows states its basis explicitly: million cubic metres at 15 degrees Celsius and 760 mm Hg.
- Eurostat publishes both million cubic metres and terajoules GCV, without a prominent statement of the volume basis.
- The EA LT dataset's basis is unknown. Given that EA metadata practices are acknowledged to be poor, the working assumption is that **it is not documented anywhere we can look it up**. That is the reason this appendix exists.

Verified arithmetic, computed rather than quoted:

| Comparison | Ratio | Effect |
|---|---|---|
| 15 C basis against 0 C basis | 1.05491 | the same quantity of gas is 5.49 percent larger when expressed at 15 C |
| 60 F basis against 15 C basis | 1.00193 | 0.19 percent, immaterial |
| 760 mm Hg against 14.696 psia | 1.00000 | identical, both are 101.325 kPa |

So the only basis difference that matters here is 15 C against 0 C, and it is 5.49 percent.

## B.2 Why this lands on the headline number

Pipeline first sequencing makes this worse than it would otherwise be. The LNG call is derived as a residual from the gas balance in 5.2. A systematic basis error in the pipeline term does not average out across countries and does not partly cancel; it flows in one direction, straight into the residual.

Order of magnitude: on 300 bcm of European pipeline imports, a 5.49 percent basis error is **16.5 bcm landing entirely in the derived LNG call**. That is larger than the total LNG imports of most individual European countries, and it is bigger than the 5 percent divergence tolerance in 5.6. An undetected basis mismatch would therefore present as a real disagreement with the LT dataset's own LNG series, and we would spend the review arguing about pipeline assumptions that were never the problem.

## B.3 One piece of positive evidence already in hand

The contracts workbook cover row states Mt to bcm as 1.37. That factor is itself a clue to EA's basis.

Taking LNG at roughly 55 MJ/kg GCV and pipeline quality gas at roughly 40 MJ per cubic metre at 15 C:

- on a 15 C basis, 1 Mt LNG implies **1.375 bcm**
- on a 0 C basis, the same gas is about 42.2 MJ per normal cubic metre, implying **1.303 bcm**

The stated 1.37 is consistent with a 15 C basis and inconsistent with a 0 C one. That is encouraging, because it would mean EA and IEA GTF agree. It is a hypothesis to test, not a conclusion: the calorific values above are typical rather than measured, and a factor can be inherited from a source whose basis differs from the data it is being applied to.

## B.4 Identifying the basis empirically

Since documentation is unlikely to settle it, four tests using data we already hold. None requires anyone at EA to remember anything.

1. **Back-derive from multi-unit rows.** The liquefaction and regas workbooks carry MTPA, bcf/d and bcma for every project row. Three units for one quantity means the implied conversion factors are directly computable, and internally checkable for consistency across 1,232 rows. A factor that drifts by project, or a bcf/d to bcma ratio that is not constant, tells us something about how the file was built.
2. **Back-derive from the contracts workbook.** Every contract row carries both bcm and MTPA. Compute the implied factor per row and check whether it is uniformly 1.37 or varies. Variation would mean the file mixes sources.
3. **Cross-check overlapping series against IEA.** For European corridors and years where both EA and IEA GTF cover the same border pair, take the ratio of the two. A ratio clustering near 1.000 means the bases match. A ratio clustering near 1.055 identifies the basis difference without any documentation at all. This is the strongest test available and it should be run in session 1, not later.
4. **Test against a published global identity.** IGU puts 2025 global LNG trade at 437.0 Mt. Divide EA's global LNG total in bcm by 437.0. A result near 1.37 is consistent with the workbook factor; a result near 1.30 says something differs.

Use Eurostat's dual publication as a supporting check: dividing its terajoule GCV series by its cubic metre series gives an implied calorific value per cubic metre for each reporting and partner pair, and whether that lands nearer 40 or nearer 42 MJ indicates the volume basis.

## B.5 Rules to build in

1. **One canonical internal unit**: bcm at a single declared reference condition, written explicitly in `model_config.yaml`. Never implicit, never inherited from whichever file was read last.
2. **Conversions live in one module.** No conversion arithmetic anywhere else in `src`. A factor appearing inline in a model file is a defect.
3. **A conversion registry table**, one row per factor, carrying source, from unit, to unit, factor, reference basis, and provenance as one of `documented`, `back_derived` or `assumed`, plus a confidence flag. Any factor marked `assumed` appears in every validation report until it is resolved.
4. **Quantities carry their basis.** A column of numbers with no recorded unit and basis should not be able to reach the balance identity. This is what the pandera schemas are for.
5. **Run the sensitivity.** Execute the model once on each candidate basis and report the delta on the derived LNG call per country per year. If the delta exceeds the 5.6 tolerance, the basis question is blocking and the model does not publish until it is answered. If it does not, say so and move on.
6. **Composition varies.** Even with the basis settled, a single global Mt to bcm factor carries roughly plus or minus 2 percent error at country level, because rich Nigerian and Algerian LNG differs from leaner Australian and Qatari cargoes. Acceptable for a long term annual model, but it should be a recorded assumption rather than an accident, and it argues against quoting outputs to more precision than they carry.
