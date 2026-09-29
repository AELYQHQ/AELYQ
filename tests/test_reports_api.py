import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from reconforge.api import create_app
from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID, CaseStore
from reconforge.reports import VerifiedReport


class ReportApiTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore()
        self.client = TestClient(create_app(self.store), base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)

    def test_both_http_reports_return_exact_amounts_and_verification_scope(self):
        for case_id, residuals in ((CASE_ID, [25000, 0]), (BANK_CASE_ID, [0, 15000]), (TIMING_CASE_ID, [0, 1000000])):
            case = self.store.get_case(case_id)
            response = self.client.get(f"/cases/{case_id}/report", params={"case_version": case.case_version})
            with self.subTest(case_id=case_id):
                self.assertEqual(response.status_code, 200)
                verified = VerifiedReport.model_validate(response.json())
                self.assertEqual([f.amount_minor for f in verified.report.findings[3:5]], residuals)
                self.assertEqual(verified.verification.scope, "captured_rows_and_fixed_report_rules")
                self.assertFalse(verified.report.financial_actions_allowed)

    def test_missing_malformed_stale_and_unknown_report_contexts_have_explicit_errors(self):
        self.assertEqual(self.client.get(f"/cases/{CASE_ID}/report").status_code, 422)
        for version, status in (("bad", 422), ("0" * 64, 409)):
            self.assertEqual(self.client.get(f"/cases/{CASE_ID}/report", params={"case_version": version}).status_code, status)
        self.assertEqual(self.client.get("/cases/unknown/report", params={"case_version": "0" * 64}).status_code, 404)

    def test_inconsistent_case_facts_cannot_leave_the_api_as_a_verified_report(self):
        case = self.store.get_case(CASE_ID)
        totals = case.facts.totals_minor.model_copy(update={"bank": 1})
        invalid = case.model_copy(update={"facts": case.facts.model_copy(update={"totals_minor": totals})})
        with patch.object(self.store, "get_case", return_value=invalid):
            response = self.client.get(f"/cases/{CASE_ID}/report", params={"case_version": case.case_version})
        self.assertEqual(response.status_code, 422)
        self.assertIn("totals", response.json()["detail"])
        self.assertNotIn("verification", response.json())
