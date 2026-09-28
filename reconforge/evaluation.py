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
