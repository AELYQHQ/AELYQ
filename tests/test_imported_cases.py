"""Regression tests for imported synthetic cases across CaseStore/API/MCP."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from reconforge.cases import CaseStore
from reconforge.imported_cases import (
    ImportRegistrationError,
    imported_fixtures,
    open_case_store,
    register_batch,
)
from reconforge.reconciliation import InputError, SOURCE_FILES
from reconforge.reports import get_investigation_report


class ImportedCaseRegistrationTests(unittest.TestCase):
    SOURCE = Path('examples/imported_case_demo')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / 'registry'
        self.source = self.root / 'incoming'
        shutil.copytree(self.SOURCE, self.source)

    def register(self):
        return register_batch(self.source, registry_directory=self.registry,
                              synthetic_test_data=True)

    def test_registered_case_is_visible_with_original_evidence_and_verified_report(self):
        receipt = self.register()
        store = open_case_store(self.registry, include_examples=False)
        case = store.get_case(receipt.case_id)
        self.assertEqual(receipt.case_version, case.case_version)
        self.assertTrue(case.facts.review_required)
        self.assertEqual(case.facts.totals_minor.ledger, 10000)
        self.assertEqual(case.facts.totals_minor.provider, 9000)
        self.assertEqual(case.facts.totals_minor.bank, 8500)
        self.assertEqual(case.facts.comparisons.ledger_to_provider.residual_minor, 1000)
        self.assertEqual(case.facts.comparisons.provider_to_bank.residual_minor, 500)
        evidence = store.get_evidence(receipt.case_id, case.case_version,
                                      case.evidence[0].evidence_id)
        self.assertEqual(evidence.case_id, receipt.case_id)
        self.assertEqual(evidence.reference.sha256,
                         next(s.sha256 for s in case.facts.source_snapshots
                              if s.file == evidence.reference.file))
        report = get_investigation_report(store, receipt.case_id, case.case_version)
        self.assertEqual(report.report.case_id, receipt.case_id)
        self.assertEqual(report.verification.status, 'passed')
        self.assertFalse(report.report.external_completeness_verified)

    def test_repeated_import_is_idempotent_and_keeps_case_version(self):
        first = self.register()
        second = self.register()
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.case_id, second.case_id)
        self.assertEqual(first.case_version, second.case_version)
        self.assertEqual(len(imported_fixtures(self.registry)), 1)

    def test_source_changes_after_capture_cannot_change_registered_evidence(self):
        first = self.register()
        (self.source / 'bank_entries.csv').write_text('totally different bytes')
        store = open_case_store(self.registry, include_examples=False)
        self.assertEqual(store.get_case(first.case_id).case_version, first.case_version)
        self.assertEqual(
            (self.registry / first.case_id / 'bank_entries.csv').read_bytes(),
            (self.SOURCE / 'bank_entries.csv').read_bytes(),
        )

    def test_tampering_fails_closed_and_does_not_publish_corrupt_cases(self):
        receipt = self.register()
        file = self.registry / receipt.case_id / 'psp_events.csv'
        file.write_bytes(file.read_bytes() + b'\n')
        with self.assertRaises(ImportRegistrationError):
            open_case_store(self.registry, include_examples=False)
        with self.assertRaises(ImportRegistrationError):
            self.register()

    def test_symlink_registry_entry_is_rejected(self):
        receipt = self.register()
        entry = self.registry / receipt.case_id
        moved = self.root / 'moved'
        entry.rename(moved)
        entry.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ImportRegistrationError):
            open_case_store(self.registry, include_examples=False)

    def test_registration_requires_explicit_synthetic_confirmation(self):
        with self.assertRaisesRegex(ImportRegistrationError, 'synthetic test data'):
            register_batch(self.source, registry_directory=self.registry)

    def test_invalid_incoming_batch_is_never_registered(self):
        (self.source / 'bank_entries.csv').unlink()
        with self.assertRaises(InputError):
            self.register()
        self.assertFalse(self.registry.exists())

    def test_case_identity_is_derived_from_all_three_captured_sources(self):
        first = self.register()
        (self.source / 'bank_entries.csv').write_bytes(
            (self.source / 'bank_entries.csv').read_bytes() + b'\n'
        )
        second = self.register()
        self.assertNotEqual(first.case_id, second.case_id)
        self.assertEqual(len(imported_fixtures(self.registry)), 2)

    def test_uncommitted_staging_directory_is_not_exposed(self):
        self.registry.mkdir()
        (self.registry / '.pending-abandoned').mkdir()
        self.assertEqual(imported_fixtures(self.registry), {})

    def test_existing_default_cases_remain_available(self):
        receipt = self.register()
        store = open_case_store(self.registry)
        self.assertIn(receipt.case_id, [c.case_id for c in store.list_cases().cases])
        self.assertGreaterEqual(len(store.list_cases().cases), 4)


class ImportedCaseTransportTests(unittest.TestCase):
    SOURCE = Path('examples/imported_case_demo')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = Path(self.temp.name) / 'registry'
        self.receipt = register_batch(self.SOURCE, registry_directory=self.registry,
                                      synthetic_test_data=True)
        self.store = open_case_store(self.registry, include_examples=False)

    def test_read_only_fastapi_routes_for_imported_case(self):
        from fastapi.testclient import TestClient
        from reconforge.api import create_app

        with TestClient(create_app(self.store), base_url='http://127.0.0.1') as client:
            case_id = self.receipt.case_id
            case = self.store.get_case(case_id)
            self.assertEqual(client.get('/cases').status_code, 200)
            self.assertEqual(client.get(f'/cases/{case_id}').status_code, 200)
            ref = case.evidence[0]
            evidence = client.get(
                f'/cases/{case_id}/evidence/{ref.evidence_id}',
                params={'case_version': case.case_version},
            )
            self.assertEqual(evidence.status_code, 200)
            self.assertEqual(evidence.json()['reference']['sha256'], ref.sha256)
            report = client.get(f'/cases/{case_id}/report',
                                params={'case_version': case.case_version})
            self.assertEqual(report.status_code, 200)
            self.assertEqual(report.json()['report']['case_id'], case_id)
            self.assertEqual(client.post(f'/cases/{case_id}').status_code, 405)

    async def _mcp_round_trip(self):
        from mcp import Client
        from reconforge.mcp_server import create_server
        async with Client(create_server(self.store)) as client:
            tools = (await client.list_tools()).tools
            self.assertTrue(all(t.annotations.read_only_hint for t in tools))
            case = (await client.call_tool('get_case',
                                           {'case_id': self.receipt.case_id})).structured_content
            self.assertEqual(case['case_id'], self.receipt.case_id)
            report = (await client.call_tool('get_investigation_report', {
                'case_id': self.receipt.case_id,
                'case_version': self.receipt.case_version,
            })).structured_content
            self.assertEqual(report['report']['case_id'], self.receipt.case_id)

    def test_imported_case_mcp_tools_are_read_only_and_version_bound(self):
        import asyncio
        asyncio.run(self._mcp_round_trip())


if __name__ == '__main__':
    unittest.main()
