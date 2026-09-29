"""Objective measurements for accepted ReconForge investigation runs.

This module intentionally does not produce an aggregate model-quality score.
It measures contract/evidence properties and agreement with an explicit
reference ordering. Matching that ordering is not treated as proof that the
model chose the best priorities.
"""

from typing import Literal

from pydantic import Field, StrictInt

from .cases import FrozenModel
from .investigation import InvestigationRun, required_evidence


class InvestigationEvaluation(FrozenModel):
    """Reproducible measurements for one accepted investigation run."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_passed: bool
    case_context_matches: bool
    required_evidence_coverage: float = Field(ge=0.0, le=1.0)
    extra_evidence_count: StrictInt = Field(ge=0)
    hypothesis_order_matches_reference: bool
    question_order_matches_reference: bool
    next_step_order_matches_reference: bool
    quality_claim: Literal["not_established"] = "not_established"


def evaluate_run(run: InvestigationRun) -> InvestigationEvaluation:
    """Measure an accepted run without claiming that its priorities are optimal.

    The reference ordering is the deterministic ordering already present in the
    verified report. Agreement is reported only as agreement with that explicit
    reference; it is not an AI-quality score.
    """

    proposal = run.proposal
    report = run.report.report

    required = required_evidence(run.report)
    cited = set(proposal.evidence_ids)
    coverage = 1.0 if not required else len(required & cited) / len(required)

    return InvestigationEvaluation(
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

