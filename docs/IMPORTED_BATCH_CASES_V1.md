# Imported Batches → Investigable Cases (synthetic local prototype)

**Scope:** Register *synthetic test data only* as an immutable case that the
existing deterministic reports, read-only API, MCP server and bounded offline
investigator can inspect. No remote upload, payment action, authorization,
provider completeness claim, or production customer data intake exists.

## Safety and trust boundary

- Operator-only local CLI registration; API and MCP remain read-only.
- Source inputs must already be in the strict three-source normalized CSV schema.
  A native Adyen report must first be converted by the existing adapter.
- The registrar invokes `stage_directory` once to capture source bytes, then
  writes those captured bytes to a staging directory under `.aelyq/imported_cases`.
  It validates the persisted snapshot using the current CaseStore before renaming
  it into its final content-addressed location.
- Case IDs are `case_import_<full SHA-256 ingestion digest>`: deterministic,
  stable, and within the existing CaseId 80-character limit.
- Manifest hashes are verified each time imported cases are discovered.
  Corrupt cases cause the whole catalogue load to fail closed.
- A process's CaseStore is an immutable snapshot. Restart the HTTP/MCP server
  after new registration; no live reload of case/evidence identity.
- The existing `data_classification='synthetic'` contract is retained; do not
  register sensitive or real merchant data with this prototype. An explicit
  CLI flag enforces conscious synthetic-only use, *not* an automated privacy
  inspection of the actual file contents.
- Both the `.aelyq` registry and provider original data must be excluded from
  public Git commits; never commit actual transaction statements or secrets.
- Snapshot identity does not establish external completeness, authorization,
  or that unsupported provider journal types were correctly mapped.

## Operator workflow

```bash
# On a clean feature branch, using the bundled synthetic example:
python -m reconforge.imported_cases register \
  examples/imported_case_demo --synthetic-test-data

python -m reconforge.imported_cases list

# Start read-only imported-case HTTP on loopback in a separate terminal:
uvicorn reconforge.imported_api:app --host 127.0.0.1 --port 8000

# Read all available cases (examples plus imported):
curl http://127.0.0.1:8000/cases

# Use the case_id returned by the registrar:
python -m reconforge.imported_investigation_demo \
  --case-id case_import_<64-digit-digest> --json
```

The investigator uses the **existing bounded host** and a separate imported
read-only MCP server, with exactly two allowlisted MCP entrypoint modules.
`run_mcp_investigation(case_id)` keeps its original behavior; the new optional
`server_module` keyword selects the imported catalogue for the offline CLI.
No LLM provider calls are made by the default scripted driver.

## Out of scope

- Real merchant data classification, PII redaction, access controls, retention,
  deletion, authn/authz and tenant isolation.
- Browser upload, persistent database, append-only audit trail for operations,
  cryptographic authentication of the original provider report.
- Mapping native Adyen event references to an internal merchant ledger.
- Authoritative approval, funds movement or writeback.

## Architecture next

First complete authenticated, correctly classified local data ingestion and
retention controls, then evaluate canonical transaction identity mapping. Do
not silently change the evidence contracts to accommodate arbitrary uploads.
