"""Operator-controlled, synthetic-only registration of immutable normalized batches.

This is a local prototype, NOT an authenticated customer-data intake service.
Neither an API nor an MCP caller can register/modify a case.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .cases import CaseStore, DEFAULT_FIXTURES, MAX_CASES
from .ingestion import StagedBatch, stage_directory
from .reconciliation import InputError, SOURCE_FILES

DEFAULT_REGISTRY = Path('.aelyq/imported_cases')
SCHEMA_VERSION = '0.1.0'
CASE_PREFIX = 'case_import_'


class ImportRegistrationError(ValueError):
    """The immutable registry is unavailable, damaged, or inconsistent."""


@dataclass(frozen=True)
class RegisteredCase:
    case_id: str
    ingestion_id: str
    created: bool
    case_version: str | None = None

    def as_dict(self) -> dict:
        return {
            'case_id': self.case_id,
            'ingestion_id': self.ingestion_id,
            'created': self.created,
            'case_version': self.case_version,
            'data_classification': 'synthetic',
        }


def _case_id(staged: StagedBatch) -> str:
    # Full 256-bit digest fits CaseId's 80-character limit; avoids truncated IDs.
    suffix = staged.ingestion_id.removeprefix('ingestion_')
    if len(suffix) != 64 or any(c not in '0123456789abcdef' for c in suffix):
        raise ImportRegistrationError('Invalid staged ingestion identity.')
    return CASE_PREFIX + suffix


def _validate_registry(root: Path, *, create: bool) -> Path:
    root = Path(root)
    if root.is_symlink():
        raise ImportRegistrationError('Registry must not be a symbolic link.')
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ImportRegistrationError('Registry directory does not exist.')
    return root


def _manifest_for(staged: StagedBatch, case_id: str) -> dict:
    return {
        'schema_version': SCHEMA_VERSION,
        'case_id': case_id,
        'ingestion_id': staged.ingestion_id,
        'data_classification': 'synthetic',
        'sources': [entry.as_dict() for entry in staged.sources],
    }


def _validate_entry(path: Path) -> dict:
    if path.is_symlink() or not path.is_dir():
        raise ImportRegistrationError('Imported case entry must be a real directory.')
    if not path.name.startswith(CASE_PREFIX):
        raise ImportRegistrationError('Invalid imported case name.')
    manifest_path = path / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ImportRegistrationError(f'{path.name}: missing or linked manifest.')
    try:
        # Bound the operator manifest; source files are separately bounded by stage_directory.
        if manifest_path.stat().st_size > 8192:
            raise ImportRegistrationError(f'{path.name}: oversized manifest.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        staged = stage_directory(path)
    except (OSError, ValueError, UnicodeError, InputError) as exc:
        raise ImportRegistrationError(f'{path.name}: corrupt or invalid registered batch.') from exc
    expected = _manifest_for(staged, _case_id(staged))
    if path.name != expected['case_id'] or manifest != expected:
        raise ImportRegistrationError(f'{path.name}: identity or source hash mismatch.')
    return manifest


@contextmanager
def _write_lock(root: Path) -> Iterator[None]:
    # macOS/Linux: flock prevents two collaborating registrars racing for a case.
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    file_path = root / '.register.lock'
    try:
        fd = os.open(file_path, flags, 0o600)
    except OSError as exc:
        raise ImportRegistrationError('Cannot open registry lock.') from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ImportRegistrationError('Registry lock is not a regular file.')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def register_batch(
    source_directory: Path | str,
    *,
    registry_directory: Path | str = DEFAULT_REGISTRY,
    synthetic_test_data: bool = False,
) -> RegisteredCase:
    """Capture and atomically register a *synthetic* normalized batch once.

    Source contents are read once by stage_directory; the exact captured bytes
    are persisted. Registration never reruns the ingestion read on source paths.
    """
    if not synthetic_test_data:
        raise ImportRegistrationError(
            'This unauthenticated prototype accepts synthetic test data only; '
            'pass synthetic_test_data=True after verifying the input.'
        )
    staged = stage_directory(source_directory)
    case_id = _case_id(staged)
    root = _validate_registry(Path(registry_directory), create=True)
    target = root / case_id
    expected = _manifest_for(staged, case_id)

    with _write_lock(root):
        if target.exists() or target.is_symlink():
            if _validate_entry(target) != expected:
                raise ImportRegistrationError('Existing case identity conflicts with staged bytes.')
            store = CaseStore(fixtures={case_id: target})
            return RegisteredCase(case_id, staged.ingestion_id, False,
                                  store.get_case(case_id).case_version)

        with tempfile.TemporaryDirectory(prefix='.pending-', dir=root) as temp:
            pending = Path(temp)
            for filename in SOURCE_FILES:
                with (pending / filename).open('xb') as output:
                    output.write(staged.snapshots[filename])
                    output.flush()
                    os.fsync(output.fileno())
            with (pending / 'manifest.json').open('x', encoding='utf-8') as output:
                json.dump(expected, output, sort_keys=True, separators=(',', ':'))
                output.flush()
                os.fsync(output.fileno())

            # Validate persisted snapshot before publication, including the normal
            # case/evidence model and report-compatible source row contracts.
            _validate_entry_preview(pending, expected)
            temp_store = CaseStore(fixtures={case_id: pending})
            case_version = temp_store.get_case(case_id).case_version
            os.rename(pending, target)
            # TemporaryDirectory cleanup won't remove renamed target.
            fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    return RegisteredCase(case_id, staged.ingestion_id, True, case_version)


def _validate_entry_preview(path: Path, expected: dict) -> None:
    # Pending dirs are intentionally not named case_import_<digest>.
    try:
        staged = stage_directory(path)
        current = json.loads((path / 'manifest.json').read_text('utf-8'))
    except (OSError, ValueError, InputError) as exc:
        raise ImportRegistrationError('Pending registry snapshot failed validation.') from exc
    if current != expected or _manifest_for(staged, _case_id(staged)) != expected:
        raise ImportRegistrationError('Pending registry snapshot identity mismatch.')


def imported_fixtures(
    registry_directory: Path | str = DEFAULT_REGISTRY,
) -> dict[str, Path]:
    """Discover only previously registered cases, refusing partial/corrupt entries."""
    root = _validate_registry(Path(registry_directory), create=True)
    fixtures = {}
    for entry in sorted(root.iterdir()):
        if entry.name.startswith('.pending-'):
            # Crashed, uncommitted temporary staging is never published.
            continue
        if entry.name.startswith(CASE_PREFIX):
            _validate_entry(entry)
            fixtures[entry.name] = entry
    return fixtures


def open_case_store(
    registry_directory: Path | str = DEFAULT_REGISTRY,
    *,
    include_examples: bool = True,
) -> CaseStore:
    """Open an immutable API/MCP-ready CaseStore from the selected registry."""
    fixtures = dict(DEFAULT_FIXTURES) if include_examples else {}
    imported = imported_fixtures(registry_directory)
    if len(fixtures) + len(imported) > MAX_CASES:
        raise ImportRegistrationError(f'Maximum combined case count is {MAX_CASES}.')
    for case_id, path in imported.items():
        if case_id in fixtures:
            raise ImportRegistrationError('Imported case collides with a configured example.')
        fixtures[case_id] = path
    if not fixtures:
        raise ImportRegistrationError('No cases have been registered.')
    return CaseStore(fixtures=fixtures)


def main() -> None:
    parser = argparse.ArgumentParser(description='Register synthetic normalized batches as read-only cases.')
    parser.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY,
                        help='Operator-owned local registry directory.')
    commands = parser.add_subparsers(dest='command', required=True)
    registration = commands.add_parser('register', help='Register one normalized batch.')
    registration.add_argument('directory', type=Path)
    registration.add_argument('--synthetic-test-data', action='store_true', required=False,
                              help='Confirm the input contains synthetic test data only.')
    commands.add_parser('list', help='List registered case IDs (not default examples).')
    try:
        args = parser.parse_args()
        if args.command == 'register':
            result = register_batch(args.directory, registry_directory=args.registry,
                                    synthetic_test_data=args.synthetic_test_data)
            print(json.dumps(result.as_dict(), indent=2))
        else:
            print(json.dumps({'cases': sorted(imported_fixtures(args.registry))}, indent=2))
    except (ImportRegistrationError, InputError) as exc:
        parser.exit(2, f'Import rejected: {exc}\n')


if __name__ == '__main__':
    main()
