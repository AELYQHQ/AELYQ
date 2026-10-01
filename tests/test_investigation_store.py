import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from reconforge.cases import BANK_CASE_ID, CaseStore
from reconforge.investigation import (
    InvestigationRun,
    proposal_template,
    required_evidence,
    validate_proposal,
)
from reconforge.investigation_store import (
    InvestigationArtifactError,
    InvestigationArtifactStore,
)
from reconforge.reports import get_investigation_report


class InvestigationArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.case_store = CaseStore()
        self.case = self.case_store.get_case(BANK_CASE_ID)
        self.report = get_investigation_report(
            self.case_store,
            BANK_CASE_ID,
            self.case.case_version,
        )

        self.inspected = {
            evidence_id: self.case_store.get_evidence(
                BANK_CASE_ID,
                self.case.case_version,
                evidence_id,
            )
            for evidence_id in required_evidence(self.report)
        }

        proposal = validate_proposal(
            proposal_template(self.case, self.report),
            self.case,
            self.report,
            self.inspected,
        )

        self.run = InvestigationRun(
            mode="scripted_offline",
            requested_model=None,
            returned_models=(),
            proposal=proposal,
            report=self.report,
            model_turns=2,
            provider_requests=0,
            input_tokens=None,
            output_tokens=None,
            trace=(),
        )

    def make_store(self, directory: Path) -> InvestigationArtifactStore:
        return InvestigationArtifactStore(
            directory,
            application_version="test-version",
        )

    def test_save_and_get_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            created_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

            saved = store.save(
                self.run,
                run_id="run_" + "a" * 32,
                created_at=created_at,
            )
            loaded = store.get(saved.run_id)

            self.assertEqual(loaded, saved)
            self.assertEqual(loaded.run, self.run)
            self.assertEqual(loaded.run.proposal.case_version, self.case.case_version)
            self.assertEqual(loaded.run.proposal.report_id, self.report.report_id)
            self.assertEqual(loaded.application_version, "test-version")
            self.assertEqual(loaded.created_at, created_at)

    def test_save_creates_single_json_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            saved = store.save(
                self.run,
                run_id="run_" + "b" * 32,
                created_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            )

            files = sorted(Path(directory).glob("*.json"))

            self.assertEqual(files, [Path(directory) / f"{saved.run_id}.json"])

    def test_duplicate_run_id_is_rejected_without_replacing_existing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            run_id = "run_" + "c" * 32
            created_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

            first = store.save(
                self.run,
                run_id=run_id,
                created_at=created_at,
            )
            original = (Path(directory) / f"{run_id}.json").read_text(
                encoding="utf-8"
            )

            with self.assertRaises(InvestigationArtifactError):
                store.save(
                    self.run,
                    run_id=run_id,
                    created_at=created_at,
                )

            current = (Path(directory) / f"{run_id}.json").read_text(
                encoding="utf-8"
            )

            self.assertEqual(current, original)
            self.assertEqual(store.get(run_id), first)

    def test_integrity_digest_is_stable_for_same_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            run_id = "run_" + "d" * 32
            created_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

            first = store.save(
                self.run,
                run_id=run_id,
                created_at=created_at,
            )

            with self.assertRaises(InvestigationArtifactError):
                store.save(
                    self.run,
                    run_id=run_id,
                    created_at=created_at,
                )

            self.assertEqual(len(first.run_sha256), 64)
            self.assertRegex(first.run_sha256, r"^[0-9a-f]{64}$")

    def test_tampered_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            run_id = "run_" + "e" * 32

            store.save(
                self.run,
                run_id=run_id,
                created_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            )

            path = Path(directory) / f"{run_id}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["run_sha256"] = "0" * 64
            path.write_text(
                json.dumps(payload, sort_keys=True),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                InvestigationArtifactError,
                "SHA-256 integrity verification",
            ):
                store.get(run_id)

    def test_missing_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            with self.assertRaisesRegex(
                InvestigationArtifactError,
                "not found",
            ):
                store.get("run_" + "f" * 32)

    def test_invalid_run_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            for run_id in (
                "bad",
                "run_short",
                "run_" + "g" * 32,
                "run_" + "a" * 31,
            ):
                with self.subTest(run_id=run_id):
                    with self.assertRaisesRegex(
                        InvestigationArtifactError,
                        "Invalid investigation run ID",
                    ):
                        store.get(run_id)

    def test_malformed_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            run_id = "run_" + "1" * 32
            path = Path(directory) / f"{run_id}.json"
            path.write_text(
                '{"not": "an investigation artifact"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                InvestigationArtifactError,
                "invalid",
            ):
                store.get(run_id)

    def test_artifact_does_not_duplicate_raw_evidence_records(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            run_id = "run_" + "2" * 32

            store.save(
                self.run,
                run_id=run_id,
                created_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            )

            artifact_json = (
                Path(directory) / f"{run_id}.json"
            ).read_text(encoding="utf-8")

            for evidence_id, record in self.inspected.items():
                serialized_record = json.dumps(
                    record.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                self.assertNotIn(
                    serialized_record,
                    artifact_json,
                    msg=f"Raw evidence record {evidence_id} was duplicated.",
                )


if __name__ == "__main__":
    unittest.main()
