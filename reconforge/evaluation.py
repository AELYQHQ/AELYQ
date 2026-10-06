"""Objective measurements for accepted ReconForge investigation runs.

This module intentionally does not produce an aggregate model-quality score.
It measures contract/evidence properties and agreement with an explicit
reference ordering. Matching that ordering is not treated as proof that the
model chose the best priorities.
"""
from collections import Counter
from datetime import datetime, timezone
from . import __version__
from .cases import CaseId, Digest, FrozenModel
from datetime import datetime, timezone
from platform import python_version
from time import perf_counter
from typing import Literal

from pydantic import Field, StrictInt

from .cases import FrozenModel
from .investigation import InvestigationRun, required_evidence


class InvestigationEvaluation(FrozenModel):
    """Reproducible measurements for one accepted investigation run."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    evaluated_at: str
    python_runtime: str
    mode: Literal["scripted_offline", "openai_live", "anthropic_live"]
    requested_model: str | None
    returned_models: tuple[str, ...]
    elapsed_seconds: float = Field(ge=0.0)
    contract_passed: bool
    case_context_matches: bool
    required_evidence_coverage: float = Field(ge=0.0, le=1.0)
    extra_evidence_count: StrictInt = Field(ge=0)
    hypothesis_order_matches_reference: bool
    question_order_matches_reference: bool
    next_step_order_matches_reference: bool
    quality_claim: Literal["not_established"] = "not_established"

def evaluate_run(
    run: InvestigationRun,
    *,
    elapsed_seconds: float = 0.0,
) -> InvestigationEvaluation:
    """Measure an accepted run without claiming that its priorities are optimal.

    The reference ordering is the deterministic ordering already present in the
    verified report. Agreement is reported only as agreement with that explicit
    reference; it is not an AI-quality score.

    ``elapsed_seconds`` is supplied by the caller because timing belongs to the
    execution boundary, not the immutable investigation result itself.
    """

    if type(elapsed_seconds) not in (int, float) or elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be a non-negative number.")

    proposal = run.proposal
    report = run.report.report

    required = required_evidence(run.report)
    cited = set(proposal.evidence_ids)
    coverage = 1.0 if not required else len(required & cited) / len(required)

    return InvestigationEvaluation(
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        python_runtime=python_version(),
        mode=run.mode,
        requested_model=run.requested_model,
        returned_models=run.returned_models,
        elapsed_seconds=float(elapsed_seconds),
        contract_passed=run.contract_status == "passed",
        case_context_matches=(
            proposal.case_id == report.case_id
            and proposal.case_version == report.case_version
            and proposal.report_id == run.report.report_id
        ),
        required_evidence_coverage=coverage,
        extra_evidence_count=len(cited - required),
        hypothesis_order_matches_reference=(
            proposal.hypothesis_order == tuple(item.code for item in report.hypotheses)
        ),
        question_order_matches_reference=(
            proposal.question_order == tuple(item.code for item in report.unresolved_questions)
        ),
        next_step_order_matches_reference=(
            proposal.next_step_order == tuple(item.code for item in report.next_steps)
        ),
    )

class InvestigationEvaluationSummary(FrozenModel):
    "Aggregate objective measurements without creating a model-quality score."

    schema_version: Literal["0.1.0"] = "0.1.0"
    run_count: StrictInt = Field(ge=1)
    contract_pass_count: StrictInt = Field(ge=0)
    case_context_match_count: StrictInt = Field(ge=0)
    mean_required_evidence_coverage: float = Field(ge=0.0, le=1.0)
    total_extra_evidence_count: StrictInt = Field(ge=0)
    hypothesis_order_match_rate: float = Field(ge=0.0, le=1.0)
    question_order_match_rate: float = Field(ge=0.0, le=1.0)
    next_step_order_match_rate: float = Field(ge=0.0, le=1.0)
    quality_claim: Literal["not_established"] = "not_established"


class InvestigationBenchmarkItem(FrozenModel):
    """One identified run within a reproducible benchmark."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    case_id: CaseId
    case_version: Digest
    mode: Literal["scripted_offline", "openai_live", "anthropic_live"]
    requested_model: str | None
    evaluation: InvestigationEvaluation


class InvestigationBenchmark(FrozenModel):
    """A reproducible collection of descriptive investigation measurements."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    generated_at: datetime
    application_version: str
    evaluations: tuple[InvestigationBenchmarkItem, ...] = Field(min_length=1)
    summary: InvestigationEvaluationSummary
    quality_claim: Literal["not_established"] = "not_established"

class InvestigationRepeatability(FrozenModel):
    """Descriptive consistency measurements across repeated runs."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    case_id: CaseId
    case_version: Digest
    mode: Literal["scripted_offline", "openai_live", "anthropic_live"]
    requested_model: str | None

    run_count: StrictInt = Field(ge=2)
    contract_pass_count: StrictInt = Field(ge=0)
    case_context_match_count: StrictInt = Field(ge=0)

    distinct_evidence_selections: StrictInt = Field(ge=1)
    distinct_hypothesis_orders: StrictInt = Field(ge=1)
    distinct_question_orders: StrictInt = Field(ge=1)
    distinct_next_step_orders: StrictInt = Field(ge=1)

    evidence_selection_agreement: float = Field(ge=0.0, le=1.0)
    hypothesis_order_agreement: float = Field(ge=0.0, le=1.0)
    question_order_agreement: float = Field(ge=0.0, le=1.0)
    next_step_order_agreement: float = Field(ge=0.0, le=1.0)

    quality_claim: Literal["not_established"] = "not_established"

def summarize_evaluations(
    evaluations: tuple[InvestigationEvaluation, ...],
) -> InvestigationEvaluationSummary:
    "Summarize multiple evaluations using descriptive measurements only."
    if not evaluations:
        raise ValueError("At least one investigation evaluation is required.")

    run_count = len(evaluations)

    return InvestigationEvaluationSummary(
        run_count=run_count,
        contract_pass_count=sum(item.contract_passed for item in evaluations),
        case_context_match_count=sum(item.case_context_matches for item in evaluations),
        mean_required_evidence_coverage=sum(
            item.required_evidence_coverage for item in evaluations
        ) / run_count,
        total_extra_evidence_count=sum(
            item.extra_evidence_count for item in evaluations
        ),
        hypothesis_order_match_rate=sum(
            item.hypothesis_order_matches_reference for item in evaluations
        ) / run_count,
        question_order_match_rate=sum(
            item.question_order_matches_reference for item in evaluations
        ) / run_count,
        next_step_order_match_rate=sum(
            item.next_step_order_matches_reference for item in evaluations
        ) / run_count,
    )

def build_benchmark(
    runs: tuple[InvestigationRun, ...],
    *,
    elapsed_seconds: tuple[float, ...] | None = None,
) -> InvestigationBenchmark:
    """Build a reproducible benchmark without creating a model-quality score."""

    if not runs:
        raise ValueError("At least one investigation run is required.")

    if elapsed_seconds is None:
        elapsed_seconds = (0.0,) * len(runs)

    if len(elapsed_seconds) != len(runs):
        raise ValueError(
            "elapsed_seconds must contain one value per investigation run."
        )

    items = tuple(
        InvestigationBenchmarkItem(
            case_id=run.proposal.case_id,
            case_version=run.proposal.case_version,
            mode=run.mode,
            requested_model=run.requested_model,
            evaluation=evaluate_run(
                run,
                elapsed_seconds=elapsed_seconds[index],
            ),
        )
        for index, run in enumerate(runs)
    )

    summary = summarize_evaluations(
        tuple(item.evaluation for item in items)
    )

    return InvestigationBenchmark(
    generated_at=datetime.now(timezone.utc),
    application_version=__version__,
    evaluations=items,
    summary=summary,
)


def evaluate_repeatability(
    runs: tuple[InvestigationRun, ...],
) -> InvestigationRepeatability:
    """Measure consistency across repeated runs of the same case/configuration."""

    if len(runs) < 2:
        raise ValueError("At least two investigation runs are required.")

    first = runs[0]

    for run in runs[1:]:
        if (
            run.proposal.case_id != first.proposal.case_id
            or run.proposal.case_version != first.proposal.case_version
        ):
            raise ValueError(
                "All repeated runs must use the same case and case version."
            )

        if (
            run.mode != first.mode
            or run.requested_model != first.requested_model
        ):
            raise ValueError(
                "All repeated runs must use the same investigation configuration."
            )

    evaluations = tuple(evaluate_run(run) for run in runs)

    evidence_selections = tuple(
        tuple(sorted(run.proposal.evidence_ids))
        for run in runs
    )
    hypothesis_orders = tuple(
        run.proposal.hypothesis_order
        for run in runs
    )
    question_orders = tuple(
        run.proposal.question_order
        for run in runs
    )
    next_step_orders = tuple(
        run.proposal.next_step_order
        for run in runs
    )
    def agreement(values: tuple[tuple[str, ...], ...]) -> float:
        counts = Counter(values)
        return max(counts.values()) / len(values)

    return InvestigationRepeatability(
        case_id=first.proposal.case_id,
        case_version=first.proposal.case_version,
        mode=first.mode,
        requested_model=first.requested_model,
        run_count=len(runs),
        contract_pass_count=sum(item.contract_passed for item in evaluations),
        case_context_match_count=sum(
            item.case_context_matches for item in evaluations
        ),
        distinct_evidence_selections=len(set(evidence_selections)),
        distinct_hypothesis_orders=len(set(hypothesis_orders)),
        distinct_question_orders=len(set(question_orders)),
        distinct_next_step_orders=len(set(next_step_orders)),
        evidence_selection_agreement=agreement(evidence_selections),
        hypothesis_order_agreement=agreement(hypothesis_orders),
        question_order_agreement=agreement(question_orders),
        next_step_order_agreement=agreement(next_step_orders),
    )