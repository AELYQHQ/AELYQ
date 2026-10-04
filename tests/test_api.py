import json
import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from reconforge.investigation_store import InvestigationArtifactStore
from reconforge.evaluation_store import EvaluationArtifactStore

from fastapi.testclient import TestClient

from reconforge.api import create_app
from reconforge.cases import BANK_CASE_ID, CASE_ID, CaseStore
from reconforge.evaluation import InvestigationRepeatability
from reconforge.investigation import InvestigationError
from reconforge.investigator import run_mcp_investigation


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore()
        self.artifact_directory = tempfile.TemporaryDirectory()
        self.artifact_store = InvestigationArtifactStore(
            Path(self.artifact_directory.name),
            application_version="test-version",
        )
        self.evaluation_directory = tempfile.TemporaryDirectory()
        self.evaluation_store = EvaluationArtifactStore(
            Path(self.evaluation_directory.name),
            application_version="test-version",
        )
        self.client = TestClient(
            create_app(
                self.store,
                artifact_store=self.artifact_store,
                evaluation_store=self.evaluation_store,
            ),
            base_url="http://127.0.0.1",
        )
        self.addCleanup(self.client.close)
        self.addCleanup(self.artifact_directory.cleanup)
        self.addCleanup(self.evaluation_directory.cleanup)
        self.case = self.store.get_case(CASE_ID)

    def make_repeatability(self, case_id: str) -> InvestigationRepeatability:
        case = self.store.get_case(case_id)
        return InvestigationRepeatability(
            case_id=case.case_id,
            case_version=case.case_version,
            mode="scripted_offline",
            requested_model=None,
            run_count=2,
            contract_pass_count=2,
            case_context_match_count=2,
            distinct_evidence_selections=1,
            distinct_hypothesis_orders=1,
            distinct_question_orders=1,
            distinct_next_step_orders=1,
            evidence_selection_agreement=1.0,
            hypothesis_order_agreement=1.0,
            question_order_agreement=1.0,
            next_step_order_agreement=1.0,
        )

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

    def test_investigation_history_returns_verified_metadata_newest_first(self):
        run = asyncio.run(run_mcp_investigation(BANK_CASE_ID))

        first = self.artifact_store.save(
            run,
            run_id="run_" + "a" * 32,
            created_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        )
        second = self.artifact_store.save(
            run,
            run_id="run_" + "b" * 32,
            created_at=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        )

        response = self.client.get(
            f"/cases/{BANK_CASE_ID}/investigations"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(
            [item["run_id"] for item in payload],
            [second.run_id, first.run_id],
        )
        self.assertEqual(payload[0]["case_id"], BANK_CASE_ID)
        self.assertEqual(
            payload[0]["case_version"],
            run.proposal.case_version,
        )
        self.assertEqual(payload[0]["application_version"], "test-version")
        self.assertEqual(payload[0]["mode"], run.mode)
        self.assertEqual(
            payload[0]["requested_model"],
            run.requested_model,
        )
        self.assertEqual(payload[0]["contract_status"], "passed")
        self.assertEqual(
            payload[0]["run_sha256"],
            second.run_sha256,
        )

    def test_investigation_history_returns_404_for_unknown_case(self):
        response = self.client.get(
            "/cases/unknown/investigations"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "Unknown case ID.",
        )

    def test_investigation_history_fails_closed_on_invalid_artifact(self):
        run_id = "run_" + "c" * 32
        path = Path(self.artifact_directory.name) / f"{run_id}.json"
        path.write_text(
            '{"not": "a valid investigation artifact"}',
            encoding="utf-8",
        )

        response = self.client.get(
            f"/cases/{BANK_CASE_ID}/investigations"
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn(
            "investigation artifact",
            response.json()["detail"].lower(),
        )

    def test_evaluation_history_lists_all_and_filters_by_case(self):
        invoice = self.evaluation_store.save(
            self.make_repeatability(CASE_ID)
        )
        bank = self.evaluation_store.save(
            self.make_repeatability(BANK_CASE_ID)
        )

        response = self.client.get("/evaluations")

        self.assertEqual(response.status_code, 200)
        listed = response.json()
        self.assertEqual(len(listed), 2)
        self.assertEqual(
            {item["evaluation_id"] for item in listed},
            {invoice.evaluation_id, bank.evaluation_id},
        )

        response = self.client.get(
            f"/cases/{CASE_ID}/evaluations"
        )

        self.assertEqual(response.status_code, 200)
        case_history = response.json()
        self.assertEqual(len(case_history), 1)
        self.assertEqual(
            case_history[0]["evaluation_id"],
            invoice.evaluation_id,
        )
        self.assertEqual(
            case_history[0]["case_ids"],
            [CASE_ID],
        )

    def test_evaluation_detail_returns_verified_artifact(self):
        artifact = self.evaluation_store.save(
            self.make_repeatability(BANK_CASE_ID)
        )

        response = self.client.get(
            f"/evaluations/{artifact.evaluation_id}"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["evaluation_id"],
            artifact.evaluation_id,
        )
        self.assertEqual(
            payload["artifact_type"],
            "repeatability",
        )
        self.assertEqual(
            payload["result_sha256"],
            artifact.result_sha256,
        )
        self.assertEqual(
            payload["result"]["case_id"],
            BANK_CASE_ID,
        )

    def test_missing_evaluation_returns_404(self):
        response = self.client.get(
            "/evaluations/" + "evaluation_" + "a" * 32
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            "Evaluation artifact not found",
            response.json()["detail"],
        )

    def test_tampered_evaluation_fails_closed(self):
        artifact = self.evaluation_store.save(
            self.make_repeatability(BANK_CASE_ID)
        )

        path = (
            Path(self.evaluation_directory.name)
            / f"{artifact.evaluation_id}.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["result_sha256"] = "0" * 64
        path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        response = self.client.get(
            f"/evaluations/{artifact.evaluation_id}"
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn(
            "integrity",
            response.json()["detail"].lower(),
        )

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
    def test_operator_case_contains_bounded_investigation_action(self):
        response = self.client.get(f"/operator/cases/{CASE_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'/operator/cases/{CASE_ID}/investigate',
            response.text,
        )
        self.assertIn("Run bounded investigation", response.text)
    def test_operator_case_shows_persisted_investigation_history(self):
        run = asyncio.run(run_mcp_investigation(BANK_CASE_ID))
        artifact = self.artifact_store.save(
            run,
            run_id="run_" + "e" * 32,
            created_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc),
        )

        response = self.client.get(f"/operator/cases/{BANK_CASE_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Investigation history", response.text)
        self.assertIn(artifact.run_id, response.text)
        self.assertIn(
            f"/operator/investigations/{artifact.run_id}",
            response.text,
        )
        self.assertIn("scripted_offline", response.text)
        self.assertIn("View investigation", response.text)

    def test_operator_investigation_persists_and_redirects_to_run(self):
        fake_run = object()
        fake_artifact = MagicMock()
        fake_artifact.run_id = "run_" + "a" * 32

        with (
            patch(
                "reconforge.api.run_mcp_investigation",
                new=AsyncMock(return_value=fake_run),
            ) as runner,
            patch.object(
                self.artifact_store,
                "save",
                return_value=fake_artifact,
            ) as saver,
        ):
            response = self.client.post(
                f"/operator/cases/{CASE_ID}/investigate",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/operator/investigations/{fake_artifact.run_id}",
        )
        runner.assert_awaited_once_with(CASE_ID)
        saver.assert_called_once_with(fake_run)

    def test_operator_investigation_get_loads_and_renders_verified_artifact(self):
        fake_artifact = MagicMock()
        fake_artifact.run = object()

        with (
            patch.object(
                self.artifact_store,
                "get",
                return_value=fake_artifact,
            ) as loader,
            patch(
                "reconforge.api.render_operator_investigation",
                return_value="<html>verified-investigation</html>",
            ) as renderer,
        ):
            response = self.client.get(
                "/operator/investigations/run_" + "b" * 32
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("verified-investigation", response.text)
        loader.assert_called_once_with("run_" + "b" * 32)
        renderer.assert_called_once_with(
            fake_artifact.run,
            artifact=fake_artifact,
        )

    def test_operator_investigation_get_returns_404_for_missing_run(self):
        response = self.client.get(
            "/operator/investigations/run_" + "c" * 32
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Investigation unavailable", response.text)
        self.assertIn("Investigation run not found", response.text)


    def test_operator_investigation_get_fails_closed_on_invalid_artifact(self):
        run_id = "run_" + "d" * 32
        path = Path(self.artifact_directory.name) / f"{run_id}.json"
        path.write_text(
            '{"not": "a valid investigation artifact"}',
            encoding="utf-8",
        )

        response = self.client.get(
            f"/operator/investigations/{run_id}"
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("Investigation unavailable", response.text)
        self.assertIn("integrity", response.text.lower())


    def test_operator_investigation_error_is_rendered(self):
        with patch(
            "reconforge.api.run_mcp_investigation",
            new=AsyncMock(
                side_effect=InvestigationError("synthetic investigator failure")
            ),
        ):
            response = self.client.post(
                f"/operator/cases/{CASE_ID}/investigate"
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Investigation stopped", response.text)
        self.assertIn("synthetic investigator failure", response.text)
