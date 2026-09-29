"""Run the offline bounded investigator and report objective evaluation measurements."""

import argparse
import asyncio

from .cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID
from .evaluation import (
    InvestigationEvaluation,
    InvestigationEvaluationSummary,
    evaluate_run,
    summarize_evaluations,
)
from .investigation import InvestigationError
from .investigator import run_mcp_investigation


DEFAULT_EVALUATION_CASES = (CASE_ID, BANK_CASE_ID, TIMING_CASE_ID)


def render_evaluation(result: InvestigationEvaluation) -> str:
    """Render measurements without turning them into an aggregate quality score."""
    return "\n".join(
        (
            "# ReconForge investigator evaluation",
            "",
            f"Contract passed: **{str(result.contract_passed).lower()}**",
            f"Case context matches: **{str(result.case_context_matches).lower()}**",
            f"Required evidence coverage: **{result.required_evidence_coverage:.0%}**",
            f"Extra evidence rows cited: **{result.extra_evidence_count}**",
            "",
            "## Reference-order agreement",
            "",
            f"- hypotheses: **{str(result.hypothesis_order_matches_reference).lower()}**",
            f"- questions: **{str(result.question_order_matches_reference).lower()}**",
            f"- next steps: **{str(result.next_step_order_matches_reference).lower()}**",
            "",
            f"Quality claim: `{result.quality_claim}`",
            "",
            "Reference-order agreement is descriptive only; it does not establish that a model chose optimal priorities.",
        )
    )


def render_evaluation_summary(result: InvestigationEvaluationSummary) -> str:
    "Render aggregate measurements without implying an aggregate quality score."
    return "\n".join(
        (
            "# ReconForge multi-run investigator evaluation",
            "",
            f"Runs evaluated: **{result.run_count}**",
            f"Contract passed: **{result.contract_pass_count}/{result.run_count}**",
            f"Case context matched: **{result.case_context_match_count}/{result.run_count}**",
            f"Mean required evidence coverage: **{result.mean_required_evidence_coverage:.0%}**",
            f"Total extra evidence rows cited: **{result.total_extra_evidence_count}**",
            "",
            "## Reference-order agreement rates",
            "",
            f"- hypotheses: **{result.hypothesis_order_match_rate:.0%}**",
            f"- questions: **{result.question_order_match_rate:.0%}**",
            f"- next steps: **{result.next_step_order_match_rate:.0%}**",
            "",
            f"Quality claim: `{result.quality_claim}`",
            "",
            "These aggregate measurements are descriptive only; they do not establish model quality or optimal priorities.",
        )
    )


async def evaluate_case(case_id: str) -> InvestigationEvaluation:
    """Run one provider-free MCP investigation and evaluate the accepted result."""
    run = await run_mcp_investigation(case_id)
    return evaluate_run(run)


async def evaluate_cases(
    case_ids: tuple[str, ...] = DEFAULT_EVALUATION_CASES,
) -> InvestigationEvaluationSummary:
    """Evaluate multiple provider-free cases and return descriptive aggregates."""
    if not case_ids:
        raise ValueError("At least one case ID is required.")
    evaluations = tuple([await evaluate_case(case_id) for case_id in case_ids])
    return summarize_evaluations(evaluations)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case-id", choices=list(DEFAULT_EVALUATION_CASES))
    selection.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every bundled synthetic case once and summarize the results.",
    )
    parser.add_argument("--json", action="store_true", help="Print structured evaluation JSON.")
    args = parser.parse_args()

    try:
        if args.all:
            result = asyncio.run(evaluate_cases())
            rendered = render_evaluation_summary(result)
        else:
            result = asyncio.run(evaluate_case(args.case_id or CASE_ID))
            rendered = render_evaluation(result)
        print(result.model_dump_json(indent=2) if args.json else rendered)
    except InvestigationError as exc:
        print(f"Evaluation stopped: {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Evaluation cancelled.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
