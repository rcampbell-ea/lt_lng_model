# lt_lng_flows: build plan for sessions 2 and 3

For Claude Code running Sonnet 5 at medium effort. Companion to
`docs/sessions_00_01_build_plan.md`. Same discipline: both sessions are
specified so no modelling judgement is required, and where a decision cannot be
made from this document plus the plan, the session stops and asks.

Session 2 is the geo master, section 4 of the plan. Session 3 is ingestion,
section 3 and the balance inputs for section 5. They correspond to sessions 2
and 3 of the plan's section 11 sequence.

## 0. Human steps that gate these sessions

Neither session can start, or close out cleanly, unless a person has done
something first. Gates A and B were named before session 2 ran. Gates C, D
and E were discovered during session 2 itself and are recorded here on the
same footing, not left to live only in `docs/session_02_geo_master.md`: this
section is what a session reads before starting, and a gate that only
appears in a build report is a gate a later session can miss.

**Gate A, before session 2: sign off the alias crosswalk.** Session 1 produced
`crosswalks/xwalk_country_alias_proposed.csv`, 711 rows, with 39 unresolved
across 30 distinct raw values. Those 39 are filled in
`crosswalks/xwalk_country_alias_proposed_filled.csv`: 25 as `ea_published_pair`,
matching EA's own published country names exactly, and 14 as `proposed_variant`,
which are the rows that need a human eye. A person reviews and renames the file
to `crosswalks/xwalk_country_alias.csv`. Check 2 of plan 4.8 makes an unresolved
value a build failure, so session 2 stops rather than proceeding on a partial
crosswalk. That is intended.

One row is a data quality finding rather than a variant: `Hondrus` in the
contracts workbook is a typo for Honduras. It is mapped to HN so the build
proceeds, and the note records it, but the workbook is what should be corrected
or the next vintage reintroduces it.

`Republic of Türkiye` carries a non-ASCII character in `raw_value`. That is
correct and stays: raw values are data, not identifiers. Any ASCII check must
apply to identifiers and column names, not to raw source strings.

**Gate B, during or after session 2: port coordinates.** `dim_port` needs a
latitude and longitude per representative port, and **EA does not publish
them.** The cargo tracking files give integer port ids and their country
grouping, nothing more, and neither project workbook carries a position: their
columns are Region, Country, ISO 2-letter code, Project, Trains, Company, Start
date, Start Year, MTPA, bcf/d, bcma, Status, Type and FTA. Confirmed by reading
both workbooks.

So coordinates come from a public domain external source, pinned like any other
snapshot, and the assignment of a port to a node is a reviewed crosswalk rather
than a name join. Session 2 pulls the source and proposes only exact matches;
everything else stays null for sign off.

Scale is worth knowing before choosing an approach: plan 4.3 wants roughly 40
load and 60 to 80 discharge ports, so about 120 rows. Filling 120 coordinates by
hand from a chart is a legitimate path and may well be faster than reviewing a
generated crosswalk. Either way the artefact is the same reviewed CSV, so the
decision can be taken after seeing how many rows match exactly.

Until the file is signed off, `fact_route_distance` cannot be computed and plan
checks 4.8.6 and 4.8.7 cannot run. Session 2 reports them as not runnable
rather than passing them.

Do not let a session resolve either gate by inference. A geocoded port or a
guessed ISO2 is exactly the kind of plausible wrong value the plan is built to
keep out.

**Gate C, discovered in session 2: Gibraltar has an LNG role but no geometry.**
Gibraltar (GI) is a real regas importer in `202608_LNG_regas_projects.xlsx`
(`workbook_regas`, one row), so `role_lng` is non-`none` for it. The pinned
Natural Earth Admin 0 Countries 1:50m snapshot does not carve Gibraltar out as
a separate polygon at that resolution: it is absorbed into Spain's outline.
`dim_country` therefore carries GI with `continent`, `un_subregion`,
`centroid_lat`, `centroid_lon`, `is_landlocked` and the three geo lineage
columns all null, and plan 4.8 check 4 fails for it (reported, not silenced;
see `session2_check_4_geometry_and_containment` in `geo_checks.py`).

Two ways to close it, neither of which a session should pick on its own:
1. A third network pull, Natural Earth Admin 0 Countries **10m** (same
   public-domain family as the pinned 1:50m layer, which does carve Gibraltar
   out separately), used only to fill this one country's geometry. This
   exceeds the two pulls sessions 2.1/2.1b authorise, so it needs the same
   kind of sign off gates A and B got, not a session's own judgement call.
2. A hand-reviewed coordinate for Gibraltar, entered the same way gate B's
   port coordinates are: a reviewed row, not an inferred one. The session 2
   "do not" list ("do not geocode anything") forbids a session doing this
   unreviewed.

Until this closes, GI stays in `dim_country` with the null geometry columns
above, is excluded from `dim_country_adjacency` (see gate D), and any pipe or
LNG check that depends on its geometry, continent or landlocked flag reports
GI as not runnable rather than silently passing or failing.

**Gate D, discovered in session 2: Kosovo has geometry but no `dim_country`
row.** The pinned Natural Earth Admin 0 Countries 1:50m snapshot gives Kosovo
`ISO_A2_EH = 'XK'` and a real polygon. Plan 4.4 reserves `XK` ("avoid XK,
already used de facto for Kosovo") but never adds a `dim_country` row for it,
and Kosovo is not in the session 1 ISO 3166-1 snapshot (it has no official ISO
3166-1 code). Kosovo appears in none of the three LNG workbooks or the IEA GTF
file, so it carries `role_lng = none` and `role_pipe = none` either way.

Session 2 does not invent a real-or-pseudo classification for XK on its own
judgement: `dim_country_adjacency` declares a foreign key to `dim_country`, so
every adjacency pair touching XK is filtered out before that table is built
(`build_session2.py`, "Gate D" block) rather than raising a constraint error
or silently including a code with no dimension row. This means Kosovo's real
land borders (with Serbia, Albania, North Macedonia, Montenegro) are currently
**absent** from `dim_country_adjacency`, which matters directly for session
3.3's GTF adjacency check: if any GTF border point ever names Kosovo (none do
in the pinned 202606 vintage, confirmed), that row would need this gate closed
first, not a fallback.

Closing it needs a decision, not a derivation: whether Kosovo gets a formal
`dim_country` row (as `is_real_country = True` with a documented ISO
exception, or as an eighth pseudo code alongside XP/XM/XR/XL/XN/XX/ZZ), and if
so, whether its geometry comes from the same 1:50m snapshot already pinned
(it already has a valid polygon there, unlike Gibraltar) or needs its own
review.

**Gate E, discovered in session 2: split-country project-to-node assignment.**
Plan 4.3's node split (US into `us_gulf`/`us_east`/`us_west`/`us_alaska`,
Canada into `ca_east`/`ca_west`, Russia into four, Australia into three) has
no supporting field in either the liquefaction or regas workbook: both carry
only `Region`, `Country` and `ISO 2-letter code`, no sub-national location.
`crosswalks/xwalk_project_node_proposed.csv`, built in session 2, therefore
resolves `country_iso2` and `port_role` for every project row but leaves
`node_id` empty and `method = unresolved_split_country` for every project in
the four split countries — 31.6% of total pinned capacity by the session 2
count, so this is not a small residual. The same gap blocks the `load`/
`discharge` rows for those countries in `crosswalks/dim_port_candidate.csv`.

This is the same crosswalk plan 3.7 already names as a session 3 deliverable
(`xwalk_project_node.csv`, "using the EA area evidence from session 1"):
session 2's file is the honest starting point for that work, not a finished
proposal, since assigning a project name like "Sabine Pass" to `us_gulf`
needs either the EA cargo-tracking area evidence in
`crosswalks/xwalk_area_node_proposed.csv` or a human's own knowledge of the
project, and CLAUDE.md forbids inferring it from the project name string. Do
not treat `crosswalks/xwalk_project_node_proposed.csv` as already reviewed:
review it the same way gates A and B were reviewed, then rename or replace it
per whatever session 3 names as the final file.

## 1. Rules that bind both sessions

The nine rules in section 2 of the sessions 0 and 1 plan still apply, with one
amendment.

Rule 8 was no network calls. In session 2 that becomes: **two network pulls are
permitted, the geo boundary snapshot and the port gazetteer, and only through a
pull script that writes a hashed manifest.** Both are unauthenticated public
data, so no credential is involved. Everything after the pulls reads the
snapshots. Session 3 returns to no network calls at all: the EA pull script it
writes is run by the operator.

Two additions:

10. **Every table loaded into DuckDB declares `PRIMARY KEY` and, where the plan
    names one, `FOREIGN KEY`.** Enforcement by the database is the point. A
    test must prove an unmapped code actually raises on insert, per plan A.4
    check 3, rather than asserting that it would.
11. **Manifests end `_manifest.json`.** `data/**` is gitignored except
    directories, `.gitkeep`, and that suffix. A manifest named anything else is
    silently untracked and its provenance is lost.

## 2. Session 2: geo master

Plan section 4 in full is the specification. Read 4.1 to 4.9 before writing
anything. This section says what to build and in what order, and names the
traps.

### Inputs

`crosswalks/xwalk_country_alias.csv` from gate A, the three workbooks and the
IEA GTF export in `data/raw`, the five EA snapshots in
`data/raw/ea_api/202608/` (`ea_api_mappings.txt`, `ea_ct_areas_metadata.txt`,
`ea_ct_country_ports.txt`, `ea_ct_cargoes.txt`, `ea_ts_metadata.txt`),
`crosswalks/xwalk_ea_api_country.csv`, and the `data/interim/` outputs and
`data/geo/dim_country.parquet` written by session 1.

### Deliverables

**2.1 `scripts/pull_geo_snapshots.py` and `data/geo/raw/`**

Pull Natural Earth Admin 0 Countries at 1:50m once. Write the payload plus
`natural_earth_admin0_50m_manifest.json` recording source URL, retrieval
timestamp, byte count and sha256.

Two specific warnings, both of which have cost people a day:

- **Do not use `geopandas.datasets`.** The bundled Natural Earth datasets were
  deprecated and removed in geopandas 1.0. Code written against them fails on
  the pinned environment. Fetch the archive from a pinned URL instead.
- Natural Earth's own host has been intermittently unavailable in the past. If
  the pull fails, do not substitute a different boundary source or a different
  resolution to get past it. Report the failure, name the URL, and stop.

ArcGIS Living Atlas is an optional cross check in plan 4.2 and is **out of
scope for this session**. Do not pull it.

**2.1b Port coordinate source**

Pull one public domain port gazetteer into `data/geo/raw/`, with its own
`_manifest.json` on the same pattern. Preference order:

1. **World Port Index**, NGA Publication 150. A work of the US Government, so
   public domain. Roughly 3,700 ports with name, country, coordinates and
   harbour attributes. Best coverage of the ports the model needs.
2. **Natural Earth 10m ports**, if World Port Index cannot be retrieved. Public
   domain, same source family as the Admin 0 layer, but far thinner.

Do not use OpenStreetMap harbour data. It is ODbL, which carries share alike
obligations that are the wrong shape for a redistributable reference table.

Record which source was used in the manifest and in the report. If neither can
be retrieved, say so and leave 2.7 entirely null rather than substituting a
third source unreviewed.

**2.2 `crosswalks/xwalk_country_alias.csv` applied, plus the EA API source system**

`crosswalks/xwalk_ea_api_country.csv` holds 254 EA API country names paired to
ISO2 as published by EA in `ea_ts_metadata.txt`, method `ea_published_pair`,
`source_system` `ea_api_timeseries`. Session 1 never saw it, so that source
system is absent from the 711 rows. Merge it in as a sixth source system. Do not
re-derive it, do not name match against it, and do not alter its codes.

Two facts in it that plan 4.5's trap list does not yet carry: EA publishes
`Korea` for KR, not `South_Korea`; and EA's own unknown code is `XX`, which maps
to a distinct pseudo code and never to ZZ, because `XX` is EA saying it does not
know while a ZZ in our output is a bug.

Rename the reviewed proposal, then apply it. Applying means: every raw country
string in every source resolves to a `country_iso2` through this table and
through nothing else. No name matching anywhere in the codebase from this point
on.

Constraints from plan 4.3 and 4.8:

- Key is `(source_system, raw_value)`. Many to one only. A raw value mapping to
  two codes fails the build and names both.
- An unresolved raw value fails the build and is listed. It is never dropped,
  and it never becomes ZZ.

**2.3 `data/geo/dim_country.parquet`, replacing session 1's interim version**

Session 1 already wrote this file from the ISO 3166-1 list alone. **Session 2
replaces it**, it does not append to it and does not skip it because the path
exists. The session 1 version has no geometry-derived columns, no ISO3, no
centroids, no roles and no lineage. Read it, diff the country list against the
new one, and report any country present in one and not the other. A country
disappearing between the two is a defect, not a tidy-up.

Every column in the plan 4.3 table, no substitutions and no additions. The
lineage columns `geo_source`, `geo_snapshot_date`, `geo_snapshot_sha256` come
from the 2.1 manifest.

`role_lng` and `role_pipe` are derived from the data, not asserted: `role_lng`
from whether the country appears as an exporter or importer in the liquefaction
and regas workbooks, `role_pipe` from whether it appears as an entry, exit or
transit party in the GTF file. A country appearing on neither gets `none`.

`lt_region` is created and left **null**. It is derived from the LT demand series
per plan 4.3b and cannot be populated until session 3 has the pull. Do not fill
it from the API `region` field, from Natural Earth, or from the workbook region
columns. `continent` and `un_subregion` come from Natural Earth as normal.

**Each of the six traps in plan 4.5 gets its own named test, not a comment.**

1. `ISO_A2` is -99 for several Natural Earth entities, and in some vintages
   that has included France and Norway as well as Kosovo, Northern Cyprus and
   Somaliland. Use `ISO_A2_EH` where present, patch the remainder from the ISO
   list, and assert that no -99 survives. A silent -99 is a silently dropped
   country.
2. Name variants resolve as: UK to GB, South Korea to KR, Turkey and Turkiye
   both to TR, UAE to AE, Trinidad and Tobago to TT, Myanmar and Burma both to
   MM.
3. CD and CG are different countries. Assert they resolve separately and that
   neither inherits the other's rows.
4. Curacao is CW, Puerto Rico is PR, Gibraltar is GI, and none of them folds
   into a parent state.
5. Taiwan is TW whatever a third party layer calls it.
6. The `ISO 2-letter code` column already in the two project workbooks is
   validated against the master. Where the workbook code and the alias
   resolution of the country name disagree, **report the conflict, do not
   resolve it**. That is a data quality finding for EA, and picking a winner
   silently destroys the evidence.

**2.4 `data/geo/geo_country_geometry.parquet`**

GeoParquet keyed on `country_iso2`, kept out of the dimension table so that
stays diffable. The stored point is the **pole of inaccessibility, not the
centroid**, so it sits inside the polygon for concave and multipart countries.
Assert containment per country; a point outside its own polygon fails.

**2.5 `data/geo/dim_country_adjacency.parquet` and
`crosswalks/adjacency_override.csv`**

Key `(country_iso2_a, country_iso2_b)`, derived from shared land border in the
geometry. Adjacency must be symmetric.

The override file exists for two cases the geometry gets wrong: a border that
exists geometrically but has no pipeline crossing, and a named subsea link
between non-adjacent countries. Create it with a header and a documented
schema, and populate it only where the evidence is in the GTF file. Do not
invent links. Every row carries a source note.

**2.6 `data/geo/dim_supply_node.parquet` and `dim_demand_node.parquet`**

Exactly the splits in plan 4.3: four US nodes, two Canadian, four Russian,
three Australian, and one node per country elsewhere with `node_id` equal to
the country slug. Do not add nodes, and do not adopt EA's finer taxonomy.

`crosswalks/xwalk_area_node_proposed.csv` from session 1 is **evidence, not
input**. EA's 53 areas split the US five ways against the plan's four, so the
mapping is not one to one. Report the discrepancy and leave it for sign off.

Node to country aggregation must reproduce country totals exactly, for capacity
now and for flows later. Test it with real workbook capacity, not with a
fixture.

**2.7 `crosswalks/dim_port_candidate.csv`**

Columns: `node_id`, `country_iso2`, `ea_project_name`, `port_role` (load,
discharge, or both), `gazetteer_port_name`, `gazetteer_id`, `latitude`,
`longitude`, `method`, `confidence`, `source`, `note`.

Populate `node_id`, `country_iso2`, `ea_project_name` and `port_role` from the
liquefaction and regas workbooks. Then attempt one assignment against the
gazetteer from 2.1b, under the same rules session 1 used for countries:

- `method = exact_name` and `confidence = high` only where the EA project or
  terminal name matches a gazetteer port name exactly, case insensitively,
  within the same country. Fill the coordinates on those rows only.
- Everything else is `method = unresolved`, `confidence = none`, coordinates
  **null**. No fuzzy matching, no edit distance, no nearest-port-in-country, no
  substring matching. EA project names are plant names rather than port names,
  so expect the exact match rate to be low. A low rate is the correct outcome,
  not a failure to work around.
- Never fill a coordinate from a country centroid or a pole of inaccessibility.
  A wrong port position becomes a wrong freight distance and then a wrong
  netback, and nothing downstream will ever flag it.

Target scale from plan 4.3 is roughly 40 load and 60 to 80 discharge ports.
Report the actual counts and the exact match rate, so the choice between
reviewing this file and hand-filling it can be made on evidence.

**2.8 `data/output/lt_lng_flows.duckdb`**

Create the working store and load `dim_country`, `dim_country_adjacency`,
`dim_supply_node`, `dim_demand_node` and the applied alias crosswalk, each with
its primary key declared and its foreign keys to `dim_country` declared.

Then prove enforcement: a test that attempts to insert a fact row carrying an
unmapped `country_iso2` and asserts the insert raises. If it does not raise,
every integrity guarantee in plan section 4 is decorative and the session
should stop and say so.

**2.9 `src/lt_lng_flows/validate/geo_checks.py`**

Add one check specific to 2.7: every row with `confidence = high` has both
coordinates non null and within valid bounds, and every row with
`method = unresolved` has both null. A high confidence row with a null
coordinate, or an unresolved row with a filled one, fails.

Implement plan 4.8 checks 1 to 5 and 8 to 11. Checks 6 and 7, port coordinates
and route distances, cannot run until gate B closes: implement them, mark them
skipped with the reason, and make the skip visible in the report rather than
silent.

`fact_route_distance` and the `searoute` work in plan 4.7 are **out of scope for
this session**, because they need coordinates. Do not stub them with
placeholder distances.

**2.10 `docs/session_02_geo_master.md`**

The coverage report the plan asks for: every raw country string in every source
resolving to a code, counted by source system. Plus the workbook ISO2 conflicts
from trap 6, the node discrepancy from 2.6, the port candidate counts, and the
two skipped checks with their reason.

### Do not

- Compute route distances, or install or call `searoute`.
- Geocode anything.
- Pull the ArcGIS layer.
- Create `dim_aggregate`. The LT dataset taxonomy it needs is not on disk yet;
  it belongs to session 3.
- Read any EA series data. None has been pulled.
- Start session 3.

### Gate

`verify_env` exits 0, `pytest` passes, plan 4.8 checks 1 to 5 and 8 to 11 pass,
and the foreign key enforcement test in 2.8 passes. Checks 6 and 7 report as
skipped with a reason.

## 3. Session 3: ingestion

Plan sections 3.1, 3.4, 5.2 and 6, plus `docs/session_01_data_availability.md`
**and `docs/session_02_geo_master.md` in full**, and section 0 above, gates C,
D and E specifically: all three were discovered during session 2, not named
before it, and none is resolved yet. Read them before touching
`dim_country_adjacency`, `crosswalks/xwalk_project_node_proposed.csv` or
`crosswalks/dim_port_candidate.csv`. This session turns the pinned snapshots
into typed fact tables, and writes the one script the operator runs to bring
EA series data in.

### Deliverables

**3.1 Typed fact tables from the three workbooks**

`fact_liq_project`, `fact_regas_project`, `fact_lng_contract`, loaded into
DuckDB with primary keys and foreign keys to `dim_country` and, where the plan
says so, to the node tables.

Row counts to assert against plan 3.1, so a silent parse failure is caught:
liquefaction 617 project or train rows across 39 countries, regas 615 rows
across 78 countries, contracts 1,074 rows and 27 columns with header on row 3.
All three sheets report a max row near 3,500 because of trailing formatting, so
**trim on all-null rows and never trust the sheet dimension**.

Contract distributions to assert, also from plan 3.1: status Current 512,
Future 356, Expired 206. Delivery type DES 525, FOB 474, DES/FOB 48, dash 26,
Undeclared 1. Export country 31 values of which Portfolio is 204 rows. Import
country 61 values of which Multiple is 305 rows. Portfolio resolves to XP and
Multiple to XM, per plan 4.4, and neither is ever dropped.

Annual expansion of contracts belongs to session 8. Do not do it here.

**3.2 `src/lt_lng_flows/ingest/workbook_diff.py`**

Month on month diff per plan 3.1: new projects, status changes, capacity
revisions, contracts added, amended, expired. Only one vintage exists, so the
module must report "no prior vintage found" as a result rather than being
skipped or left untested. Test it against a synthetic second vintage built in
the test fixture, so the diff logic is exercised now and not first exercised in
September when it matters.

**3.3 `fact_pipe_flow_hist` from the IEA GTF export**

Physical border flows, directional, per plan 3.4 and 5.4. This is the European
pipeline baseline and the only historical pipe basis the model has.

The two non-country values in the GTF entry and exit columns resolve to pseudo
codes, per plan 4.4: `Liquefied Natural Gas` to XL, because it is a mode and
not a place, and `Not Elsewhere Specified` to XN. Neither enters `dim_country`
as real.

Assert that every flow row's origin and destination pair either has adjacency
in `dim_country_adjacency` or an explicit override row. A pipe flow between two
countries with no shared border and no named subsea link is a data error, per
plan 4.3.

**Gate D note.** `dim_country_adjacency` currently excludes Kosovo (XK)
entirely, per gate D in section 0: it has no `dim_country` row, so any pair
touching it was filtered out rather than left to violate the foreign key.
Confirmed against the pinned 202606 GTF vintage: no row names Kosovo, so this
assertion does not fail on that account today. If a future GTF vintage adds a
Kosovo border point, this assertion will correctly fail until gate D closes,
and that failure is expected, not a bug in this check.

**3.4 `scripts/pull_ea_series.py`, for the operator to run**

Parameterised by `mapping_id`. It reads
`data/raw/ea_api/202608/ea_api_mappings.txt`, takes the mapping's
`dataset_ids`, **deduplicates them**, and issues the request using the
`request_string` template already in the catalogue. It writes the response plus
a `_manifest.json` to `data/raw/ea_api/<vintage>/mapping_<id>/`.

The key is read from the environment. The script never prints it, and the
session does not run the script.

State the exact commands to run, in this priority order, because these are what
the balance in plan 5.2 needs:

| mapping_id | name | why |
|---|---|---|
| 297 | Long term gas supply | production, and the open question of whether it carries net pipe trade |
| 314 | Long term total demand | the demand term |
| 553 | Long term losses | own use and losses |
| 545 | Long term LNG imports and exports | the benchmark for the derived LNG call, per plan 5.6 |
| 300 | Long term prices | netback in plan section 7 |
| 5, 6 | Global LNG exports, imports | country totals for the backtest |

**3.5 `fact_gas_balance` from whatever EA snapshots exist**

Long form: `country_iso2`, `year`, `component`, `value`, `unit`,
`lifecycle_stage`, `dataset_id`, `release_date`, `source`. Components named to
match plan 5.2 exactly, with the sign convention fixed in code and stated in a
docstring.

If no EA snapshot exists yet because the operator has not run 3.4, build the
loader, test it against a fixture, and report the table as empty pending the
pull. Do not fabricate a balance.

**3.6 Answer the six open questions in the availability note**

`docs/session_01_data_availability.md` section 6 lists six definitional
questions: whether mapping 297 carries net pipe trade, whether demand is gross
inland or final consumption, whether production is marketed or gross, whether
LNG imports are gross or net of reloads, what mapping 614 is, and units and
frequency per series. Every one resolves from series metadata in the pull.

Answer them from the metadata and write the answers into
`docs/session_03_definitions.md`. Where the metadata does not settle a
question, say so and name what would. This document gates the balance
implementation in plan 5.2, so a guess here propagates into every derived LNG
call in the same direction.

**3.6b `lt_region` derived from the LT demand series, and the region tag table**

Per plan 4.3b. Take the distinct `(country_iso, region)` pairs on the series in
mappings 314 and 550 to 560. Test the result: every real country exactly once,
and every country with `role_lng` or `role_pipe` other than `none` present. If it
is a partition, populate `lt_region` in `dim_country`. If it is not, **stop and
list the offenders**. Do not pick a winner, do not fall back to the API `region`
field, and do not fill from Natural Earth.

Where a country carries a geographic region on one sector's series and an OECD,
OPEC, Suez or WORLD value on another's, report it as a multi-valued country and
leave `lt_region` null for that country. The rule for resolving it is an open
decision for sign off, recorded in plan 4.3b, and is not a code default.

Then build `dim_country_region_tag`, key `(country_iso2, scheme, tag_value)`,
many to many, loading every EA grouping available: `ea_api_region`,
`ea_api_sub_region`, `ea_workbook_region`, `ea_supply_area`, `ea_demand_area`.
The `padd`, `oecd`, `opec` and `suez` schemes are populated only from values that
actually appear in the data, never inferred.

Record in the manifest which mappings `lt_region` was derived from, the vintage,
and the partition test result.

**3.7 Remaining crosswalks, proposed**

The EA API country crosswalk is already done and needs no proposal:
`crosswalks/xwalk_ea_api_country.csv` holds all 254 EA API country names paired
to ISO2 as published by EA in `ea_ts_metadata.txt`, at high confidence with
method `ea_published_pair`. Load it, do not re-derive it, and do not name match
against it. Two facts in it matter: `Korea` is KR, not `South_Korea`, so plan
4.5's trap list needs that variant; and EA's own unknown code is `XX`, which must
map to a distinct pseudo code and never to ZZ, because `XX` is EA saying it does
not know while ZZ in our output is a bug.

`xwalk_project_node.csv` for the four split countries, using the EA area
evidence from session 1. **This is gate E, section 0**:
`crosswalks/xwalk_project_node_proposed.csv` from session 2 already resolves
`country_iso2` and `port_role` for every project row and already leaves
`node_id` empty for the four split countries (`method =
unresolved_split_country`); build on it rather than starting over, and use
`crosswalks/xwalk_area_node_proposed.csv` as the evidence source it was
always meant to be. `xwalk_hub_country.csv`. Proposals with confidence flags,
not applied. Same rules as session 1: exact matches only, unresolved left
empty, no fuzzy matching.

`dim_aggregate` per plan 4.4: LT dataset aggregates such as EU, Other Europe
and World are not countries. Create the table with explicit member lists taken
from the LT taxonomy in the pulled metadata. If the pull has not happened,
create the schema and leave the member lists empty, flagged.

**3.8 `docs/session_03_ingestion.md`**

Row counts against every assertion in 3.1, the GTF adjacency violations if any,
what the diff module reports, what is empty pending the pull, and the six
answers or the reason each is still open.

### Do not

- Call the EA API. Write the script, state the command, stop.
- Expand contracts annually. Session 8.
- Model anything: no capacity envelope, no allocation, no balance forecast.
- Fill a missing balance component with an assumption.
- Start session 4.

### Gate

`verify_env` exits 0, `pytest` passes, every row count assertion in 3.1 holds,
the GTF adjacency check passes or lists its violations, and the diff module has
a passing test against a synthetic second vintage.

## 4. Starting prompt for session 2

Paste into a fresh Claude Code session in the project root, in plan mode.
Requires gate A closed: `crosswalks/xwalk_country_alias_proposed.csv` reviewed.

```
Read CLAUDE.md in full. Read docs/sessions_02_03_build_plan.md in full. Read
sections 4.1 to 4.9 of docs/LT_LNG_flows_forecast_plan.md in full, and read
docs/session_01_country_key.md.

Your task is session 2 as specified in section 2 of the sessions 02 and 03
build plan: the geo master. Do not start session 3.

Deliverables are the eleven items in section 2, and nothing else. Several
files they name already exist from session 1 and are interim: replace them,
do not skip them because the path exists.

Two network pulls are permitted, both public unauthenticated data, both through
a pull script that writes a hashed manifest: the Natural Earth Admin 0 snapshot
in 2.1, and the port gazetteer in 2.1b. Everything after them reads the
snapshots. No other network call, no EA API, no MCP.

Hard constraints:
- Do not use geopandas.datasets. The bundled Natural Earth data was removed in
  geopandas 1.0. Fetch from a pinned URL and hash it.
- If the Natural Earth pull fails, report it and stop. Do not substitute a
  different boundary source or resolution.
- Every raw country string resolves through crosswalks/xwalk_country_alias.csv
  and through nothing else. No name matching anywhere. An unresolved value
  fails the build and is listed. It never becomes ZZ.
- Merge crosswalks/xwalk_ea_api_country.csv in as the ea_api_timeseries source
  system. Load it as given, do not re-derive it. Korea is KR. EA's XX maps to a
  distinct pseudo code, never to ZZ.
- data/geo/dim_country.parquet already exists from session 1 and is interim.
  Replace it, do not append and do not skip it. Diff the country list against
  the session 1 version and report any country in one and not the other.
- Where a workbook ISO2 code and the alias resolution disagree, report the
  conflict. Do not resolve it.
- Each of the six traps in plan 4.5 gets its own named test.
- The stored point per country is the pole of inaccessibility, not the
  centroid, and must fall inside its own polygon.
- Nodes are exactly the splits in plan 4.3. Do not add nodes and do not adopt
  EA's finer taxonomy. Report the discrepancy where they differ.
- dim_port_candidate.csv fills coordinates only on an exact case insensitive
  port name match within the same country, from the gazetteer pulled in 2.1b.
  Everything else is unresolved with null coordinates. No fuzzy matching, no
  nearest port in country, no substring matching, and never a country centroid.
  Report the exact match rate.
- Do not compute route distances, do not install or call searoute, and do not
  stub distances with placeholders. Plan checks 4.8.6 and 4.8.7 report as
  skipped with the reason.
- Every DuckDB table declares PRIMARY KEY and its FOREIGN KEYs. A test must
  prove that inserting an unmapped country_iso2 raises. If it does not raise,
  stop and say so.
- Do not create dim_aggregate, do not pull the ArcGIS layer, do not read EA
  series data.
- Manifests end _manifest.json.
- ASCII lower snake case throughout, ISO codes uppercase. Paths via pathlib.
- Fail loudly and name the offender.

The gate: verify_env exits 0, pytest passes, plan 4.8 checks 1 to 5 and 8 to 11
pass, and the foreign key enforcement test passes.

Report the coverage table by source system, the workbook ISO2 conflicts, the
node discrepancy, the port candidate counts, the two skipped checks with their
reason, anything you deviated from and why, and anything you could not resolve.
Report unknowns as unknown.
```

## 5. Starting prompt for session 3

Run after session 2 has passed its gate.

```
Read CLAUDE.md in full. Read docs/sessions_02_03_build_plan.md in full,
section 0 gates C, D and E specifically. Read sections 3.1, 3.4, 5.2 and 6 of
docs/LT_LNG_flows_forecast_plan.md, and read docs/session_01_data_availability.md
and docs/session_02_geo_master.md.

Your task is session 3 as specified in section 3 of the sessions 02 and 03
build plan: ingestion. Do not start session 4.

Deliverables are the nine items in section 3, and nothing else.

Hard constraints:
- No network calls at all. You write scripts/pull_ea_series.py and state the
  commands to run. You do not run it. The operator does.
- Assert the row counts and distributions in 3.1 against plan 3.1. A mismatch
  raises and names the file, the sheet and both numbers.
- Trim workbooks on all-null rows. Never trust the sheet dimension, which
  reports around 3,500 rows because of trailing formatting.
- Portfolio resolves to XP and Multiple to XM. Neither is ever dropped.
- In the GTF file, Liquefied Natural Gas resolves to XL and Not Elsewhere
  Specified to XN. Neither enters dim_country as real.
- Every pipe flow pair must have adjacency or an explicit override row. List
  violations, do not absorb them. Gate D (Kosovo/XK has no dim_country row) is
  why it is currently excluded from dim_country_adjacency; a future GTF
  vintage naming Kosovo should fail this check until gate D closes, not be
  silently absorbed.
- Gate E: crosswalks/xwalk_project_node_proposed.csv from session 2 already
  resolves country_iso2 and port_role per project; build the split-country
  node assignment on top of it using crosswalks/xwalk_area_node_proposed.csv
  as evidence, do not start the crosswalk over.
- Gates C (Gibraltar has an LNG role but no geometry at 1:50m) and D are not
  this session's to resolve; report their status, do not attempt a fix.
- workbook_diff.py must have a passing test against a synthetic second vintage,
  and must report no prior vintage found as a result rather than being skipped.
- If an EA snapshot does not exist yet, build and test the loader and report
  the table as empty pending the pull. Do not fabricate a balance.
- Answer the six questions in session_01_data_availability.md section 6 from
  series metadata only. Where the metadata does not settle one, say so and name
  what would. Do not infer a definition from a series name.
- Crosswalks in 3.7 are proposals with confidence flags. Exact matches only,
  unresolved left empty, no fuzzy matching, not applied.
- Do not expand contracts annually. Do not model anything.
- lt_region is derived from the LT demand series per plan 4.3b and tested to be
  a partition. If it is not a partition, stop and list the offenders. Never fall
  back to the API region field, Natural Earth, or the workbook region columns.
  A multi-valued country is reported with lt_region left null, not resolved.
- Load crosswalks/xwalk_ea_api_country.csv as given. Do not re-derive it and do
  not name match against it. Korea is KR. EA's XX is a distinct pseudo code and
  never ZZ.
- Every numeric value in config, never inline. Manifests end _manifest.json.
- ASCII lower snake case throughout, ISO codes uppercase. Paths via pathlib.

The gate: verify_env exits 0, pytest passes, every row count assertion in 3.1
holds, the GTF adjacency check passes or lists its violations, and the diff test
passes.

Report the row counts against every assertion, the GTF adjacency violations,
what the diff module reports, what is empty pending the pull, the six answers or
the reason each is still open, anything you deviated from and why, and anything
you could not resolve. Report unknowns as unknown.
```

## 6. What comes after

Session 4 is pipeline capacity and projects, `fact_pipe_capacity` and
`config/pipeline_projects.yaml`. Plan section 11 flags it as the stage most
likely to need external data and your judgement, and notes it can run in
parallel with the geo build since it is largely independent.

Two things will be blocking by then, and both are worth starting now rather
than discovering later:

**Port coordinates.** Gate B. Without them there is no `fact_route_distance`,
and without that there is no netback allocation in plan section 7. EA does not
publish coordinates, so this will not resolve itself: it is roughly 120 rows
that either match a public gazetteer exactly or get filled by hand. Session 2
reports the exact match rate, and that number decides which. Worth doing while
session 3 runs, since session 4 onwards assumes it.

**The licence gaps.** `OilX flows`, `US LNG exports by terminal` and
`Australian LNG exports by terminal` came back unlicensed. They are the only
sources that would validate the node splits and supply a realised bilateral
matrix for the backtest in plan 8 check 14. Whether that is a subscription
boundary or a redistribution one changes what session 10 can do at all.
