"""Immutable storage for descriptive investigation evaluation artifacts."""

import os
import re
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from . import __version__
from .cases import Digest, FrozenModel
from .evaluation import (
    InvestigationBenchmark,
    InvestigationMultiCaseRepeatability,
    InvestigationRepeatability,
)
from .investigation import canonical_json


class EvaluationArtifactError(ValueError):
    """An evaluation artifact could not be created, loaded, or verified."""


class EvaluationArtifact(FrozenModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    evaluation_id: str
    created_at: datetime
    application_version: str
    artifact_type: Literal[
    "benchmark",
    "repeatability",
    "multi_case_repeatability",
]
    result: InvestigationBenchmark | InvestigationRepeatability | InvestigationMultiCaseRepeatability
    result_sha256: Digest


def _result_type(
    result: InvestigationBenchmark | InvestigationRepeatability | InvestigationMultiCaseRepeatability,
) -> str:
    if isinstance(result, InvestigationBenchmark):
        return "benchmark"
    if isinstance(result, InvestigationRepeatability):
        return "repeatability"
    if isinstance(result, InvestigationMultiCaseRepeatability):
        return "multi_case_repeatability"
    raise EvaluationArtifactError("Unsupported evaluation result type.")


def _unsigned_payload(
    *,
    evaluation_id: str,
    created_at: datetime,
    application_version: str,
    artifact_type: str,
    result: InvestigationBenchmark | InvestigationRepeatability | InvestigationMultiCaseRepeatability,
) -> dict:
    """Return the exact artifact fields covered by the integrity digest."""
    return {
        "schema_version": "0.1.0",
        "evaluation_id": evaluation_id,
        "created_at": created_at.isoformat(),
        "application_version": application_version,
        "artifact_type": artifact_type,
        "result": result.model_dump(mode="json"),
    }


def _artifact_digest(
    *,
    evaluation_id: str,
    created_at: datetime,
    application_version: str,
    artifact_type: str,
    result: InvestigationBenchmark | InvestigationRepeatability | InvestigationMultiCaseRepeatability,
) -> str:
    canonical = canonical_json(
        _unsigned_payload(
            evaluation_id=evaluation_id,
            created_at=created_at,
            application_version=application_version,
            artifact_type=artifact_type,
            result=result,
        )
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class EvaluationArtifactStore:
    """Write-once JSON artifacts for descriptive evaluation results."""

    _ID_PATTERN = re.compile(r"evaluation_[0-9a-f]{32}")

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
        result: InvestigationBenchmark | InvestigationRepeatability | InvestigationMultiCaseRepeatability,
        *,
        evaluation_id: str | None = None,
        created_at: datetime | None = None,
    ) -> EvaluationArtifact:
        selected_id = evaluation_id or f"evaluation_{uuid4().hex}"
        selected_created_at = created_at or datetime.now(timezone.utc)

        if self._ID_PATTERN.fullmatch(selected_id) is None:
            raise EvaluationArtifactError("Invalid evaluation ID.")

        if (
            selected_created_at.tzinfo is None
            or selected_created_at.utcoffset() is None
        ):
            raise EvaluationArtifactError(
                "created_at must be timezone-aware."
            )

        artifact_type = _result_type(result)

        digest = _artifact_digest(
            evaluation_id=selected_id,
            created_at=selected_created_at,
            application_version=self.application_version,
            artifact_type=artifact_type,
            result=result,
        )

        artifact = EvaluationArtifact(
            evaluation_id=selected_id,
            created_at=selected_created_at,
            application_version=self.application_version,
            artifact_type=artifact_type,
            result=result,
            result_sha256=digest,
        )

        target = self.directory / f"{artifact.evaluation_id}.json"

        if target.exists():
            raise EvaluationArtifactError(
                "An evaluation artifact with this ID already exists."
            )

        payload = canonical_json(
            artifact.model_dump(mode="json")
        ).encode("utf-8")

        temp_name: str | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.directory,
                prefix=f".{artifact.evaluation_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            try:
                os.link(temp_name, target)
            except FileExistsError as exc:
                raise EvaluationArtifactError(
                    "An evaluation artifact with this ID already exists."
                ) from exc

        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass

        return artifact

    def get(self, evaluation_id: str) -> EvaluationArtifact:
        if (
            not isinstance(evaluation_id, str)
            or self._ID_PATTERN.fullmatch(evaluation_id) is None
        ):
            raise EvaluationArtifactError("Invalid evaluation ID.")

        path = self.directory / f"{evaluation_id}.json"

        if not path.is_file():
            raise EvaluationArtifactError(
                "Evaluation artifact not found."
            )

        try:
            artifact = EvaluationArtifact.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise EvaluationArtifactError(
                "The evaluation artifact is invalid."
            ) from exc

        if artifact.evaluation_id != evaluation_id:
            raise EvaluationArtifactError(
                "The artifact evaluation ID does not match its requested ID."
            )

        if (
            artifact.created_at.tzinfo is None
            or artifact.created_at.utcoffset() is None
        ):
            raise EvaluationArtifactError(
                "The evaluation artifact timestamp is not timezone-aware."
            )

        if _result_type(artifact.result) != artifact.artifact_type:
            raise EvaluationArtifactError(
                "The evaluation artifact type does not match its result."
            )

        expected = _artifact_digest(
            evaluation_id=artifact.evaluation_id,
            created_at=artifact.created_at,
            application_version=artifact.application_version,
            artifact_type=artifact.artifact_type,
            result=artifact.result,
        )

        if expected != artifact.result_sha256:
            raise EvaluationArtifactError(
                "The evaluation artifact failed SHA-256 integrity verification."
            )

        return artifact

    def list_all(self) -> tuple[EvaluationArtifact, ...]:
        """Return every verified evaluation artifact, newest first."""
        artifacts = [
            self.get(path.stem)
            for path in self.directory.glob("evaluation_*.json")
        ]

        return tuple(
            sorted(
                artifacts,
                key=lambda artifact: (
                    artifact.created_at,
                    artifact.evaluation_id,
                ),
                reverse=True,
            )
        )

    def list_for_case(
        self,
        case_id: str,
    ) -> tuple[EvaluationArtifact, ...]:
        """Return verified evaluation artifacts containing the selected case."""
        matches: list[EvaluationArtifact] = []

        for artifact in self.list_all():
            if artifact.artifact_type == "benchmark":
                case_ids = {
                    item.case_id
                    for item in artifact.result.evaluations
                }
                if case_id in case_ids:
                    matches.append(artifact)

            elif artifact.result.case_id == case_id:
                matches.append(artifact)

        return tuple(matches)
