"""Read-only intake of normalized, three-source reconciliation CSV batches.

This stage preserves the exact bytes submitted for deterministic validation and
future evidence processing. It does not register cases, upload data, or post funds.
"""

import argparse
import json
import os
import stat
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .reconciliation import InputError, SOURCE_FILES, reconcile_snapshots

# Keep this stage within the existing CaseStore source-size boundary.
MAX_SOURCE_BYTES = 1_048_576


@dataclass(frozen=True)
class SourceReceipt:
    filename: str
    size_bytes: int
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class StagedBatch:
    """Immutable receipt, deterministic facts, and captured source snapshots.

    snapshots is retained in memory, never included in JSON output.
    Its bytes must be used for any subsequent evidence/case registration rather
    than re-reading paths, which might have changed in the meantime.
    """

    ingestion_id: str
    sources: tuple[SourceReceipt, ...]
    reconciliation: dict
    snapshots: Mapping[str, bytes] = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "input_format": "reconforge_normalized_csv_v1",
            "ingestion_id": self.ingestion_id,
            "sources": [source.as_dict() for source in self.sources],
            "reconciliation": self.reconciliation,
        }


def _read_regular_file(path: Path, filename: str) -> bytes:
    """Capture no more than MAX_SOURCE_BYTES + 1 bytes from one regular file."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        if path.is_symlink():
            raise InputError(f"{filename}: symbolic links are not accepted.")
        descriptor = os.open(path, flags)
    except InputError:
        raise
    except OSError as exc:
        raise InputError(f"{filename}: source cannot be opened ({exc.strerror}).") from exc

    try:
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise InputError(f"{filename}: expected a regular file.")
            content = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise InputError(f"{filename}: source cannot be read ({exc.strerror}).") from exc

    if len(content) > MAX_SOURCE_BYTES:
        raise InputError(
            f"{filename}: source exceeds the {MAX_SOURCE_BYTES}-byte intake limit."
        )
    return content


def stage_directory(directory: Path | str) -> StagedBatch:
    """Validate a new normalized batch from one capture of each input file.

    This stage is deliberately independent of the fixed case catalogue. Only
    reconciliation facts, not model-generated decisions, determine validity.
    """
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise InputError("Batch input must be a real, existing directory.")

    source_names = tuple(SOURCE_FILES)
    if source_names != (
        "ledger_events.csv", "psp_events.csv", "bank_entries.csv"
    ):
        raise InputError("Unexpected normalized source-file contract.")

    snapshots: dict[str, bytes] = {}
    sources: list[SourceReceipt] = []
    for filename in source_names:
        raw = _read_regular_file(root / filename, filename)
        snapshots[filename] = raw
        sources.append(
            SourceReceipt(
                filename=filename,
                size_bytes=len(raw),
                sha256=sha256(raw).hexdigest(),
            )
        )

    # This invokes the existing strict schema, scope and financial validation.
    facts = reconcile_snapshots(snapshots)

    # Stable identity incorporates the filename to prevent cross-source swaps.
    digest_input = "\n".join(
        f"{entry.filename}:{entry.sha256}" for entry in sources
    ).encode("ascii")
    ingestion_id = "ingestion_" + sha256(digest_input).hexdigest()

    return StagedBatch(
        ingestion_id=ingestion_id,
        sources=tuple(sources),
        reconciliation=facts,
        snapshots=MappingProxyType(snapshots),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and preview a normalized three-source reconciliation batch."
    )
    parser.add_argument("directory", type=Path, help="Directory containing the three CSV files")
    parser.add_argument("--json", action="store_true", help="Print the full JSON receipt and reconciliation")
    args = parser.parse_args()

    try:
        staged = stage_directory(args.directory)
    except InputError as exc:
        parser.exit(2, f"Batch rejected: {exc}\n")

    if args.json:
        print(json.dumps(staged.as_dict(), indent=2, ensure_ascii=False))
    else:
        print("Normalized batch accepted for deterministic review.")
        print(f"Ingestion ID: {staged.ingestion_id}")
        for source in staged.sources:
            print(f"  {source.filename}: {source.size_bytes} bytes, SHA-256 {source.sha256}")
        print("No data was persisted or posted; completeness is not established.")


if __name__ == "__main__":
    main()
