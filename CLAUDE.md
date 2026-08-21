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
2. **Pull scripts, for anything that lands on disk.** `scripts/pull_*.py`
   write the raw response plus a manifest recording endpoint, parameters,
   timestamp and content hash to `data/raw/<source>/<vintage>/`. The script is
   the reproducible unit. Whoever runs it, operator or session, the artefact on
   disk is the contract.
3. **Pinned snapshots, for everything else.** All geo, pipe, model, validate
   and output code reads only `data/raw` and `data/interim`. No live external
   call at model runtime, ever. Reruns are reproducible because the inputs are
   fixed and hashed.

**When a session cannot make an authenticated call itself.** It happens, and it
is not a blocker. Do not stall, do not ask for the key, do not argue with the
constraint, and do not add a plan doc paragraph attempting to lift it. Do this
instead: use path 1 if a tool exists; otherwise write or extend the pull script
under path 2, state the exact command to run, and continue against the snapshot
once it lands. Record in the session note which path was used and what could not
be reached, so the gap is visible rather than inferred later.

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
