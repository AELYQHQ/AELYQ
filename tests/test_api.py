import unittest

from fastapi.testclient import TestClient

from reconforge.api import create_app
from reconforge.cases import BANK_CASE_ID, CASE_ID, CaseStore


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore()
        self.client = TestClient(create_app(self.store), base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)
        self.case = self.store.get_case(CASE_ID)

    def test_http_case_matches_the_domain_object(self):
        response = self.client.get(f"/cases/{CASE_ID}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.case.model_dump(mode="json"))
        listed = self.client.get("/cases").json()
        self.assertEqual(len(listed["cases"]), 3)
        summary = next(item for item in listed["cases"] if item["case_id"] == CASE_ID)
        self.assertEqual(summary["case_version"], self.case.case_version)

    def test_bank_discrepancy_is_visible_in_both_list_and_case(self):
        response = self.client.get(f"/cases/{BANK_CASE_ID}")
        self.assertEqual(response.status_code, 200)
        facts = response.json()["facts"]
        self.assertEqual(facts["comparisons"]["ledger_to_provider"]["residual_minor"], 0)
        self.assertEqual(facts["comparisons"]["provider_to_bank"]["residual_minor"], 15000)
        self.assertTrue(facts["review_required"])
        listed = self.client.get("/cases").json()["cases"]
        summary = next(item for item in listed if item["case_id"] == BANK_CASE_ID)
        self.assertEqual(summary["provider_to_bank_residual_minor"], 15000)
        self.assertEqual(summary["ledger_to_provider_residual_minor"], 0)

    def test_evidence_lookup_cannot_cross_case_boundaries(self):
        bank = self.store.get_case(BANK_CASE_ID)
        bank_ref = next(ref for ref in bank.evidence if ref.file == "bank_entries.csv")
        response = self.client.get(
            f"/cases/{BANK_CASE_ID}/evidence/{bank_ref.evidence_id}",
            params={"case_version": bank.case_version},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["row"]["amount_eur"], "81850.00")
        invoice_ref = next(ref for ref in self.case.evidence if ref.event_id == "evt_invoice_001")
        response = self.client.get(
            f"/cases/{BANK_CASE_ID}/evidence/{invoice_ref.evidence_id}",
            params={"case_version": bank.case_version},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Unknown evidence ID for this case.")

    def test_another_cases_version_is_rejected_for_valid_bank_evidence(self):
        bank = self.store.get_case(BANK_CASE_ID)
        response = self.client.get(
            f"/cases/{BANK_CASE_ID}/evidence/{bank.evidence[0].evidence_id}",
            params={"case_version": self.case.case_version},
        )
        self.assertEqual(response.status_code, 409)

    def test_http_evidence_requires_version_and_returns_correct_row(self):
        reference = next(ref for ref in self.case.evidence if ref.event_id == "evt_invoice_001")
        url = f"/cases/{CASE_ID}/evidence/{reference.evidence_id}"
        self.assertEqual(self.client.get(url).status_code, 422)
        self.assertEqual(self.client.get(url, params={"case_version": "bad"}).status_code, 422)
        self.assertEqual(self.client.get(url, params={"case_version": "0" * 64}).status_code, 409)
        response = self.client.get(url, params={"case_version": self.case.case_version})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["row"]["amount_eur"], "-250.00")
        self.assertEqual(response.json()["reference"]["sha256"], reference.sha256)

    def test_unknown_case_and_evidence_have_explicit_not_found_results(self):
        self.assertEqual(self.client.get("/cases/unknown").status_code, 404)
        response = self.client.get(
            f"/cases/{CASE_ID}/evidence/ev_" + "0" * 64,
            params={"case_version": self.case.case_version},
        )
        self.assertEqual(response.status_code, 404)

    def test_financial_mutations_are_not_exposed(self):
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            with self.subTest(method=method):
                self.assertEqual(self.client.request(method, f"/cases/{CASE_ID}").status_code, 405)
        self.assertEqual(self.client.post(f"/cases/{CASE_ID}/approve").status_code, 404)

    def test_unexpected_host_is_rejected(self):
        self.assertEqual(self.client.get("/cases", headers={"Host": "untrusted.example"}).status_code, 400)

    def test_openapi_documents_integer_money_and_read_only_routes(self):
        document = self.client.get("/openapi.json").json()
        self.assertEqual(document["components"]["schemas"]["Totals"]["properties"]["ledger"]["type"], "integer")
        for path, operations in document["paths"].items():
            with self.subTest(path=path):
                self.assertEqual(set(operations), {"get"})
