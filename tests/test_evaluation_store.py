import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from reconforge.cases import BANK_CASE_ID
from reconforge.evaluation import build_benchmark, evaluate_repeatability
from reconforge.evaluation_store import (
    EvaluationArtifactError,
    EvaluationArtifactStore,
)
from reconforge.investigator import run_mcp_investigation


class EvaluationArtifactStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.investigation_run = asyncio.run(
            run_mcp_investigation(BANK_CASE_ID)
        )
        cls.benchmark = build_benchmark((cls.investigation_run,))
        cls.repeatability = evaluate_repeatability(
            (cls.investigation_run, cls.investigation_run)
        )

    def make_store(self, directory: Path) -> EvaluationArtifactStore:
        return EvaluationArtifactStore(
            directory,
            application_version="test-version",
        )

    def test_save_and_get_benchmark_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            created_at = datetime(
                2026, 10, 4, 12, 0, tzinfo=timezone.utc
            )

            saved = store.save(
                self.benchmark,
                evaluation_id="evaluation_" + "a" * 32,
                created_at=created_at,
            )

            loaded = store.get(saved.evaluation_id)

            self.assertEqual(loaded, saved)
            self.assertEqual(loaded.result, self.benchmark)
            self.assertEqual(loaded.artifact_type, "benchmark")
            self.assertEqual(
                loaded.application_version,
                "test-version",
            )
            self.assertEqual(loaded.created_at, created_at)
            self.assertEqual(len(loaded.result_sha256), 64)

    def test_save_and_get_repeatability_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            saved = store.save(
                self.repeatability,
                evaluation_id="evaluation_" + "b" * 32,
                created_at=datetime(
                    2026, 10, 4, 13, 0,
                    tzinfo=timezone.utc,
                ),
            )

            loaded = store.get(saved.evaluation_id)

            self.assertEqual(loaded.result, self.repeatability)
            self.assertEqual(
                loaded.artifact_type,
                "repeatability",
            )

    def test_duplicate_id_is_rejected_without_replacing_existing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            evaluation_id = "evaluation_" + "c" * 32
            created_at = datetime(
                2026, 10, 4, 12, 0,
                tzinfo=timezone.utc,
            )

            first = store.save(
                self.benchmark,
                evaluation_id=evaluation_id,
                created_at=created_at,
            )

            path = Path(directory) / f"{evaluation_id}.json"
            original = path.read_text(encoding="utf-8")

            with self.assertRaises(EvaluationArtifactError):
                store.save(
                    self.repeatability,
                    evaluation_id=evaluation_id,
                    created_at=created_at,
                )

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                original,
            )
            self.assertEqual(
                store.get(evaluation_id),
                first,
            )

    def test_tampered_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            evaluation_id = "evaluation_" + "d" * 32

            store.save(
                self.benchmark,
                evaluation_id=evaluation_id,
                created_at=datetime(
                    2026, 10, 4, 12, 0,
                    tzinfo=timezone.utc,
                ),
            )

            path = Path(directory) / f"{evaluation_id}.json"
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
            payload["result_sha256"] = "0" * 64

            path.write_text(
                json.dumps(payload, sort_keys=True),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                EvaluationArtifactError,
                "SHA-256 integrity verification",
            ):
                store.get(evaluation_id)

    def test_invalid_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            for evaluation_id in (
                "bad",
                "evaluation_short",
                "evaluation_" + "g" * 32,
                "evaluation_" + "a" * 31,
            ):
                with self.subTest(
                    evaluation_id=evaluation_id
                ):
                    with self.assertRaisesRegex(
                        EvaluationArtifactError,
                        "Invalid evaluation ID",
                    ):
                        store.get(evaluation_id)

    def test_naive_created_at_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            with self.assertRaisesRegex(
                EvaluationArtifactError,
                "timezone-aware",
            ):
                store.save(
                    self.benchmark,
                    evaluation_id="evaluation_" + "e" * 32,
                    created_at=datetime(
                        2026, 10, 4, 12, 0
                    ),
                )

    def test_list_all_and_list_for_case_return_verified_artifacts_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))

            older = store.save(
                self.repeatability,
                evaluation_id="evaluation_" + "f" * 32,
                created_at=datetime(
                    2026, 10, 4, 12, 0,
                    tzinfo=timezone.utc,
                ),
            )

            newer = store.save(
                self.benchmark,
                evaluation_id="evaluation_" + "1" * 32,
                created_at=datetime(
                    2026, 10, 4, 13, 0,
                    tzinfo=timezone.utc,
                ),
            )

            self.assertEqual(
                tuple(
                    item.evaluation_id
                    for item in store.list_all()
                ),
                (
                    newer.evaluation_id,
                    older.evaluation_id,
                ),
            )

            self.assertEqual(
                tuple(
                    item.evaluation_id
                    for item in store.list_for_case(
                        BANK_CASE_ID
                    )
                ),
                (
                    newer.evaluation_id,
                    older.evaluation_id,
                ),
            )

            self.assertEqual(
                store.list_for_case("case_not_present"),
                (),
            )

    def test_malformed_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            evaluation_id = "evaluation_" + "2" * 32
            path = Path(directory) / f"{evaluation_id}.json"

            path.write_text(
                '{"not": "an evaluation artifact"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                EvaluationArtifactError,
                "invalid",
            ):
                store.get(evaluation_id)


if __name__ == "__main__":
    unittest.main()
