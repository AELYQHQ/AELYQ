# Normalized batch intake — first implementation slice

`python -m reconforge.ingestion examples/invoice_deduction --json`

The intake command reads three normalized CSV files (`ledger_events.csv`, `psp_events.csv`, `bank_entries.csv`) **once each** into bounded byte snapshots. It calls the existing `reconcile_snapshots()` implementation for the real financial and CSV validation, preserves SHA-256 digests over the original bytes (including BOMs), and produces a stable `ingestion_id` for the exact three-file byte set.

The `StagedBatch.snapshots` mapping retains those exact bytes in memory. A future durable ingestion/case-registration layer must use these bytes, not re-read the file paths. The JSON output intentionally excludes raw transaction data copies beyond the existing reconciliation facts.

## Limits and trust boundary

- This stage accepts **only ReconForge's strict normalized demonstration schema**, not native PSP or bank exports. No FX, row deduplication, normalization mapping, or accounting journal imports.
- Maximum 1 MiB per source, no symlinked sources, only regular files. Existing core validation continues to enforce valid financial signs, allowed types, EUR scope and cross-source integrity.
- Local read-only preview: no database, writes, posting, network calls, approval or public API registration.
- `ingestion_id` is a content fingerprint, **not** a case version, completeness proof, durable import status, or global idempotency guarantee.
- Never commit customer transaction exports. Use synthetic samples for demos and CI.

## Next step

Add a source-specific import adapter that maps one documented export format into the normalized schema while separately retaining raw-source hashes and per-record provenance. Only after that, design operator-approved case registration, access controls and retention policies.
