"""Typed, immutable views of configured synthetic cases and their source rows."""

import csv
import json
from collections.abc import Mapping
from hashlib import sha256
from io import StringIO
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, TypeAdapter, ValidationError

from .reconciliation import InputError, SOURCE_FILES, reconcile_snapshots

CASE_ID = "case_invoice_deduction_001"
BANK_CASE_ID = "case_bank_shortfall_001"
TIMING_CASE_ID = "case_settlement_timing_001"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
FIXTURE = EXAMPLES / "invoice_deduction"
BANK_FIXTURE = EXAMPLES / "bank_shortfall"
TIMING_FIXTURE = EXAMPLES / "settlement_timing"
DEFAULT_FIXTURES = MappingProxyType({
    CASE_ID: FIXTURE,
    BANK_CASE_ID: BANK_FIXTURE,
    TIMING_CASE_ID: TIMING_FIXTURE,
})
MAX_CASES = 32
MAX_SOURCE_BYTES = 1_048_576
MAX_SOURCE_RECORDS = 1000

CaseId = Annotated[StrictStr, Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]
Digest = Annotated[StrictStr, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
EvidenceId = Annotated[StrictStr, Field(min_length=67, max_length=67, pattern=r"^ev_[0-9a-f]{64}$")]
RecordNumber = Annotated[StrictInt, Field(ge=1, le=MAX_SOURCE_RECORDS)]
SourceFile = Literal["ledger_events.csv", "psp_events.csv", "bank_entries.csv"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(FrozenModel):
    tenant_id: StrictStr
    merchant_id: StrictStr
    batch_id: StrictStr
    currency: Literal["EUR"]


class SourceReference(FrozenModel):
    file: SourceFile
    record_number: RecordNumber
    event_id: StrictStr
    sha256: Digest


class EvidenceReference(SourceReference):
    evidence_id: EvidenceId


class SourceSnapshot(FrozenModel):
    file: SourceFile
    sha256: Digest
    data_records: Annotated[StrictInt, Field(ge=1, le=MAX_SOURCE_RECORDS)]


class Difference(FrozenModel):
    kind: Literal["provider_event_absent_from_ledger", "ledger_event_absent_from_provider", "event_values_differ"]
    event_id: StrictStr
    ledger_amount_minor: StrictInt | None
    provider_amount_minor: StrictInt | None
    ledger_source: SourceReference | None
    provider_source: SourceReference | None


class Totals(FrozenModel):
    ledger: StrictInt
    provider: StrictInt
    bank: StrictInt


class Comparison(FrozenModel):
    residual_minor: StrictInt
    status: Literal["needs_review", "balanced_on_supplied_events", "balanced_by_total"]


class Comparisons(FrozenModel):
    ledger_to_provider: Comparison
    provider_to_bank: Comparison


class Facts(FrozenModel):
    schema_version: Literal["0.0.1"]
    mode: Literal["deterministic_fixture_comparison"]
    scope: Scope
    totals_minor: Totals
    comparisons: Comparisons
    event_differences: tuple[Difference, ...]
    source_snapshots: tuple[SourceSnapshot, ...]
    review_required: StrictBool
    external_completeness_verified: Literal[False]


class ReconciliationCase(FrozenModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    case_id: CaseId
    case_version: Digest
    data_classification: Literal["synthetic"] = "synthetic"
    read_only: Literal[True] = True
    facts: Facts
    evidence: tuple[EvidenceReference, ...]


class CaseSummary(FrozenModel):
    case_id: CaseId
    case_version: Digest
    review_required: StrictBool
    currency: Literal["EUR"] = "EUR"
    ledger_to_provider_residual_minor: StrictInt
    provider_to_bank_residual_minor: StrictInt


class CaseList(FrozenModel):
    cases: tuple[CaseSummary, ...]


class SourceRow(FrozenModel):
    tenant_id: StrictStr
    merchant_id: StrictStr
    batch_id: StrictStr
    event_id: StrictStr
    event_type: StrictStr
    amount_eur: StrictStr
    currency: Literal["EUR"]
    effective_at: StrictStr
    description: Annotated[StrictStr, Field(max_length=2048)]


class EvidenceRecord(FrozenModel):
    case_id: CaseId
    case_version: Digest
    reference: EvidenceReference
    row: SourceRow
    data_role: Literal["untrusted_source_data"] = "untrusted_source_data"


class UnknownCaseError(LookupError):
    pass


class UnknownEvidenceError(LookupError):
    pass


class CaseVersionMismatch(ValueError):
    pass


class CaseStore:
    """Load once at startup; all reads use this snapshot until process restart.

    Directories and case IDs are operator configuration, never client paths.
    Only the three allow-listed CSV names are read. Case IDs and evidence IDs
    are looked up in memory, never used to construct a filesystem path.
    Every configured case is visible to local callers; this is not authorization.
    """

    def __init__(
        self, directory: Path | None = None, *, fixtures: Mapping[str, Path] | None = None,
    ):
        if directory is not None and fixtures is not None:
            raise InputError("Supply a directory or a fixture catalogue, not both.")
        if directory is not None:
            selected = {CASE_ID: directory}
        elif fixtures is not None:
            selected = fixtures
        else:
            selected = DEFAULT_FIXTURES
        if not 1 <= len(selected) <= MAX_CASES:
            raise InputError(f"The fixture catalogue must contain 1 to {MAX_CASES} cases.")
        configured = dict(selected)
        adapter = TypeAdapter(CaseId)
        for case_id in configured:
            try:
                adapter.validate_python(case_id)
            except ValidationError as exc:
                raise InputError("Invalid configured case ID.") from exc

        cases = {}
        records = {}
        for case_id in sorted(configured):
            case, evidence = _capture_case(case_id, Path(configured[case_id]))
            cases[case_id] = case
            records[case_id] = MappingProxyType(evidence)
        # Publish the store only after every configured case has validated.
        self._cases = MappingProxyType(cases)
        self._records = MappingProxyType(records)

    def list_cases(self) -> CaseList:
        return CaseList(cases=tuple(CaseSummary(
            case_id=case.case_id, case_version=case.case_version,
            review_required=case.facts.review_required,
            ledger_to_provider_residual_minor=case.facts.comparisons.ledger_to_provider.residual_minor,
            provider_to_bank_residual_minor=case.facts.comparisons.provider_to_bank.residual_minor,
        ) for case in self._cases.values()))

    def get_case(self, case_id: str) -> ReconciliationCase:
        if case_id not in self._cases:
            raise UnknownCaseError("Unknown case ID.")
        return self._cases[case_id]

    def get_evidence(self, case_id: str, case_version: str, evidence_id: str) -> EvidenceRecord:
        case = self.get_case(case_id)
        if case_version != case.case_version:
            raise CaseVersionMismatch("Case version changed; retrieve the case again.")
        records = self._records[case_id]
        if evidence_id not in records:
            raise UnknownEvidenceError("Unknown evidence ID for this case.")
        return records[evidence_id]


def _capture_case(case_id: str, directory: Path) -> tuple[ReconciliationCase, dict[str, EvidenceRecord]]:
    """Capture one batch; calculations and evidence consume the same bytes."""
    snapshots = {}
    for filename in SOURCE_FILES:
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            raise InputError(f"{filename}: expected a regular fixture file.")
        with path.open("rb") as handle:
            content = handle.read(MAX_SOURCE_BYTES + 1)
        if len(content) > MAX_SOURCE_BYTES:
            raise InputError(f"{filename}: exceeds the fixture size limit.")
        snapshots[filename] = content

    raw_facts = reconcile_snapshots(snapshots)
    if any(s["data_records"] > MAX_SOURCE_RECORDS for s in raw_facts["source_snapshots"]):
        raise InputError("A source exceeds the fixture record limit.")
    facts = Facts.model_validate(raw_facts)
    canonical = json.dumps(
        {"case_id": case_id, "case_schema_version": "0.1.0", "facts": raw_facts},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    version = sha256(canonical).hexdigest()

    records = {}
    for filename in SOURCE_FILES:
        content = snapshots[filename]
        digest = sha256(content).hexdigest()
        reader = csv.DictReader(StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        for record_number, row in enumerate(reader, 1):
            identity = json.dumps(
                [filename, digest, record_number, row["event_id"]], separators=(",", ":")
            ).encode("utf-8")
            reference = EvidenceReference(
                file=filename, record_number=record_number, event_id=row["event_id"],
                sha256=digest, evidence_id="ev_" + sha256(identity).hexdigest(),
            )
            records[reference.evidence_id] = EvidenceRecord(
                case_id=case_id, case_version=version, reference=reference,
                row=SourceRow.model_validate(row),
            )
    case = ReconciliationCase(
        case_id=case_id, case_version=version, facts=facts,
        evidence=tuple(record.reference for record in records.values()),
    )
    return case, records
