# Synthetic imported case demo

Only test values; not derived from a provider or real customer. Both financial
comparison residuals are deliberately nonzero: ledger EUR 100, provider EUR 90,
bank EUR 85. Register using `python -m reconforge.imported_cases register
examples/imported_case_demo --synthetic-test-data`. The ingestion fingerprint
becomes a stable case ID and the imported case can be examined by the existing
report, API, MCP and offline investigator flows.
