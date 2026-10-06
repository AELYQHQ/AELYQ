"""Run bounded investigator evaluation offline or explicitly against Anthropic."""

import argparse
import asyncio
import getpass
import os
from time import perf_counter
from pathlib import Path

from .anthropic_model import AnthropicMessagesModel
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
    started = perf_counter()
    run = await run_mcp_investigation(case_id)
    elapsed = perf_counter() - started
    return evaluate_run(run, elapsed_seconds=elapsed)

async def evaluate_live_case(
    case_id: str,
    model: AnthropicMessagesModel,
) -> InvestigationEvaluation:
    """Run one bounded Anthropic investigation and evaluate it."""
    started = perf_counter()
    run = await run_mcp_investigation(case_id, model)
    elapsed = perf_counter() - started

    if run.mode != "anthropic_live":
        raise InvestigationError("The live evaluator did not receive an Anthropic run.")

    return evaluate_run(run, elapsed_seconds=elapsed)


async def run_live_cases(
    case_ids: tuple[str, ...],
    model: AnthropicMessagesModel,
) -> tuple[InvestigationRun, ...]:
    """Run selected cases against Anthropic and preserve complete runs."""
    if not case_ids:
        raise ValueError("At least one case ID is required.")

    runs_list = []
    for case_id in case_ids:
        runs_list.append(
            await run_mcp_investigation(case_id, model)
        )
    runs = tuple(runs_list)

    if any(run.mode != "anthropic_live" for run in runs):
        raise InvestigationError("The live evaluator received a non-Anthropic run.")

    return runs


async def evaluate_live_benchmark(
    case_ids: tuple[str, ...],
    model: AnthropicMessagesModel,
) -> InvestigationBenchmark:
    """Build the same descriptive benchmark from Anthropic runs."""
    runs = []
    elapsed_seconds = []

    for case_id in case_ids:
        started = perf_counter()
        run = await run_mcp_investigation(case_id, model)
        elapsed_seconds.append(perf_counter() - started)
        runs.append(run)

    runs_tuple = tuple(runs)
    elapsed_tuple = tuple(elapsed_seconds)

    if any(run.mode != "anthropic_live" for run in runs_tuple):
        raise InvestigationError(
            "The live evaluator received a non-Anthropic run."
        )

    return build_benchmark(
        runs_tuple,
        elapsed_seconds=elapsed_tuple,
    )

async def evaluate_live_repeat(
    case_id: str,
    repeat_count: int,
    model: AnthropicMessagesModel,
) -> InvestigationRepeatability:
    """Repeat one Anthropic investigation and measure consistency."""
    if repeat_count < 2:
        raise ValueError("Repeat count must be at least 2.")

    runs_list = []
    for _ in range(repeat_count):
        runs_list.append(
            await run_mcp_investigation(case_id, model)
        )
    runs = tuple(runs_list)

    if any(run.mode != "anthropic_live" for run in runs):
        raise InvestigationError("The live evaluator received a non-Anthropic run.")

    return evaluate_repeatability(runs)


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
    """Run the bundled cases once and preserve execution timing."""
    runs = []
    elapsed_seconds = []

    for case_id in case_ids:
        started = perf_counter()
        run = await run_mcp_investigation(case_id)
        elapsed_seconds.append(perf_counter() - started)
        runs.append(run)

    return build_benchmark(
        tuple(runs),
        elapsed_seconds=tuple(elapsed_seconds),
    )

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
    selection.add_argument(
        "--case-id",
        choices=list(DEFAULT_EVALUATION_CASES),
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every bundled synthetic case once.",
    )

    parser.add_argument(
        "--repeat",
        type=int,
        metavar="N",
        help="Repeat one selected case N times and measure consistency.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the Anthropic live investigator instead of the offline simulator.",
    )
    parser.add_argument(
        "--provider",
        choices=("anthropic",),
        help="Live provider. Anthropic is the only live evaluation provider.",
    )
    parser.add_argument(
        "--model",
        help="Explicit Anthropic model ID; or set RECONFORGE_MODEL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured evaluation JSON.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist benchmark or repeatability results as an immutable evaluation artifact.",
    )

    args = parser.parse_args()

    try:
        if args.persist and not (args.all or args.repeat is not None):
            parser.error("--persist requires --all or --repeat.")

        if args.provider and not args.live:
            parser.error("--provider is only used with --live.")

        if args.model and not args.live:
            parser.error("--model is only used with --live.")

        if args.live:
            if not (args.case_id or args.all or args.repeat is not None):
                parser.error(
                    "--live requires --case-id, --all, or --repeat."
                )

            if args.repeat is not None and not args.case_id:
                parser.error("--repeat requires --case-id.")

            if args.repeat is not None and args.all:
                parser.error("--repeat cannot be combined with --all.")

            provider = args.provider or "anthropic"

            if provider != "anthropic":
                parser.error("Only Anthropic is enabled for live evaluation.")

            model_id = args.model or os.environ.get("RECONFORGE_MODEL")

            if not model_id:
                parser.error(
                    "--live requires --model MODEL_ID "
                    "or RECONFORGE_MODEL."
                )

            api_key = os.environ.get("ANTHROPIC_API_KEY")

            if not api_key:
                if not os.isatty(0):
                    parser.error(
                        "Run interactively for a hidden Anthropic API-key prompt, "
                        "or set ANTHROPIC_API_KEY locally."
                    )
                api_key = getpass.getpass(
                    "Anthropic API key (hidden; not saved): "
                )

            model = AnthropicMessagesModel(api_key, model_id)

            if args.repeat is not None:
                result = asyncio.run(
                    evaluate_live_repeat(
                        args.case_id,
                        args.repeat,
                        model,
                    )
                )
                rendered = render_repeatability(result)

                if args.persist:
                    artifact = persist_evaluation(result)
                    rendered += (
                        "\n\n"
                        f"Persisted evaluation artifact: `{artifact.artifact_id}`"
                    )

            elif args.all:
                result = asyncio.run(
                    evaluate_live_benchmark(
                        DEFAULT_EVALUATION_CASES,
                        model,
                    )
                )
                rendered = render_benchmark(result)

                if args.persist:
                    artifact = persist_evaluation(result)
                    rendered += (
                        "\n\n"
                        f"Persisted evaluation artifact: `{artifact.artifact_id}`"
                    )

            else:
                result = asyncio.run(
                    evaluate_live_case(
                        args.case_id,
                        model,
                    )
                )
                rendered = render_evaluation(result)

            if args.json:
                if args.repeat is not None or args.all:
                    print(result.model_dump_json(indent=2))
                else:
                    print(result.model_dump_json(indent=2))
            else:
                print(rendered)

            return

        # -------------------------
        # Offline mode
        # -------------------------

        if args.repeat is not None:
            if not args.case_id:
                parser.error("--repeat requires --case-id.")
            if args.all:
                parser.error("--repeat cannot be combined with --all.")

            result = asyncio.run(
                evaluate_repeat(
                    args.case_id,
                    args.repeat,
                )
            )
            rendered = render_repeatability(result)

            if args.persist:
                artifact = persist_evaluation(result)
                rendered += (
                    "\n\n"
                    f"Persisted evaluation artifact: `{artifact.artifact_id}`"
                )

        elif args.all:
            result = asyncio.run(
                evaluate_benchmark()
            )
            rendered = render_benchmark(result)

            if args.persist:
                artifact = persist_evaluation(result)
                rendered += (
                    "\n\n"
                    f"Persisted evaluation artifact: `{artifact.artifact_id}`"
                )

        else:
            case_id = args.case_id or CASE_ID
            result = asyncio.run(
                evaluate_case(case_id)
            )
            rendered = render_evaluation(result)

        print(
            result.model_dump_json(indent=2)
            if args.json
            else rendered
        )

    except InvestigationError as exc:
        print(f"Evaluation stopped: {exc}")
        raise SystemExit(1) from None

    except KeyboardInterrupt:
        print("Evaluation cancelled.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
