"""Run the offline bounded investigator and report objective evaluation measurements."""

import argparse
import asyncio

from .cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID
from .evaluation import InvestigationEvaluation, evaluate_run
from .investigation import InvestigationError
from .investigator import run_mcp_investigation


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


async def evaluate_case(case_id: str) -> InvestigationEvaluation:
    """Run one provider-free MCP investigation and evaluate the accepted result."""
    run = await run_mcp_investigation(case_id)
    return evaluate_run(run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=[CASE_ID, BANK_CASE_ID, TIMING_CASE_ID], default=CASE_ID)
    parser.add_argument("--json", action="store_true", help="Print structured evaluation JSON.")
    args = parser.parse_args()

    try:
        result = asyncio.run(evaluate_case(args.case_id))
        print(result.model_dump_json(indent=2) if args.json else render_evaluation(result))
    except InvestigationError as exc:
        print(f"Evaluation stopped: {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Evaluation cancelled.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
