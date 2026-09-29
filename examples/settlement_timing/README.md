# Settlement timing scenario

This synthetic case demonstrates a provider-to-bank discrepancy where the
ledger and provider agree on EUR 69,400.00, while the supplied bank payout is
EUR 59,400.00.

One EUR 10,000.00 capture has an effective timestamp after the supplied bank
payout timestamp. That makes reporting or settlement timing a plausible line of
investigation, but it does **not** establish timing as the cause.

ReconForge therefore keeps `payout_timing_or_reporting` as an unverified
hypothesis, preserves `cause_undetermined`, and asks a human to compare complete
payout advice, bank statements, dates, and reporting cutoffs.

All data in this directory is synthetic.
