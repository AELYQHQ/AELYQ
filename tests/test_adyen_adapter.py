"""Offline tests for the narrow, fail-closed Adyen settlement-details adapter."""

import csv
import io
import json
import unittest
from hashlib import sha256
from pathlib import Path

from reconforge.adyen_adapter import (
    AdyenAdapterError,
    convert_adyen_settlement,
)

FIXTURE = Path(__file__).resolve().parents[1] / 'examples' / 'adyen_settlement_demo'
ARGS = {
    "tenant_id": "tenant_demo",
    "merchant_id": "DemoMerchant",
    "batch_id": "batch_42",
    "batch_number": "42",
}


def fixture():
    return (FIXTURE / 'adyen_settlement_details.csv').read_bytes()


def parse(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))


def edit(raw, record, **fields):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8'), newline=''))
    headers = reader.fieldnames
    rows = list(reader)
    rows[record - 1].update(fields)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode('utf-8')


class AdyenAdapterTests(unittest.TestCase):
    def test_correct_conversion_amounts_and_provenance(self):
        result = convert_adyen_settlement(fixture(), **ARGS)
        self.assertEqual(result.source_record_count, 6)
        self.assertEqual(result.normalized_record_count, 7)
        self.assertEqual(result.psp_total_minor, 7300)
        self.assertEqual(result.payout_control_minor, 7300)
        self.assertEqual(result.payout_control_row, 6)
        rows = parse(result.normalized_psp)
        self.assertEqual([r['event_type'] for r in rows], [
            'Capture','Fee','Refund','Fee','Fee','InvoiceDeduction','ReserveAdjustment'
        ])
        self.assertEqual([r['amount_eur'] for r in rows], [
            '100.00','-2.50','-20.00','-0.50','-1.00','-5.00','2.00'
        ])
        self.assertEqual({r['currency'] for r in rows}, {'EUR'})
        self.assertEqual({r['effective_at'][-6:] for r in rows}, {'+00:00'})
        self.assertEqual(result.provenance[0]['source_record_number'], 1)
        self.assertEqual(result.provenance[1]['source_record_number'], 1)
        self.assertEqual(result.provenance[1]['normalized_event_type'], 'Fee')
        self.assertEqual(sha256(fixture()).hexdigest(), result.source_sha256)
        self.assertEqual(sha256(result.normalized_psp).hexdigest(), result.normalized_sha256)

    def test_repeated_conversion_is_byte_reproducible(self):
        first = convert_adyen_settlement(fixture(), **ARGS)
        second = convert_adyen_settlement(fixture(), **ARGS)
        self.assertEqual(first, second)

    def test_source_bom_is_preserved_in_hash_not_normalized_output(self):
        report = b'\xef\xbb\xbf' + fixture()
        result = convert_adyen_settlement(report, **ARGS)
        self.assertEqual(result.source_sha256, sha256(report).hexdigest())
        self.assertFalse(result.normalized_psp.startswith(b'\xef\xbb\xbf'))

    def test_optional_extra_column_is_supported(self):
        base = fixture().decode('utf-8').splitlines()
        modified = ('Optional Extra,' + base[0] + '\n' +
                    ''.join('value,' + row + '\n' for row in base[1:])).encode()
        result = convert_adyen_settlement(modified, **ARGS)
        self.assertEqual(result.psp_total_minor, 7300)

    def test_different_source_hash_for_modified_raw_data(self):
        modified = edit(fixture(), 1, **{'Merchant Reference': 'new_identifier'})
        original = convert_adyen_settlement(fixture(), **ARGS)
        changed = convert_adyen_settlement(modified, **ARGS)
        self.assertNotEqual(original.source_sha256, changed.source_sha256)
        self.assertEqual(original.normalized_sha256, changed.normalized_sha256)

    def test_manifest_accounts_for_every_normalized_row(self):
        result = convert_adyen_settlement(fixture(), **ARGS)
        manifest = result.manifest()
        self.assertEqual(len(manifest['mapping']), len(parse(result.normalized_psp)))
        self.assertEqual(manifest['payout_control']['amount_minor'], 7300)
        self.assertNotIn('raw_rows', json.dumps(manifest))

    def test_unsupported_chargeback_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'Chargeback'):
            convert_adyen_settlement(edit(fixture(), 1, Type='Chargeback'), **ARGS)

    def test_fx_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'gross currency/FX'):
            convert_adyen_settlement(edit(fixture(), 1, **{'Gross Currency': 'GBP'}), **ARGS)

    def test_mixed_merchant_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'merchant account mismatch'):
            convert_adyen_settlement(edit(fixture(), 3, **{'Merchant Account': 'AnotherMerchant'}), **ARGS)

    def test_mixed_batch_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'batch number mismatch'):
            convert_adyen_settlement(edit(fixture(), 3, **{'Batch Number': '43'}), **ARGS)

    def test_wrong_control_total_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'payout control mismatch'):
            convert_adyen_settlement(edit(fixture(), 6, **{'Net Debit (NC)': '72.00'}), **ARGS)

    def test_malformed_amount_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'invalid nonnegative EUR amount'):
            convert_adyen_settlement(edit(fixture(), 1, **{'Net Credit (NC)': '97.501'}), **ARGS)

    def test_negative_amount_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'invalid nonnegative EUR amount'):
            convert_adyen_settlement(edit(fixture(), 3, **{'Net Debit (NC)': '-1.00'}), **ARGS)

    def test_ambiguous_credit_debit_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'expected exactly one'):
            convert_adyen_settlement(edit(fixture(), 1, **{'Net Debit (NC)': '1.00'}), **ARGS)

    def test_timezone_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'unsupported timezone'):
            convert_adyen_settlement(edit(fixture(), 1, TimeZone='America/Chicago'), **ARGS)

    def test_malformed_csv_header_fails_closed(self):
        content = fixture().decode('utf-8').replace('Merchant Account,', 'Wrong Header,', 1).encode('utf-8')
        with self.assertRaisesRegex(AdyenAdapterError, 'Missing required Adyen columns'):
            convert_adyen_settlement(content, **ARGS)

    def test_missing_payout_control_fails_closed(self):
        report = fixture().decode('utf-8').splitlines()
        with self.assertRaisesRegex(AdyenAdapterError, 'Exactly one MerchantPayout'):
            convert_adyen_settlement(('\n'.join(report[:-1]) + '\n').encode('utf-8'), **ARGS)

    def test_oversized_source_fails_closed(self):
        with self.assertRaisesRegex(AdyenAdapterError, 'at most 1 MiB'):
            convert_adyen_settlement(b'a' * (1_048_576 + 1), **ARGS)

    def test_unsupported_positive_invoice_credit_fails_closed(self):
        report = edit(fixture(), 4, **{'Net Debit (NC)': '', 'Net Credit (NC)': '5.00'})
        with self.assertRaisesRegex(AdyenAdapterError, 'positive InvoiceDeduction'):
            convert_adyen_settlement(report, **ARGS)

    def test_malformed_row_fails_closed(self):
        report = fixture() + b'garbage,too,few\n'
        with self.assertRaisesRegex(AdyenAdapterError, 'malformed field count'):
            convert_adyen_settlement(report, **ARGS)

    def test_core_integration_produces_bank_shortfall(self):
        # This integration test uses the actual project's reconciliation engine.
        try:
            from reconforge.adyen_adapter import prepare_adyen_batch
            from reconforge.reconciliation import reconcile_snapshots
        except ImportError:
            self.skipTest('Existing reconciliation engine not installed in isolated package.')
        conversion, facts, snapshots = prepare_adyen_batch(
            report=fixture(),
            ledger=(FIXTURE / 'ledger_events.csv').read_bytes(),
            bank=(FIXTURE / 'bank_entries.csv').read_bytes(),
            **ARGS,
        )
        self.assertEqual(conversion.psp_total_minor, 7300)
        self.assertEqual(facts['comparisons']['provider_to_bank']['residual_minor'], 100)
        self.assertTrue(facts['review_required'])
        self.assertEqual(snapshots['psp_events.csv'], conversion.normalized_psp)


if __name__ == '__main__':
    unittest.main()
