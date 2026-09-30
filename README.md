# AELYQ

[![Tests](https://github.com/SamanGharagozlou/reconforge/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/SamanGharagozlou/reconforge/actions/workflows/tests.yml)

**Evidence-grounded payment reconciliation with bounded AI investigation.**

AELYQ is an engineering prototype for investigating settlement discrepancies across internal ledger, payment-provider, and bank records.

The core design principle is simple: **financial truth stays deterministic; models remain bounded.**

Financial calculations, evidence identity, case scope, and permissions are controlled by application code. An optional LLM can inspect permitted evidence and prioritize a fixed investigation playbook, but it cannot change verified amounts or execute financial actions.

> **main · 135 offline tests · FastAPI · 4 read-only MCP tools · Claude + OpenAI adapters**

## Why AELYQ

Many AI demos let the model calculate, infer, and act at the same time.

AELYQ deliberately separates those responsibilities:

- **Deterministic financial core** — authoritative amounts use integer EUR cents.
- **Traceable evidence** — findings link to captured source rows and SHA-256-bound snapshots.
- **Version-bound context** — evidence retrieval is tied to the exact case version.
- **Read-only MCP tools** — current tools inspect data; they cannot mutate financial state.
- **Bounded model execution** — the host controls case scope, tool access, evidence budgets, and final validation.
- **Explicit failure handling** — invalid model proposals are rejected rather than silently accepted.
- **Provider-independent model layer** — the same bounded investigator supports Claude, OpenAI, and an offline scripted driver.

## Architecture

```mermaid
flowchart LR
    A["Ledger / Provider / Bank snapshots"] --> B["Deterministic reconciliation"]
    B --> C["Versioned case + evidence"]
    C --> D["Verified investigation report"]
    D --> E["Bounded investigator host"]
    C --> F["Read-only MCP tools"]
    F --> E
    G["Claude / OpenAI / scripted model"] <--> E
    E --> H["Host-validated proposal"]
```

> **Naming note:** AELYQ is the public product name. The Python package and CLI module remain `reconforge` for compatibility during the rebrand.

## Run the first example

Use Python 3.12 or newer from the extracted `reconforge-starter` directory.
The original financial demo still uses only the Python standard library:

```bash
python3 -m reconforge.demo
```

The supplied fictional merchant has the following settlement totals:

| Source | EUR |
| --- | ---: |
| Internal ledger | 115,300.00 |
| Payment-provider components | 115,050.00 |
| Bank payout | 115,050.00 |
| Ledger minus provider | **250.00** |
| Provider minus bank | **0.00** |

The provider file includes `evt_invoice_001`, a EUR -250.00 invoice deduction.
The ledger file omits that event. The program reports the difference and source
row so a person can verify it. This is deterministic set comparison on canonical
fixture IDs, not an AI investigation or a real-provider matching integration.

For machine-readable output:

```bash
python3 -m reconforge.demo --json
```

For another directory using the same strict demonstration schema:

```bash
python3 -m reconforge.demo --data-dir examples/invoice_deduction --json
```

## Compare three different discrepancies

| Case ID | Ledger minus provider | Provider minus bank | Interpretation |
| --- | ---: | ---: | --- |
| `case_invoice_deduction_001` | EUR 250.00 | EUR 0.00 | The supplied ledger omits an invoice deduction |
| `case_bank_shortfall_001` | EUR 0.00 | EUR 150.00 | The bank payout is below the provider total; cause undetermined |
| `case_settlement_timing_001` | EUR 0.00 | EUR 10,000.00 | A late-dated capture makes timing/reporting plausible, but the cause remains undetermined |

The second case has matching ledger and provider components totalling EUR
82,000.00, but a supplied bank payout of EUR 81,850.00. It requires review even
though no ledger/provider events differ. The amounts do not establish a cause
or justify a correcting entry. Run its financial comparison without dependencies:

```bash
python3 -m reconforge.demo --data-dir examples/bank_shortfall --json
```

### Settlement timing scenario

The third bundled case has matching ledger and provider records totalling
EUR 69,400.00 and a supplied bank payout of EUR 59,400.00. One EUR 10,000.00
capture is timestamped after the supplied payout. AELYQ treats that as
context for an unverified timing/reporting hypothesis, not as proof of cause:

```bash
python3 -m reconforge.demo --data-dir examples/settlement_timing --json
python -m reconforge.report_demo --case-id case_settlement_timing_001
python -m reconforge.investigator_demo --case-id case_settlement_timing_001
python -m reconforge.evaluation_demo --case-id case_settlement_timing_001
```

## Run the API and MCP milestone

Create a local environment and install the pinned dependencies. Installation
downloads packages; the fixture demo and MCP round trip use no model or API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m reconforge.mcp_demo
python -m reconforge.mcp_demo --case-id case_bank_shortfall_001
```

The 135-test suite includes the original 13 financial tests plus case, HTTP, MCP,
case-isolation, report, and investigator checks. Provider HTTP tests use a mock
transport; CI needs no API key and makes no paid model calls. Each MCP demo launches a real
stdio server subprocess, discovers its four tools, selects a case, and retrieves
its captured evidence.
The default retrieves the invoice; `--case-id` above retrieves the bank row. It is a
deterministic client demonstration. The optional investigator is a separate command below.

To inspect the HTTP API locally:

```bash
python -m uvicorn reconforge.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.
The API has no authentication and is intended only for the bundled synthetic
fixtures on your own machine. See [the investigation-report walkthrough](docs/DAY_03_REPORTS.md).

| MCP tool | Result |
| --- | --- |
| `list_cases()` | Configured cases, their versions, review flags and both residuals |
| `get_case(case_id)` | Typed deterministic facts and evidence IDs |
| `get_evidence(case_id, case_version, evidence_id)` | One source row from that exact captured case snapshot |
| `get_investigation_report(case_id, case_version)` | Verified fixed-rule findings, unverified possibilities, questions, and human next steps |

## Generate a cited investigation report

With the environment above active:

```bash
python -m reconforge.report_demo
python -m reconforge.report_demo --case-id case_bank_shortfall_001
python -m reconforge.report_demo --case-id case_bank_shortfall_001 --json
```

Each command retrieves the current case version and its report over real MCP
stdio. The default output is Markdown; `--json` exposes the typed report and
verification result. HTTP provides the same report through
`GET /cases/{case_id}/report?case_version=<version-from-get-case>`.

The server independently recomputes the supplied totals and event differences,
checks snapshot and row citations, and requires every claim to match the fixed
report rules. It rejects changed amounts, unrelated citations, omitted findings,
and hypotheses presented as established causes. Verification is limited to this
report format and the captured inputs. It does not verify arbitrary model prose,
source authenticity, or external reporting completeness.

The EUR 150.00 bank discrepancy remains unexplained. The report suggests records
for a person to obtain; it cannot approve or execute a financial action.

## Run the bounded investigator

Start with the offline simulation, which exercises real MCP reads and the same
proposal validator used by the live path:

```bash
python -m reconforge.investigator_demo --case-id case_bank_shortfall_001
python -m reconforge.investigator_demo
```

The output says `scripted_offline`. This is a deterministic test driver, not an
LLM result. [Inspect a saved offline run](examples/investigator/bank_scripted.md).

To make actual model calls, choose an API model explicitly and use `--live`:

```bash
python -m reconforge.investigator_demo --case-id case_bank_shortfall_001 --live --model gpt-4.1-mini-2025-04-14
```

An API key is read from `OPENAI_API_KEY` or a hidden terminal prompt. The command
does not save the key. Live mode sends the synthetic report, evidence catalogue,
and selected rows to OpenAI and uses API quota. The example snapshot supports
Responses and function calling according to its
[official model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
Account access and this application's live compatibility still need a live run.
See [today's walkthrough](docs/DAY_04_INVESTIGATOR.md).

The model chooses evidence reads and the order of existing hypotheses, questions,
and human information requests. The host fixes the case/version, requires every
verified finding and exact amount, requires inspection of the report's row
citations, and rejects unsupported tools or conclusions. There is no free-form
diagnostic prose in this first contract. All hypothesis wording comes from the
deterministic playbook and remains unverified.

The result records `contract_status: passed` and `priority_quality: not_evaluated`.
Those are different claims. A plan can meet every structural rule and still have
an unhelpful ordering. Model quality, usefulness, and resistance to adversarial
source data require separate live evaluations.

### Offline evaluation harness

AELYQ includes an offline evaluator for accepted investigation runs:

```bash
python -m reconforge.evaluation_demo
python -m reconforge.evaluation_demo --json

## What is implemented

- Exact EUR parsing into integer cents; floats and sub-cent inputs are rejected.
- Strict CSV headers, required fields, timestamp and event-type validation.
- Duplicate event detection and rejection of mixed source scopes.
- Separate ledger-to-provider and provider-to-bank residuals.
- Missing, extra, and changed canonical-event comparisons.
- Source filenames, CSV record references, and SHA-256 source snapshots.
- A rule that offsetting event differences still require review, even if totals balance.
- An offline test suite and a reproducible synthetic fixture.
- Immutable typed case views; source rows and calculations share captured bytes.
- Version-checked, bounded evidence reads through HTTP and MCP.
- A real MCP stdio client/server demonstration, covered by CI.
- Two separate synthetic cases, with bounded configuration and per-case evidence lookup.
- Version-bound investigation reports with strict integer amounts and two citation types.
- Report checks that recompute captured financial facts and enforce fixed claim rules.
- Readable Markdown examples, JSON output, and report retrieval over HTTP and MCP.
- A bounded investigator loop with optional OpenAI Responses function calling.
- Host-controlled case context, evidence-read limits, exact finding checks, and an execution trace.
- Offline simulation and mocked-provider failure tests, with explicit execution-mode labels.

## What these results mean

`balanced_by_total` only describes the supplied files. It does not prove that
external reporting is complete, that the original records are true, or that an
accounting adjustment should be posted. File hashes identify the bytes read;
they are not proof of trusted provenance. Tenant labels here are data fields,
not authentication or access control.

Each case supports one tenant, merchant, payout batch, and currency,
with exactly one bank payout entry. All configured cases are visible to local
callers; separate case lookup tables are not tenant access control.
It is not production financial software.
Its signed ledger rows are an operational cash projection, not double-entry
general-ledger records. No money moves and no journal entries are posted.

## Direction of the project

The intended product combines a deterministic reconciliation core with bounded
investigation, resolution planning, and verification. The first investigator
now consumes the read-only tools; resolution planning and authenticated human
approval remain future work. Calculations and permitted operations stay under
application control. Multi-agent orchestration is not implemented in this version.

The first public milestone is a working synthetic investigation demonstration.
The day-30 target is an evaluated v0.1 with documented limitations. Those are
targets, not released capabilities.

## Start here

- [Original Day 0 setup](START_HERE.md)
- [Day 1 checklist](docs/DAY_01.md)
- [Day 1: case API and read-only MCP](docs/DAY_01_MCP.md)
- [Multiple-case milestone](docs/NEXT_02_MULTICASE.md)
- [Day 3: evidence-verified investigation reports](docs/DAY_03_REPORTS.md)
- [Day 4: bounded model-assisted investigator](docs/DAY_04_INVESTIGATOR.md)
- [Current verification results](docs/INVESTIGATOR_VERIFICATION.md)
- [Anthropic live-provider verification](docs/ANTHROPIC_VERIFICATION.md)
- [Scope and acceptance criteria](docs/SCOPE.md)
- [Financial-core design decision](docs/architecture/0001-financial-core.md)
- [Report verification design decision](docs/architecture/0004-investigation-reports.md)
- [Investigator design decision](docs/architecture/0005-bounded-investigator.md)
- [Fixture definitions](examples/invoice_deduction/README.md)
- [Bank-discrepancy fixture](examples/bank_shortfall/README.md)
- [Contribution instructions](CONTRIBUTING.md)

## License

Apache-2.0; see [LICENSE](LICENSE). All bundled example records are synthetic.
The fixture does not claim compatibility with a production payment-provider
report. No affiliation with payment providers or target employers is implied.
