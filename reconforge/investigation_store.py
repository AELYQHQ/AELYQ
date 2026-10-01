"""Immutable filesystem storage for auditable investigation runs."""

import os
import re
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from typing import Annotated, Literal

from pydantic import Field, StrictStr

from . import __version__
from .cases import Digest, FrozenModel
from .investigation import InvestigationRun, canonical_json


RunId = Annotated[
    StrictStr,
    Field(
        min_length=36,
        max_length=36,
        pattern=r"^run_[0-9a-f]{32}$",
    ),
]


class InvestigationArtifactError(ValueError):
    """An investigation artifact is missing, invalid, duplicated, or tampered."""


class InvestigationArtifact(FrozenModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    run_id: RunId
    created_at: datetime
    application_version: StrictStr
    run_sha256: Digest
    run: InvestigationRun


def _unsigned_payload(
    *,
    run_id: str,
    created_at: datetime,
    application_version: str,
    run: InvestigationRun,
) -> dict:
    """Return the exact artifact fields covered by the integrity digest."""
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "application_version": application_version,
        "run": run.model_dump(mode="json"),
    }


def _artifact_digest(
    *,
    run_id: str,
    created_at: datetime,
    application_version: str,
    run: InvestigationRun,
) -> str:
    canonical = canonical_json(
        _unsigned_payload(
            run_id=run_id,
            created_at=created_at,
            application_version=application_version,
            run=run,
        )
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class InvestigationArtifactStore:
    """Write-once JSON artifacts for accepted investigation runs.

    The store is deliberately filesystem-backed for the current prototype.
    It does not copy source evidence rows; the run retains case/version and
    evidence identities so the original evidence boundary remains authoritative.
    """

    def __init__(
        self,
        directory: Path,
        *,
        application_version: str = __version__,
    ):
        self.directory = Path(directory)
        self.application_version = application_version
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        run: InvestigationRun,
        *,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> InvestigationArtifact:
        selected_run_id = run_id or f"run_{uuid4().hex}"
        selected_created_at = created_at or datetime.now(timezone.utc)

        if selected_created_at.tzinfo is None or selected_created_at.utcoffset() is None:
            raise InvestigationArtifactError("created_at must be timezone-aware.")

        digest = _artifact_digest(
            run_id=selected_run_id,
            created_at=selected_created_at,
            application_version=self.application_version,
            run=run,
        )

        artifact = InvestigationArtifact(
            run_id=selected_run_id,
            created_at=selected_created_at,
            application_version=self.application_version,
            run_sha256=digest,
            run=run,
        )

        target = self.directory / f"{artifact.run_id}.json"
        if target.exists():
            raise InvestigationArtifactError("An investigation run with this ID already exists.")

        payload = canonical_json(artifact.model_dump(mode="json")).encode("utf-8")

        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.directory,
                prefix=f".{artifact.run_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            # Hard-linking the completed temporary file makes publication
            # fail instead of replacing an existing artifact.
            try:
                os.link(temp_name, target)
            except FileExistsError as exc:
                raise InvestigationArtifactError(
                    "An investigation run with this ID already exists."
                ) from exc
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass

        return artifact

    def get(self, run_id: str) -> InvestigationArtifact:
        if not isinstance(run_id, str) or re.fullmatch(r"run_[0-9a-f]{32}", run_id) is None:
            raise InvestigationArtifactError("Invalid investigation run ID.")

        path = self.directory / f"{run_id}.json"
        if not path.is_file():
            raise InvestigationArtifactError("Investigation run not found.")

        try:
            data = path.read_text(encoding="utf-8")
            artifact = InvestigationArtifact.model_validate_json(data)
        except Exception as exc:
            raise InvestigationArtifactError("The investigation artifact is invalid.") from exc

        if artifact.run_id != run_id:
            raise InvestigationArtifactError("The artifact run ID does not match its requested ID.")

        if artifact.created_at.tzinfo is None or artifact.created_at.utcoffset() is None:
            raise InvestigationArtifactError("The investigation artifact timestamp is not timezone-aware.")

        expected = _artifact_digest(
            run_id=artifact.run_id,
            created_at=artifact.created_at,
            application_version=artifact.application_version,
            run=artifact.run,
        )
        if expected != artifact.run_sha256:
            raise InvestigationArtifactError(
                "The investigation artifact failed SHA-256 integrity verification."
            )

        return artifact
