# Session 3: definitions

Deliverable for session 3, build plan 3.6: answers to the open questions in `docs/session_01_data_availability.md` section 6, from series metadata only. That section carries eight items as of this session (not six -- read fresh per the session 3 starting prompt), the first four resolving from series metadata and the last four needing one page of the flows endpoint; none of the metadata pulls this session needs has landed on disk (EA series snapshots found: ['C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_297\\response.json', 'C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_300\\response.json', 'C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_314\\response.json', 'C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_5\\response.json', 'C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_545\\response.json', 'C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_553\\response.json', 'C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\ea_api\\202608\\mapping_6\\response.json']; OilX snapshots found: ['C:\\Users\\robert.campbell\\PycharmProjects\\lt_lng_flows\\data\\raw\\oilx\\202608\\flows_lng\\response.json']), so every question needing live series metadata is reported open here, named, rather than guessed.

## Question 1: Does mapping 297 include net pipeline trade by country, or supply only?

**Still open.**

**Why:** Needs mapping 297's own series metadata (aspect/aspect_subtype per dataset), which requires the mapping_id=297 pull. Not resolvable from the mappings catalogue alone (data/raw/ea_api/202608/ea_api_mappings.txt), which carries no aspect field per dataset_id -- only mapping_id, name, dataset_ids, licensed, request_string.

## Question 2: Is demand in 314 and 550-560 gross inland or final consumption, and do own use and flaring sit inside it or separately?

**Still open.**

**Why:** Needs series-level aspect/aspect_subtype/category_subtype metadata from the mapping_id=314 and 550-560 pulls.

## Question 3: Is production in 297 marketed or gross?

**Still open.**

**Why:** Same as question 1: needs the mapping_id=297 series metadata.

## Question 4: Are LNG imports in 545 gross or net of reloads?

**Still open.**

**Why:** Needs the mapping_id=545 series metadata (aspect/aspect_subtype).

## Question 5: What is mapping 614, 'Long term trial data'?

**Still open.**

**Why:** Session 1 already flagged this as provenance-unknown and 'do not use until EA confirms what it is'. No series metadata pull resolves an undocumented mapping's purpose; this needs a direct question to EA, not a data pull.

## Question 6: What is the volume field in the flows response, and in what unit?

**Answer.** Partially answered from plan 3.2c's documented response shape (not from a live call, which this session does not make): the flows endpoint returns QuantityKT, QuantityCBM and QuantityMMBtu, i.e. mass, liquid volume and energy, not a direct bcm-of-gas figure. Which of these to use, and the exact conversion to bcm (whether the decisions register's 1.37 Mt-to-bcm factor applies as-is), is still open.

**Why:** The exact conversion is not confirmed against a live response; oilx_flows.py deliberately leaves fact_lng_flow_baseline.bcm null and preserves the raw quantity fields rather than applying an unconfirmed factor.

## Question 7: Sub-country taxonomy: is the US taxonomy confirmed as PADD, what are the Canadian/Chinese/Chilean taxonomies, and does an LNG-specific sub-country or terminal breakdown exist anywhere in the API?

**Still open.**

**Why:** Out of scope this session per the Prototype phasing decision: gate E (node splits) is deferred, and this question only matters for resolving gate E's sub-national node assignment.

## Question 8: The exact response field names, for the config field map in 2.3 rule 4.

**Answer.** Partially answered from plan 3.2c: cargo type ID 211100 for LNG, subtypes 211101 (Rich)/211102 (Lean); flow record fields OriginCountryCode, DestinationCountryCode, GradeID, Import, QuantityKT/QuantityCBM/QuantityMMBtu, ReferenceDate, Deleted, all mapped to snake_case in oilx_flows.py's _FIELD_MAP.

**Why:** Not confirmed against a live response this session; the field map is built from the documented shape and should be checked against the first real pull.

## Sign convention and component naming for fact_gas_balance

`component` is stored exactly as the EA API's own `aspect` metadata field reports it (`supply`, `demand`, `production`, `net_imports`, ...), not remapped onto plan 5.2's identity term names (`domestic_production`, `pipe_imports`, ...). That remapping requires questions 1 and 3 above to be settled first; forcing it now would silently pick a side of an open question. Values are stored exactly as the API returns them, with no sign flipped at ingestion time -- see `ea_series.py`.
