import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_app
from reconforge.cases import CaseStore
from reconforge.evaluation_demo import evaluate_benchmark
from reconforge.evaluation_store import EvaluationArtifactStore


class EvaluationApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()

        self.evaluation_store = EvaluationArtifactStore(
            Path(self.directory.name),
            application_version="test-version",
        )

        benchmark = asyncio.run(evaluate_benchmark())

        self.artifact = self.evaluation_store.save(
            benchmark,
            evaluation_id="evaluation_" + "a" * 32,
        )

        self.client = TestClient(
            create_app(
                CaseStore(),
                evaluation_store=self.evaluation_store,
            ),
            base_url="http://127.0.0.1",
        )

        self.addCleanup(self.client.close)
        self.addCleanup(self.directory.cleanup)

    def test_list_evaluations_returns_verified_metadata(self):
        response = self.client.get("/evaluations")

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertEqual(len(payload), 1)
        self.assertEqual(
            payload[0]["evaluation_id"],
            self.artifact.evaluation_id,
        )
        self.assertEqual(
            payload[0]["artifact_type"],
            "benchmark",
        )
        self.assertEqual(
            payload[0]["result_sha256"],
            self.artifact.result_sha256,
        )
        self.assertEqual(
            payload[0]["quality_claim"],
            "not_established",
        )

        self.assertEqual(
            set(payload[0]["case_ids"]),
            {
                "case_invoice_deduction_001",
                "case_bank_shortfall_001",
                "case_settlement_timing_001",
            },
        )

    def test_get_evaluation_returns_complete_verified_artifact(self):
        response = self.client.get(
            f"/evaluations/{self.artifact.evaluation_id}"
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertEqual(
            payload["evaluation_id"],
            self.artifact.evaluation_id,
        )
        self.assertEqual(
            payload["artifact_type"],
            "benchmark",
        )
        self.assertEqual(
            payload["result_sha256"],
            self.artifact.result_sha256,
        )
        self.assertEqual(
            payload["result"]["quality_claim"],
            "not_established",
        )

    def test_unknown_evaluation_returns_404(self):
        response = self.client.get(
            "/evaluations/" + "evaluation_" + "b" * 32
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "Evaluation artifact not found.",
        )

    def test_malformed_evaluation_id_returns_404(self):
        response = self.client.get(
            "/evaluations/not-an-evaluation-id"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "Invalid evaluation ID.",
        )

    def test_tampered_evaluation_fails_closed(self):
        path = (
            Path(self.directory.name)
            / f"{self.artifact.evaluation_id}.json"
        )

        payload = json.loads(path.read_text())

        payload["result_sha256"] = "0" * 64

        path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        response = self.client.get(
            f"/evaluations/{self.artifact.evaluation_id}"
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn(
            "SHA-256 integrity verification",
            response.json()["detail"],
        )

    def test_evaluation_endpoints_are_read_only(self):
        openapi = self.client.get("/openapi.json").json()

        self.assertIn("/evaluations", openapi["paths"])
        self.assertIn(
            "/evaluations/{evaluation_id}",
            openapi["paths"],
        )

        self.assertEqual(
            set(openapi["paths"]["/evaluations"].keys()),
            {"get"},
        )

        self.assertEqual(
            set(
                openapi["paths"]["/evaluations/{evaluation_id}"].keys()
            ),
            {"get"},
        )


if __name__ == "__main__":
    unittest.main()
