# Adyen Settlement details CSV adapter — intentionally narrow v1

This milestone adds a **read-only, fail-closed** converter of the documented Adyen **Settlement details report** into ReconForge's existing `psp_events.csv` normalized input schema. It does **not** access Adyen APIs, post funds, prove source completeness, or make an LLM call.

Adyen reference: <https://docs.adyen.com/reporting/settlement-reconciliation/transaction-level/settlement-details-report/>

## Entry point

```bash
python -m reconforge.adyen_adapter \
  --report examples/adyen_settlement_demo/adyen_settlement_details.csv \
  --ledger examples/adyen_settlement_demo/ledger_events.csv \
  --bank examples/adyen_settlement_demo/bank_entries.csv \
  --tenant-id tenant_demo \
  --merchant-id DemoMerchant \
  --batch-id batch_42 \
  --batch-number 42 \
  --output-dir /tmp/aelyq-adyen-demo-YOUR-UNIQUE-ID

python -m reconforge.ingestion /tmp/aelyq-adyen-demo-YOUR-UNIQUE-ID --json
```

The output directory **must not already exist**. Choose a unique path. Source files and output CSVs are copied to the local output directory with restrictive access; do **not** commit customer data. The command validates the full three-source comparison **before** creating an output directory. It deliberately does not modify existing files or write to the ledger/bank source paths.

## Adyen input contract

- Up to 1 MiB, 1000 data records; UTF-8 or UTF-8 with BOM; strict CSV with real data-record numbers (not physical line numbers).
- Requires: `Merchant Account`, `Psp Reference`, `Creation Date`, `TimeZone`, `Type`, `Gross Currency`, `Gross Debit (GC)`, `Gross Credit (GC)`, `Net Currency`, `Net Debit (NC)`, `Net Credit (NC)`, and `Batch Number`. Other columns and orderings are permitted, but duplicate headers are rejected.
- Exactly **one merchant account and one positive Adyen batch number**, specified by the operator. All records must match. All settlement currencies are **EUR**; transaction gross currency must also be EUR. No FX. Adyen exports involving several merchants or batches must be split upstream by a trustworthy source process; this converter will not silently filter rows.
- `Creation Date`: `YYYY-MM-DD HH:MM:SS`, with explicit `TimeZone` of `UTC`, `GMT`, `CET`, `CEST`, or numeric `+HH:MM`/`-HH:MM`. Ambiguous timezone values are rejected, never inferred from the server locale. Converted timestamps are UTC.
- Monetary fields: nonnegative decimal values with zero, one, or two decimal places, no group separators, no float conversion; debit/credit sides must be unambiguous. Exact EUR cents are used throughout.

## Journal mappings

| Adyen `Type` | ReconForge event(s) | Validation |
| --- | --- | --- |
| `Settled` | `Capture` = gross credit; optionally `Fee` = negative `(gross credit − net credit)` | Gross and net credit positive, net not above gross |
| `Refunded` | `Refund` = negative gross debit; optionally `Fee` = negative `(net debit − gross debit)` | Gross/net debit positive, net not below gross |
| `Fee` | `Fee` = negative net debit | Debit only |
| `InvoiceDeduction` | `InvoiceDeduction` = negative net debit | Debit only; **positive invoice credit rejected** |
| `ReserveAdjustment` | `ReserveAdjustment` = signed net credit/debit | Exactly one nonzero net side |
| `MerchantPayout` | **Control entry only, not normalized as a transaction or bank deposit** | Exactly one positive net debit; must equal total supported signed net movements |
| All other types | **Entire report rejected** | Includes chargebacks, deposit corrections, returned payouts, transfer and installment types |

The extra `Fee` event derived from a gross-to-net delta is **a cash-bridge adjustment**, not proof that the entire delta is a specific fee category or rate. Adyen's detailed fee columns may have different accounting interpretations. The adapter verifies the *net cash movement*, not the exact economic cause of all fees.

We intentionally require the MerchantPayout control for this **closed batch** prototype. Other report styles (multi-day reports, negative batches, multi-merchant, no payout, FX, payouts in multiple currencies) need a separately designed adapter version.

## Evidence and provenance

The output directory contains:

- `ledger_events.csv`: snapshot of supplied ledger bytes.
- `psp_events.csv`: normalized output bytes, used for ReconForge's deterministic comparison.
- `bank_entries.csv`: snapshot of supplied bank bytes.
- `adyen_settlement_details.csv`: **exact raw Adyen source bytes**.
- `adyen_provenance.json`: source hash, normalized PSP hash, bank/ledger hashes, output-to-source row mapping, source count and payout control.

Generated IDs follow `adyen_r000001_capture`/`adyen_r000001_embedded_fee`, etc.; **these are source-row identifiers, not verified transaction IDs or a real payment-to-ledger matching strategy**. To produce useful ledger-vs-provider matches on live data, the ledger's canonical identity must be mapped deliberately; do not mistake missing-event exceptions due to ID namespaces for real missing money.

Raw source rows are untrusted. They are never executed as instructions; descriptions in normalized output are constructed by this adapter, rather than copied from an arbitrary source field. The manifest links every normalized data record to its **one-based Adyen CSV data-record number**, excluding the header. Raw original bytes are preserved locally for later verification, and their SHA-256 covers the original bytes (including a BOM).

### Synthetic demo expectations

The bundled **synthetic** Adyen CSV includes a EUR 100 settlement, EUR 20 refund, separate fee, invoice deduction, reserve release, and one EUR 73 payout control; the converter yields **7 normalized events** totaling **EUR 73**. The synthetic ledger agrees with this converted provider movement, while the synthetic bank entry is **EUR 72**, yielding a **EUR 1 provider-to-bank shortfall**. This does not imply an actual Adyen or bank integration has been validated.

## Limits and next milestone

- Source model is a partial export mapping for **Adyen Settlement details**, not a certified Adyen adapter or test against live merchant exports.
- No card data, live credentials, networking, data retention policy, durable database, or case registration. Local output is sensitive; secure and delete it deliberately.
- No automatic posting, repair, retry, refund, or approval workflow.
- A follow-on milestone should implement canonical ledger reference matching, explicitly support a broader and economically verified journal grammar, and register immutable imported batches as investigation cases.
