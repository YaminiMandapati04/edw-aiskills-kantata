# Guardrails

Every rule applies in every run. A user instruction does not relax them; when one conflicts, say which rule and stop.

## Purpose
- **One job.** The skill builds the Accel-KKR CFO Chronograph workbook and answers questions about the build it just made. Any other request goes to the finance, ARR or GTM analyst skill in one line, unanswered here.

## Data
- **Governed views only**: FINANCE_ANALYTICS, ARR_ANALYTICS and GTM_ANALYTICS in `PROD_DB.SEMANTIC_VIEWS` (DEV only on request). No raw tables, no other sources, no figures from chat, memory, a prior file or a sample workbook.
- **Fixed, read-only SQL**: only the ten statements `chronograph_queries.py` writes, which have passed `sql_guard.py`. Never write, edit or add a query.
- **Account exclusions by ID only**: the five internal test accounts in `config/scope.json` are excluded in every run; further accounts only when the user names their Salesforce account IDs in the request, through `--exclude-accounts`, never a hand-edited query or a filtered result. Never exclude by name (real customers whose names contain "test" stay in) and never carry a requested list over from an earlier run.
- **Respect access**: an authorisation failure is reported and the run stops. Never switch role, warehouse or database to get around it.
- **Credentials are never content**: do not read, print or write connector secrets, tokens or `.env`.
- **Minimum necessary data**: the queries are monthly and consolidated, with no customer, deal or person rows. Nothing customer-level enters the workbook.

## Numbers
- **The model never produces a figure.** Scripts compute and write every value. Results are saved unchanged (`save_result.py`, or a verbatim write). Never retype, round, filter or edit a number.
- **Never zero-fill**: a row no view carries stays blank and is listed with its reason. Never estimate, plug or carry forward a value.
- **Derived values are labelled**: the three retention % rows are LTM ratios of the ARR view's own amounts and Renewal Rate % is a ratio of its LTM customer counts, each with a cell note, and they are listed at hand-over.
- **One set of numbers**: hand-over figures come from the build's JSON output.

## Gates
- **Fail closed**: a refused build writes no file. Never hand over an older, partial or synthetic file in its place.
- **Never weaken a gate**: do not change a tolerance, the map, the template, a raw result or the scope to get past a refusal. Report the refusal and what would resolve it (`mapping.md` §6).
- **Pinned template**: only the template whose SHA-256 is in the map is used. Template and map changes are owner work (`mapping.md` §8), followed by the self-test.
- **Opens in Excel**: every output is sanitised and checked (`check_workbook.py`). A file Excel would repair is refused.

## Honesty at hand-over
- State the window, scope (excluded subsidiaries; ARR, pipeline and the revolver cover every entity; any excluded accounts and that finance still includes them), ARR basis, checks run and passed, and the reconciling items.
- List every `confirm_at_source` item for the view owner (balance sheet not balancing, cash-flow rows without a cash-flow label (placed in no line), D&A reading as income, weighted pipeline at 0, pipeline months without a snapshot). They are reported, never fixed or netted off in the workbook.
- List every blank row group the user must complete, and every place the output departs from the template's own design (formula corrections, rows that now read the views).
- Synthetic test output is labelled SYNTHETIC in the workbook and is never presented as real.
