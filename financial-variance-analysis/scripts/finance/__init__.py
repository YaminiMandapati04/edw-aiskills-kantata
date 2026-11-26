"""Deterministic finance diagnostic engine for the semantic-data-analyst skill.

Python determines what is true about the numbers (this package), the model
interprets what those truths mean (diagnosis.json, validated by
`diagnosis.py`), and the renderer displays both without computing anything
economic. Contract of record: references/finance-analysis.md,
references/diagnosis.md and references/dashboard-contract.md.
"""
CONTRACT_VERSION = "sda.finance-analysis/1.5.0"
DIAGNOSIS_CONTRACT = "sda.finance-diagnosis/1.2.0"
RENDERER_VERSION = "1.10.6"
