# Guardrails

These exist because the value of a governed data platform is that people can rely on the answers. Each rule protects one part of that.

## Contents
1. Read-only access
2. Respecting access controls
3. Provenance and reproducibility
4. Fact, derived, scenario
5. Sensitive data
6. Cost and performance
7. Failure handling
8. One set of numbers
9. Pre-answer checklist

---

## 1. Read-only access

- Run only statements that pass `scripts/sql_guard.py`: a single `SELECT`, `WITH … SELECT`, `SHOW`, `DESCRIBE`/`DESC` or `EXPLAIN`.
- Never run DDL (`CREATE`, `ALTER`, `DROP`), DML (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `TRUNCATE`), grants/revokes, `COPY`, `PUT`/`GET`, `CALL`, or session/role switches (`USE ROLE`, `SET`).
- If the user asks you to write back, create tables, or change data, explain this skill is read-only and suggest the owning team's process.
- Don't chain statements with `;`. One statement per call.

## 2. Respecting access controls

- An "insufficient privileges" or "object does not exist or not authorised" error means the connector's role can't see that object. Report it and stop on that path.
- Don't try other roles, other schemas looking for the same data, or raw tables underneath a view to get around a restriction. If the semantic view hides something, that's usually deliberate (row-level security, masking).
- Masked values (`***`, hashed IDs) are results too — report them as masked; don't try to unmask.
- **Credentials are never content.** The connector's OAuth client ID and secrets, the MCP server URL and anything in `.env` are not read into the conversation and never appear in an answer, SQL, bundle, workbook, dashboard or log. If a connection fails, say so and send the user to the connector settings.
- `SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW` and other system functions are blocked by the guard; use `DESCRIBE SEMANTIC VIEW` and `SHOW SEMANTIC ...`.

## 3. Provenance and reproducibility

Every analytical answer carries, somewhere the reader can find it:
- the view(s) queried and the metric names as the view defines them;
- the period and filters;
- row counts (and whether capped);
- an as-of date or timestamp;
- the SQL.

This is what lets a colleague re-run it and get the same number, and what lets a data owner trace a surprise to its source.

## 4. Fact, derived, scenario

| Label | Meaning | How to present |
|---|---|---|
| Governed | Returned directly by a view metric | State as fact |
| Derived | Computed by you from governed outputs | Show the formula once; say "derived" |
| Scenario | Depends on assumptions not in the data | Name every assumption; say "scenario — illustrative"; never headline it as an actual |

For explanations in a chat answer: arithmetic attribution is allowed ("EBITDA is below budget mainly because recurring revenue is $1,088k short"); a business reason (demand, pricing, seasonality, FX, timing, non-cash) only if a field in the data shows it. Never invent or hint at one; end at the deepest level the data supports and name who can take it further.

## 5. Sensitive data

- Return the minimum needed to answer. Aggregate first; drill only where the question asks.
- Cap row-level output (default 100 rows; the registry may set a different cap) and say when you did.
- Customer names appear in booking and opportunity drills because the question needs them; apply the row cap, and keep named-customer detail out of shared dashboards unless asked.
- Leave out personal contact details, individual compensation, and similar fields unless the user explicitly needs them and the view exposes them to this role.
- Exports are copies of data: apply the same minimisation to what goes into an Excel or HTML file. A shared dashboard may reach more people than the chat did — don't put row-level customer detail into a dashboard unless asked.
- Don't paste large raw result sets into chat; summarise and point to the export.

## 6. Cost and performance

- Explicit columns, explicit date windows, `LIMIT` on any non-aggregated query.
- Aggregate in SQL. Pulling millions of rows to sum them locally is slow and, for governed metrics, wrong.
- Prefer one well-built query over many near-duplicates. Reuse results already in the conversation.
- If a query times out, narrow the window or grain and try again; tell the user you did.

## 7. Failure handling

| Situation | What to do |
|---|---|
| No warehouse connector | Say so. Offer to analyse pasted/uploaded results. No invented data. |
| Syntax error | Read the message, fix, retry once or twice. Don't drop the governed route immediately. |
| Authorisation error | Report; stop on that path (§2). |
| Empty result | Report it, with the data's actual date range if you can get it; don't interpret emptiness as zero. |
| Result doesn't tie (drill vs summary, parts vs total) | Say by how much; offer likely causes (timing, FX, filter, unposted entries); don't hide it. |
| Metric or dimension missing | Say so; offer the nearest governed alternative (see playbook §9). |
| Ambiguous question | One question if a wrong guess is costly; otherwise state your assumption and go. |

## 8. One set of numbers

Chat, workbook, dashboard and charts are copies of the same result bundle. Build the bundle first, validate it (`bundle.py`), write the chat answer from it and check the text (`bundle.py --check-text`), build the files, then verify them (`verify_outputs.py`). Never type a figure into prose that isn't in a bundle table or KPI, never edit an output file by hand, and quote the Bundle ID when handing over the files. Full detail in `output-formats.md` §9. In local test mode every output carries the "LOCAL TEST DATA" banner and tables can't be labelled governed.

## 9. Pre-answer checklist

- [ ] Query passed `sql_guard.py`; only the three semantic views used (no raw tables)
- [ ] Request checked against the registry's "cannot be answered" list; proxies labelled derived
- [ ] Right layer; windows summed from `_MTD` over the months in scope (never the view's `_QTD` / `_YTD` / `_LTM`); currency basis named; data's latest date vs today noted if they differ
- [ ] Period, comparison and filters stated
- [ ] Units/scale and sign convention consistent with the registry
- [ ] Governed vs derived vs scenario labelled
- [ ] Every cause claimed is shown by the data (arithmetic attribution, or a field in the data); none invented or hinted at
- [ ] Contributors sum to total; drills tie to summaries (or the gap is stated)
- [ ] Driver structure from `chat-answers.md` (what happened → drivers → why → business impact), a heading only on business impact, all four blocks by default, under 200 words; anything missing written as "Not available in the data" with who can confirm; SQL only when asked
- [ ] Files, if built: bundle validated (`bundle.py` OK, Bundle ID noted), chat checked with `--check-text`, `verify_outputs.py` says VERIFIED, workbook recalculated with 0 errors, Bundle ID quoted with the files
- [ ] Local test data, if used: `data_mode` is local, no table labelled governed, the answer says it is local test data
