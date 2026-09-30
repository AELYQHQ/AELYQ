import unittest

from fastapi.testclient import TestClient

from reconforge.api import create_app
from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID, CaseStore
from reconforge.operator_ui import render_operator_case
from reconforge.reports import get_investigation_report


class OperatorUiTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore()
        self.client = TestClient(create_app(self.store), base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)

    def test_operator_index_lists_all_cases_without_expanding_openapi(self):
        response = self.client.get("/operator")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("AELYQ", response.text)
        for case_id in (CASE_ID, BANK_CASE_ID, TIMING_CASE_ID):
            self.assertIn(case_id, response.text)

        document = self.client.get("/openapi.json").json()
        self.assertNotIn("/operator", document["paths"])
        self.assertFalse(any(path.startswith("/operator/") for path in document["paths"]))

    def test_bank_case_shows_verified_discrepancy_and_uncertainty(self):
        response = self.client.get(f"/operator/cases/{BANK_CASE_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("EUR 82,000.00", response.text)
        self.assertIn("EUR 81,850.00", response.text)
        self.assertIn("EUR 150.00", response.text)
        self.assertIn("Unverified hypotheses", response.text)
        self.assertIn("payout_timing_or_reporting", response.text)
        self.assertIn("adjustment_or_data_error", response.text)
        self.assertIn("No financial actions are allowed", response.text)

    def test_operator_case_exposes_captured_evidence_rows(self):
        response = self.client.get(f"/operator/cases/{BANK_CASE_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("bank_entries.csv", response.text)
        self.assertIn("evt_bank_001", response.text)
        self.assertIn("81850.00 EUR", response.text)

    def test_operator_case_escapes_untrusted_source_fields(self):
        case = self.store.get_case(BANK_CASE_ID)
        report = get_investigation_report(self.store, BANK_CASE_ID, case.case_version)
        evidence = tuple(
            self.store.get_evidence(BANK_CASE_ID, case.case_version, ref.evidence_id)
            for ref in case.evidence
        )
        dangerous = evidence[0].model_copy(
            update={
                "row": evidence[0].row.model_copy(
                    update={"event_id": "<script>alert(1)</script>"}
                )
            }
        )

        rendered = render_operator_case(case, report, (dangerous,) + evidence[1:])

        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)

    def test_unknown_operator_case_is_not_found(self):
        response = self.client.get("/operator/cases/unknown")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
