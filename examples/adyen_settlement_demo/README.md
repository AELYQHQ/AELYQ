# Adyen settlement details demo (synthetic)

All numbers, PSP references and merchant identities here are invented. This sample is designed specifically for the supported subset of the Settlement details adapter. It is **not** a real Adyen report or a customer export.

- `adyen_settlement_details.csv`: mixed transaction, fee, invoice, reserve and MerchantPayout rows.
- `ledger_events.csv`: normalized synthetic cash projection matching the converter's output IDs and values.
- `bank_entries.csv`: EUR 72.00 payout, EUR 1.00 below the Adyen settlement control total.

Run `python -m reconforge.adyen_adapter` with the arguments in `docs/ADYEN_SETTLEMENT_ADAPTER_V1.md`, then run `python -m reconforge.ingestion` on the new output directory. Expected signed PSP total is EUR 73.00, gross ledger-to-provider residual EUR 0.00, provider-to-bank residual EUR 1.00, review required.
