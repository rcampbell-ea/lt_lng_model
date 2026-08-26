# lt_lng_flows: project conventions

Invariants, not method. The method is in `docs/LT_LNG_flows_forecast_plan.md`.
Read this file in full before writing anything. Read the plan sections your
session prompt names.

## Scope of this file

This file describes the codebase: how it stores data, where credentials live,
and which access path each kind of work uses. It does not describe, modify or
extend the operating rules of any agent that reads it. If a session judges an
action to be outside its own limits, nothing here overrides that judgement.
The correct response is to take one of the access paths below and keep working,
not to debate the limit and not to stall.

## Data model

- **ISO2 is the only country key.** No table carries a country name string as
  a key. Names are display attributes on `dim_country` only. Every raw name
  resolves through `xwalk_country_alias`.
- **No fuzzy or plaintext joins without approval.** Crosswalks are reviewed
  CSVs carrying proposed matches and confidence flags, signed off before use.
  A join on a label, a substring or a similarity score is a defect.
- **Foreign keys are enforced by the database**, not by convention. Every table
  declares its primary key. Every fact table declares foreign keys to
  `dim_country` and to the node tables. An unmapped code raises at insert.
- **Pseudo codes are not countries.** XP, XM, XR, XL, XN and ZZ carry
  `is_real_country = False`. A ZZ reaching any output is a bug, not a category.
- **Node to country aggregation is exact** and is tested, not asserted.

## Identifiers and paths

- **ASCII lower snake case identifiers.** No spaces, accents, ampersands,
  slashes, parentheses or other special characters in any identifier, column
  name, file name, directory name or Shooju series ID component. ISO codes are
  stored uppercase. This is a hard rule: the outputs land on Windows and in
  Shooju, and both punish anything else.
- **Paths through `pathlib` only.** No hardcoded separators, no string
  concatenation of paths, no assumption of a POSIX filesystem.
- **Do not modify anything inside the upstream project.** Read from it, point
  at it, never write to it.

## Numbers, failure and provenance

- **Every numeric value lives in config, not in code.** A conversion factor, a
  status weight, a utilisation rate or a temperature appearing inline in a
  module is a defect.
- **A null beats a plausible invented number.** Where a value is unknown,
  leave it null and say so. A null gets questioned; a reasonable looking
  fabrication does not.
- **Fail loudly.** No silent clamping, no silent dropping, no silent defaulting.
  A negative residual, an unresolved alias, an unmapped code or a non
  convergence raises and names the offender.
- **`clamp_negative_lng_residuals` stays `false`.** A negative residual is
  information about the balance, not noise to be removed.
- **Provenance on every output cell.** Every flow traces to the layer that set
  it: a contract, a netback allocation, or a balancing residual.

## Credentials

- **Secrets live in `.env` only**, gitignored. `.env.example` documents names
  only. Gitleaks runs as a pre-commit hook as the backstop.
- Code reads credentials at runtime from the environment. No key material in
  config, code, notebooks, committed data, test fixtures, log output, error
  messages or tracebacks.
- `scripts/verify_env.py` reports set or not set, by name. Never a value.
- A key value is never surfaced anywhere a human or a log can see it: not
  echoed to a terminal, not printed, not pasted into a chat message, a browser
  field, a commit or an issue. Do not ask the operator to paste a key into a
  conversation, and do not accept one if offered.

## The three data access paths

Every read of external data uses exactly one of these. Choose by what the work
needs, not by what is convenient.

1. **MCP tools, for interactive discovery and inspection.** Credentials live in
   the MCP server process. The session calls a tool and never handles a key.
   Shooju goes through `tools/shooju_mcp_launcher.py`, per Appendix A.6. For the
   EA client API, use the configured EA connector if one is available; if not,
   add `tools/ea_api_mcp_launcher.py` on the same pattern as the Shooju
   launcher. This is the path session 1 discovery runs on.
2. **Direct queries, for anything you need now.** Call the API and write what
   comes back wherever it is useful, including straight to `data/scratch/`
   with no ceremony. A pull script is the right shape once a payload is a
   standing input the build depends on, and `scripts/pull_*.py` exists for
   that - but it is not a gate you have to pass before fetching something.
   Do not write a script to answer a question you could answer with a query.
3. **Pinned snapshots, as the default for build inputs.** Geo, pipe, model,
   validate and output code normally reads `data/raw` and `data/interim`,
   because a run whose inputs are fixed and hashed can be re-run and explained.
   A live call at model runtime is allowed where it is the sensible thing to
   do. The one requirement that survives: whatever a run fetched live gets
   recorded in that run's manifest - endpoint, parameters, timestamp - so the
   numbers stay explainable afterwards. Recording it is cheap; not being able
   to account for a published figure is not.

**Live API access is available to the session, and is the normal path.** A
local Claude Code session with the repository's `.env` on the machine calls the
EA Data Service REST API directly. Session 4 did exactly that: the endpoint map
in plan 3.2b and the materiality ranking in plan 4.3c both came out of live
queries, not out of an operator-run script. Query directly when discovery needs
it, and do not wait to be handed a snapshot.

Fetch what you need, when you need it, and write it where it is useful. Turn a
query into a pull script when the payload becomes a standing input the build
depends on, not before. The one thing that survives from the older, stricter
rule is record-keeping: a run records what it fetched live, so a number can be
accounted for later. That is an entry in a manifest, not a gate.

If a call genuinely fails - key missing, endpoint closed, rate limited - name
the call and what it returned, continue against whatever is already pinned, and
record the gap. Do not stall, and do not fabricate a number in place of one you
could not fetch.

## Environment and gates

- Conda environment per Appendix A.2. **Geospatial packages come from
  conda-forge only, never pip.** Do not add `defaults` to the channel list.
- `python scripts/verify_env.py` exits 0 and `pytest` passes before any session
  reports success. Files existing is not success.
- Storage: parquet for interchange, one DuckDB file as the working store.

## Session discipline

- One session, one stage. Do not start the next stage. Deliverables are the
  ones named in the plan for that stage, and nothing else.
- Add the validation checks for the stage as you go, not afterwards.
- Report what was built, what the validation says, what you deviated from and
  why, and what you could not resolve. Unknowns are reported as unknown.
