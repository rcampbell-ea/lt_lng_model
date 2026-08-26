# Session 3: ingestion

Deliverable for session 3 of `docs/sessions_02_03_build_plan.md` section 3, country level only per the Prototype phasing decision.

## Build log

- 3.1 row counts: liquefaction 617 rows / 39 countries (expected 617/39); regas 615 rows / 78 countries (expected 615/78); contracts 1074 rows, header row 3 (expected 1074, header row 3). PASS
- 3.1 contract distributions PASS: status={'Current': 512, 'Future': 356, 'Expired': 206}, delivery_type={'DES': 525, 'FOB': 474, 'DES/FOB': 48, '-': 26, 'Undeclared': 1}, export_country distinct=31 (Portfolio=204), import_country distinct=61 (Multiple=305)
- 3.1 country resolution: Portfolio -> XP (204 rows), Multiple -> XM (305 rows), neither dropped
- 3.2 workbook_diff: liquefaction prior_vintage_found=False, regas prior_vintage_found=False, contracts prior_vintage_found=False -- only the 202608 vintage is pinned on disk this session, so all three report 'no prior vintage found' as a structured result rather than being skipped (build plan 3.2). The synthetic-second-vintage test (tests/test_workbook_diff.py) exercises the comparison logic itself.
- 3.3 fact_pipe_flow_hist: 2581 (origin, destination, year) rows from 184 border points (148 distinct corridors)
- 3.3 GTF adjacency check: PASS, every real-country corridor has adjacency or an override
- 3.4/3.4b: this session does not call the EA API or the OilX API. Operator commands:
-   python scripts/pull_ea_series.py --mapping-id 297 --vintage 202608
-   python scripts/pull_ea_series.py --mapping-id 314 --vintage 202608
-   python scripts/pull_ea_series.py --mapping-id 553 --vintage 202608
-   python scripts/pull_ea_series.py --mapping-id 545 --vintage 202608
-   python scripts/pull_ea_series.py --mapping-id 300 --vintage 202608
-   python scripts/pull_ea_series.py --mapping-id 5 --vintage 202608
-   python scripts/pull_ea_series.py --mapping-id 6 --vintage 202608
-   python scripts/pull_oilx_flows.py --vintage 202608 --start-date 2023-01-01 --end-date 2026-12-31 --import-basis import
- 3.4c fact_lng_flow_baseline: EMPTY, pending the OilX pull (scripts/pull_oilx_flows.py has not been run). Loader built and tested against a fixture (tests/test_oilx_flows.py).
- 3.5 fact_gas_balance: EMPTY, pending the EA series pull (scripts/pull_ea_series.py has not been run for any mapping). Loader built and tested against a fixture (tests/test_ea_series.py).
- 3.4d implied-pipe diagnostic: EMPTY, pending pull(s) -- inputs_empty={'gas_balance': True, 'lng_flow_baseline': True}. Module ran and reports this explicitly rather than skipping (build plan 3.4d / session 3 gate).
- 3.6: 8 open questions from the availability doc, answered/reported open per docs/session_03_definitions.md
- 3.6b lt_region: NOT DERIVABLE this session -- no EA series snapshot with a 'region' field is available yet; mappings 314 and 550-560 have not been pulled (scripts/pull_ea_series.py has not been run for them this session)
- 3.7 xwalk_ea_api_country.csv: loaded as given (254 rows, method ea_published_pair), not re-derived, not name matched.
- 3.7 Gate E: deferred per the Prototype phasing decision. crosswalks/xwalk_project_node_proposed.csv left exactly as session 2 wrote it; not read or modified by this session.
- 3.7 crosswalks/xwalk_hub_country.csv: written with header only, zero rows. No LT price series (mapping 300) has been pulled, so there is no evidence on disk to propose a hub-to-importer mapping from; a hand-typed mapping from general knowledge would be exactly the unreviewed judgement CLAUDE.md's 'no fuzzy or plaintext joins without approval' and 'null beats a plausible invented number' rules exist to keep out.
- 3.7 dim_aggregate: schema only, zero rows -- no LT taxonomy pull has landed. Not the same thing as the (separate, later, unresolved) Europe demand-block node.
- DuckDB store: session 2 tables (dim_country, dim_country_adjacency, dim_supply_node, dim_demand_node, xwalk_country_alias) reloaded unchanged from their own parquet/CSV outputs before session 3's tables are added
- DuckDB store: fact_liq_project, fact_regas_project, fact_lng_contract, fact_pipe_flow_hist, fact_gas_balance, fact_lng_flow_baseline, dim_aggregate, dim_country_region_tag loaded with PK/FK declared
- Wrote data/interim/session_03_ingestion_manifest.json

## GTF adjacency violations

None. Every real-country corridor in `fact_pipe_flow_hist` has geometric adjacency or an explicit override row in `dim_country_adjacency` -- expected, since session 2's override file was itself built as evidence from this same GTF file (`adjacency.py`).

## Implied-pipe diagnostic

EMPTY. `inputs_empty` = {'gas_balance': True, 'lng_flow_baseline': True}. The diagnostic module ran and reports this explicitly, per the session 3 gate ('empty-pending-pull is an acceptable report, a silent skip is not').
