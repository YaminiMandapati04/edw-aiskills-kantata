"""Deterministic GTM diagnostic engine for the semantic-data-analyst-gtm skill.

Python determines what is true about the numbers (this package), the model
interprets what those truths mean (diagnosis.json, admitted by diagnosis.py), and the
renderer displays both without computing anything economic. Contract of record:
references/dashboard-contract.md and references/diagnosis.md.

`live.py` loads governed GTM_ANALYTICS extracts and `engine.py` also reads a local
workbook laid out as in references/local-mode.md; both feed the same engine.
`render.py` assembles the page; `diagnosis.py` is the AI-review admission gate.
"""
CONTRACT_VERSION = "sda.gtm-analysis/2.0.0"
DIAGNOSIS_CONTRACT = "sda.gtm-diagnosis/1.0.0"
RENDERER_VERSION = "2.0.0"
