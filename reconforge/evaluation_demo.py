"""Run the offline bounded investigator and report objective evaluation measurements."""

import argparse
import asyncio
from pathlib import Path

from .cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID
from .evaluation import (
    InvestigationBenchmark,
    InvestigationEvaluation,
    InvestigationEvaluationSummary,
    InvestigationRepeatability,
    build_benchmark,
    evaluate_repeatability,
    evaluate_run,
    summarize_evaluations,
)
from .investigation import InvestigationError, InvestigationRun
from .investigator import run_mcp_investigation
from .evaluation_store import EvaluationArtifact, EvaluationArtifactStore


DEFAULT_EVALUATION_CASES = (CASE_ID, BANK_CASE_ID, TIMING_CASE_ID)


DEFAULT_EVALUATION_DIRECTORY = Path(".aelyq/evaluations")


def persist_evaluation(
    result: InvestigationBenchmark | InvestigationRepeatability,
) -> EvaluationArtifact:
    """Persist a descriptive benchmark or repeatability result immutably."""
    store = EvaluationArtifactStore(DEFAULT_EVALUATION_DIRECTORY)
    return store.save(result)


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


def render_benchmark(result: InvestigationBenchmark) -> str:
    """Render individual benchmark measurements and their aggregate summary."""
    lines = [
        "# ReconForge investigator benchmark",
        "",
        f"Benchmark schema: **{result.schema_version}**",
        f"Runs evaluated: **{result.summary.run_count}**",
        "",
        "## Individual evaluations",
        "",
    ]

    for item in result.evaluations:
        evaluation = item.evaluation
        lines.extend(
            (
                f"### `{item.case_id}`",
                "",
                f"- case version: `{item.case_version}`",
                f"- mode: `{item.mode}`",
                f"- contract passed: **{str(evaluation.contract_passed).lower()}**",
                f"- case context matches: **{str(evaluation.case_context_matches).lower()}**",
                f"- required evidence coverage: **{evaluation.required_evidence_coverage:.0%}**",
                f"- extra evidence rows: **{evaluation.extra_evidence_count}**",
                f"- hypothesis order matches reference: **{str(evaluation.hypothesis_order_matches_reference).lower()}**",
                f"- question order matches reference: **{str(evaluation.question_order_matches_reference).lower()}**",
                f"- next-step order matches reference: **{str(evaluation.next_step_order_matches_reference).lower()}**",
                "",
            )
        )

    lines.extend(
        (
            "## Aggregate measurements",
            "",
            f"- contract passed: **{result.summary.contract_pass_count}/{result.summary.run_count}**",
            f"- case context matched: **{result.summary.case_context_match_count}/{result.summary.run_count}**",
            f"- mean required evidence coverage: **{result.summary.mean_required_evidence_coverage:.0%}**",
            f"- total extra evidence rows: **{result.summary.total_extra_evidence_count}**",
            f"- hypothesis order agreement: **{result.summary.hypothesis_order_match_rate:.0%}**",
            f"- question order agreement: **{result.summary.question_order_match_rate:.0%}**",
            f"- next-step order agreement: **{result.summary.next_step_order_match_rate:.0%}**",
            "",
            f"Quality claim: `{result.quality_claim}`",
            "",
            "All measurements are descriptive; they do not establish model quality or optimal priorities.",
        )
    )

    return "\n".join(lines)


def render_repeatability(result: InvestigationRepeatability) -> str:
    """Render descriptive repeated-run consistency measurements."""
    return "\n".join(
        (
            "# ReconForge investigator repeatability",
            "",
            f"Case: `{result.case_id}`",
            f"Case version: `{result.case_version}`",
            f"Mode: **{result.mode}**",
            f"Runs evaluated: **{result.run_count}**",
            "",
            "## Contract measurements",
            "",
            f"- contract passed: **{result.contract_pass_count}/{result.run_count}**",
            f"- case context matched: **{result.case_context_match_count}/{result.run_count}**",
            "",
            "## Consistency measurements",
            "",
            f"- distinct evidence selections: **{result.distinct_evidence_selections}**",
            f"- evidence selection agreement: **{result.evidence_selection_agreement:.0%}**",
            f"- distinct hypothesis orders: **{result.distinct_hypothesis_orders}**",
            f"- hypothesis order agreement: **{result.hypothesis_order_agreement:.0%}**",
            f"- distinct question orders: **{result.distinct_question_orders}**",
            f"- question order agreement: **{result.question_order_agreement:.0%}**",
            f"- distinct next-step orders: **{result.distinct_next_step_orders}**",
            f"- next-step order agreement: **{result.next_step_order_agreement:.0%}**",
            "",
            f"Quality claim: `{result.quality_claim}`",
            "",
            "Consistency is descriptive only; it does not establish that a repeated priority is correct or optimal.",
        )
    )


async def evaluate_case(case_id: str) -> InvestigationEvaluation:
    """Run one provider-free MCP investigation and evaluate the accepted result."""
    run = await run_mcp_investigation(case_id)
    return evaluate_run(run)

async def run_cases(
    case_ids: tuple[str, ...] = DEFAULT_EVALUATION_CASES,
) -> tuple[InvestigationRun, ...]:
    """Run the bundled cases once and preserve the complete runs."""
    if not case_ids:
        raise ValueError("At least one case ID is required.")
    return tuple(
        [await run_mcp_investigation(case_id) for case_id in case_ids]
    )

async def evaluate_benchmark(
    case_ids: tuple[str, ...] = DEFAULT_EVALUATION_CASES,
) -> InvestigationBenchmark:
    """Run the bundled cases once and build descriptive benchmark measurements."""
    runs = await run_cases(case_ids)
    return build_benchmark(runs)

async def evaluate_repeat(
    case_id: str,
    repeat_count: int,
) -> InvestigationRepeatability:
    """Run one case repeatedly and measure descriptive consistency."""
    if repeat_count < 2:
        raise ValueError("Repeat count must be at least 2.")

    runs = tuple(
        [await run_mcp_investigation(case_id) for _ in range(repeat_count)]
    )
    return evaluate_repeatability(runs)


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
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist benchmark or repeatability results as an immutable evaluation artifact.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        metavar="N",
        help="Repeat one selected case N times and measure consistency.",
    )
    args = parser.parse_args()

    try:
        if args.persist and not (args.all or args.repeat is not None):
            parser.error("--persist requires --all or --repeat.")

        artifact = None

        if args.repeat is not None:
            if args.all:
                parser.error("--repeat cannot be combined with --all.")
            if not args.case_id:
                parser.error("--repeat requires --case-id.")
            result = asyncio.run(
                evaluate_repeat(args.case_id, args.repeat)
            )
            rendered = render_repeatability(result)

        elif args.all:
            result = asyncio.run(evaluate_benchmark())
            rendered = render_benchmark(result)

        else:
            result = asyncio.run(evaluate_case(args.case_id or CASE_ID))
            rendered = render_evaluation(result)

        if args.persist:
            artifact = persist_evaluation(result)

        if args.json:
            if artifact is not None:
                print(artifact.model_dump_json(indent=2))
            else:
                print(result.model_dump_json(indent=2))
        else:
            print(rendered)
            if artifact is not None:
                print()
                print("## Persisted evaluation artifact")
                print()
                print(f"- evaluation ID: `{artifact.evaluation_id}`")
                print(f"- artifact type: `{artifact.artifact_type}`")
                print(f"- SHA-256: `{artifact.result_sha256}`")
                print(f"- path: `{DEFAULT_EVALUATION_DIRECTORY / (artifact.evaluation_id + '.json')}`")
    except InvestigationError as exc:
        print(f"Evaluation stopped: {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Evaluation cancelled.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
