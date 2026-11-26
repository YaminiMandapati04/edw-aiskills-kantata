# Kantata EDW AI Skills

Claude skills for Kantata that answer finance, ARR and go-to-market questions, and build reporting deliverables, from the governed Snowflake semantic views in `PROD_DB.SEMANTIC_VIEWS`.

Each skill is a self-contained folder with a `SKILL.md` (the instructions Claude follows), plus the scripts, references and assets it needs. Deterministic scripts compute every number; the model runs the queries, hands the results to the scripts and relays the output. It never types or calculates a figure itself.

## Skills

| Skill | Semantic view | What it does |
|---|---|---|
| [semantic-data-analyst-arr](semantic-data-analyst-arr/SKILL.md) | `ARR_ANALYTICS` (Maxio) | Answers ARR and retention questions (beginning and ending ARR, new, upsell, downsell, churn, NDR, GDR, customer counts), explains movements, drills to customers, and produces charts, Excel and HTML. |
| [financial-variance-analysis](financial-variance-analysis/SKILL.md) | `FINANCE_ANALYTICS` (NetSuite GL) | Answers finance questions (P&L, balance sheet, cash flow, budget variance, GL drill-down) and builds the three-tab Finance diagnostic dashboard (Summary, Drivers, Outlook). |
| [pipeline-and-booking-risk](pipeline-and-booking-risk/SKILL.md) | `GTM_ANALYTICS` (Salesforce) | Answers bookings and pipeline questions (win rate, weighted pipeline, at-risk deals) and builds the three-tab GTM dashboard (Pipeline, Bookings, Outlook). |
| [chronograph-generator](chronograph-generator/SKILL.md) | All three views | Builds the Accel-KKR CFO Chronograph workbook: 24 months of actuals, reconciled to the views and checked to open in Excel without repair. Does nothing else. |

## Repository layout

```
<skill>/
  SKILL.md        Entry point: trigger description, workflow, rules
  references/     Query playbooks, guardrails, output formats, semantic view notes
  scripts/        Deterministic Python (and PowerShell) tooling, plus self-tests
  config/         Scope settings (scope.json): subsidiary exclusions, fiscal year, roll-up keys
  assets/         Templates, sample data, semantic view definitions
  artifacts/      HTML/CSS/JS dashboard templates (finance and GTM skills)
  specialists/    Role instructions for the AI review steps (driver-review, readout)
```

Not every skill has every folder. Runtime folders `work/` (intermediate extracts) and `outputs/` (deliverables) are created during a run and are git-ignored.

## Outputs

Each run builds its deliverables locally in `outputs/` (git-ignored), named for the as-of month where relevant. Intermediate extracts go to `work/`.

## Requirements

- Python 3.12 or later
- `pip install -r requirements.txt` (openpyxl, matplotlib)
- A Snowflake connection to `PROD_DB.SEMANTIC_VIEWS` (via MCP in the Claude session; the skills run the queries and hand the results to the scripts). The chronograph needs a live connection and has no sample mode.
- Chronograph only: Windows with desktop Excel for the open-in-Excel check (`excel_open_check.ps1`, `excel_finalize.ps1`).

## Using a skill

Install or point Claude at the skill folder, then ask in plain English, for example:

- "What is our ARR, and why did NDR drop last quarter?"
- "Why did EBITDA miss budget?" / "Run the month-end finance review"
- "Run this month's GTM dashboard"
- "Refresh the Kantata CFO Chronograph for October"

Each `SKILL.md` description lists its triggers and what it does not cover.

## Local mode and self-tests

The ARR, finance and GTM skills include a local mode (`references/local-mode.md`) that runs on synthetic sample data without Snowflake, for example `scripts/run_local_demo.py` and `scripts/make_sample_data.py`. Sample output is for checking the tooling only, never for reporting.

Self-tests, run from the skill's folder:

```
python financial-variance-analysis/scripts/test_finance_pipeline.py
python chronograph-generator/scripts/test_chronograph.py
```

## Safety rules shared by all skills

- Every SQL statement passes `scripts/sql_guard.py` (read-only, governed views only) before it runs.
- Figures must reconcile to the governed roll-ups; scripts refuse on a gap.
- See each skill's `references/guardrails.md` for the full list.

## Contributing

1. Change one skill at a time and keep its `SKILL.md` description accurate, since it drives when Claude uses the skill.
2. Run the skill's self-test before committing.
3. Do not commit `work/`, `outputs/`, `__pycache__/` or credentials.
4. `sql_guard.py` is duplicated in each skill so folders stay self-contained. Apply guard changes to all copies.
