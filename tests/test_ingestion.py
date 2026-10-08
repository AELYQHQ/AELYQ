"""Offline acceptance tests for normalized batch intake."""

import tempfile
import unittest
from pathlib import Path

from reconforge.ingestion import MAX_SOURCE_BYTES, stage_directory
from reconforge.reconciliation import InputError, SOURCE_FILES


class IngestionTests(unittest.TestCase):
    FIXTURE = Path("examples/invoice_deduction")

    def test_reuses_existing_financial_core_and_keeps_exact_bytes(self):
        staged = stage_directory(self.FIXTURE)
        again = stage_directory(self.FIXTURE)
        self.assertEqual(staged.ingestion_id, again.ingestion_id)
        self.assertEqual(len(staged.sources), 3)
        self.assertTrue(staged.ingestion_id.startswith("ingestion_"))
        self.assertEqual(staged.reconciliation["review_required"], True)
        self.assertEqual(tuple(staged.snapshots), tuple(SOURCE_FILES))
        self.assertEqual(
            staged.snapshots["ledger_events.csv"],
            (self.FIXTURE / "ledger_events.csv").read_bytes(),
        )
        self.assertNotIn("snapshots", staged.as_dict())

    def test_changes_to_source_bytes_change_ingestion_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for filename in SOURCE_FILES:
                (root / filename).write_bytes((self.FIXTURE / filename).read_bytes())
            first = stage_directory(root)
            path = root / "ledger_events.csv"
            path.write_bytes(path.read_bytes() + b"\n")
            second = stage_directory(root)
            self.assertNotEqual(first.ingestion_id, second.ingestion_id)

    def test_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(InputError):
                stage_directory(Path(temporary))

    def test_rejects_oversized_source_before_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for filename in SOURCE_FILES:
                (root / filename).write_bytes((self.FIXTURE / filename).read_bytes())
            (root / "ledger_events.csv").write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
            with self.assertRaisesRegex(InputError, "limit"):
                stage_directory(root)

    def test_rejects_symlinked_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for filename in SOURCE_FILES:
                if filename != "ledger_events.csv":
                    (root / filename).write_bytes((self.FIXTURE / filename).read_bytes())
            (root / "ledger_events.csv").symlink_to(
                self.FIXTURE.resolve() / "ledger_events.csv"
            )
            with self.assertRaisesRegex(InputError, "symbolic links"):
                stage_directory(root)


if __name__ == "__main__":
    unittest.main()
