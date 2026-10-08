import asyncio
from reconforge.investigator import run_mcp_investigation
import unittest
from copy import deepcopy


from reconforge.evaluation import (
    InvestigationEvaluation,
    InvestigationMultiCaseRepeatability,
    build_benchmark,
    evaluate_repeatability,
    evaluate_multi_case_repeatability,
    evaluate_run,
    summarize_evaluations,
)
from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID, CaseStore
from reconforge.evaluation import (
    InvestigationEvaluation,
    build_benchmark,
    evaluate_run,
    summarize_evaluations,
)
from reconforge.investigation import (
    InvestigationRun,
    proposal_template,
    required_evidence,
    validate_proposal,
)
from reconforge.reports import get_investigation_report

from reconforge.evaluation import (
    InvestigationEvaluation,
    build_benchmark,
    evaluate_run,
    summarize_evaluations,
)


class InvestigationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore()
        self.case = self.store.get_case(BANK_CASE_ID)
        self.report = get_investigation_report(
            self.store, BANK_CASE_ID, self.case.case_version
        )
        self.inspected = {
            evidence_id: self.store.get_evidence(
                BANK_CASE_ID, self.case.case_version, evidence_id
            )
            for evidence_id in required_evidence(self.report)
        }

    def accepted_run(self, candidate=None, inspected=None):
        candidate = proposal_template(self.case, self.report) if candidate is None else candidate
        inspected = self.inspected if inspected is None else inspected
        proposal = validate_proposal(
            candidate, self.case, self.report, inspected
        )
        return InvestigationRun(
            mode="scripted_offline",
            requested_model=None,
            returned_models=(),
            proposal=proposal,
            report=self.report,
            model_turns=2,
            provider_requests=0,
            input_tokens=None,
            output_tokens=None,
            trace=(),
        )

    def test_reference_order_reports_full_evidence_and_matching_orders(self):
        result = evaluate_run(self.accepted_run())

        self.assertTrue(result.contract_passed)
        self.assertTrue(result.case_context_matches)
        self.assertEqual(result.required_evidence_coverage, 1.0)
        self.assertEqual(result.extra_evidence_count, 0)
        self.assertTrue(result.hypothesis_order_matches_reference)
        self.assertTrue(result.question_order_matches_reference)
        self.assertTrue(result.next_step_order_matches_reference)
        self.assertEqual(result.quality_claim, "not_established")

    def test_valid_reordering_is_measured_without_becoming_contract_failure(self):
        candidate = deepcopy(proposal_template(self.case, self.report))
        candidate["hypothesis_order"].reverse()
        candidate["next_step_order"].reverse()

        result = evaluate_run(self.accepted_run(candidate))

        self.assertTrue(result.contract_passed)
        self.assertFalse(result.hypothesis_order_matches_reference)
        self.assertTrue(result.question_order_matches_reference)
        self.assertFalse(result.next_step_order_matches_reference)
        self.assertEqual(result.quality_claim, "not_established")

    def test_extra_inspected_evidence_is_counted_without_reducing_required_coverage(self):
        candidate = deepcopy(proposal_template(self.case, self.report))
        required = set(candidate["evidence_ids"])
        extra_ref = next(ref for ref in self.case.evidence if ref.evidence_id not in required)
        candidate["evidence_ids"].append(extra_ref.evidence_id)

        inspected = dict(self.inspected)
        inspected[extra_ref.evidence_id] = self.store.get_evidence(
            BANK_CASE_ID, self.case.case_version, extra_ref.evidence_id
        )

        result = evaluate_run(self.accepted_run(candidate, inspected))

        self.assertEqual(result.required_evidence_coverage, 1.0)
        self.assertEqual(result.extra_evidence_count, 1)
        self.assertTrue(result.contract_passed)

    def test_invoice_reference_order_is_measured_independently(self):
        case = self.store.get_case(CASE_ID)
        report = get_investigation_report(
            self.store, CASE_ID, case.case_version
        )
        inspected = {
            evidence_id: self.store.get_evidence(
                CASE_ID, case.case_version, evidence_id
            )
            for evidence_id in required_evidence(report)
        }
        proposal = validate_proposal(
            proposal_template(case, report), case, report, inspected
        )
        run = InvestigationRun(
            mode="scripted_offline",
            requested_model=None,
            returned_models=(),
            proposal=proposal,
            report=report,
            model_turns=2,
            provider_requests=0,
            input_tokens=None,
            output_tokens=None,
            trace=(),
        )

        result = evaluate_run(run)

        self.assertEqual(result.required_evidence_coverage, 1.0)
        self.assertEqual(result.extra_evidence_count, 0)
        self.assertTrue(result.hypothesis_order_matches_reference)
        self.assertTrue(result.question_order_matches_reference)
        self.assertTrue(result.next_step_order_matches_reference)
        self.assertEqual(result.quality_claim, "not_established")

    def test_multi_run_summary_aggregates_only_descriptive_measurements(self):
        evaluations = (
            InvestigationEvaluation(
                evaluated_at="2026-10-04T00:00:00+00:00",
                python_runtime="3.12.14",
                mode="scripted_offline",
                requested_model=None,
                returned_models=(),
                elapsed_seconds=0.001,
                contract_passed=True,
                case_context_matches=True,
                required_evidence_coverage=1.0,
                extra_evidence_count=0,
                hypothesis_order_matches_reference=True,
                question_order_matches_reference=True,
                next_step_order_matches_reference=True,
            ),
                InvestigationEvaluation(
                    evaluated_at="2026-10-04T00:00:01+00:00",
                    python_runtime="3.12.14",
                    mode="scripted_offline",
                    requested_model=None,
                    returned_models=(),
                    elapsed_seconds=0.002,
                    contract_passed=False,
                    case_context_matches=True,
                    required_evidence_coverage=0.5,
                    extra_evidence_count=2,
                    hypothesis_order_matches_reference=False,
                    question_order_matches_reference=True,
                    next_step_order_matches_reference=False,
            ),
        )

        summary = summarize_evaluations(evaluations)

        self.assertEqual(summary.run_count, 2)
        self.assertEqual(summary.contract_pass_count, 1)
        self.assertEqual(summary.case_context_match_count, 2)
        self.assertEqual(summary.mean_required_evidence_coverage, 0.75)
        self.assertEqual(summary.total_extra_evidence_count, 2)
        self.assertEqual(summary.hypothesis_order_match_rate, 0.5)
        self.assertEqual(summary.question_order_match_rate, 1.0)
        self.assertEqual(summary.next_step_order_match_rate, 0.5)
        self.assertEqual(summary.quality_claim, "not_established")

    def test_multi_run_summary_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            summarize_evaluations(())



    def test_benchmark_preserves_case_identity_and_run_metadata(self):
        run = self.accepted_run()

        benchmark = build_benchmark((run,))

        self.assertEqual(len(benchmark.evaluations), 1)

        item = benchmark.evaluations[0]

        self.assertEqual(item.case_id, self.case.case_id)
        self.assertEqual(item.case_version, self.case.case_version)
        self.assertEqual(item.mode, "scripted_offline")
        self.assertIsNone(item.requested_model)

        self.assertTrue(item.evaluation.contract_passed)
        self.assertEqual(item.evaluation.required_evidence_coverage, 1.0)

    def test_benchmark_summary_matches_its_individual_evaluations(self):
        bank_run = self.accepted_run()

        case = self.store.get_case(CASE_ID)
        report = get_investigation_report(
            self.store,
            CASE_ID,
            case.case_version,
        )
        inspected = {
            evidence_id: self.store.get_evidence(
                CASE_ID,
                case.case_version,
                evidence_id,
            )
            for evidence_id in required_evidence(report)
        }
        proposal = validate_proposal(
            proposal_template(case, report),
            case,
            report,
            inspected,
        )
        invoice_run = InvestigationRun(
            mode="scripted_offline",
            requested_model=None,
            returned_models=(),
            proposal=proposal,
            report=report,
            model_turns=2,
            provider_requests=0,
            input_tokens=None,
            output_tokens=None,
            trace=(),
        )

        benchmark = build_benchmark((bank_run, invoice_run))

        self.assertEqual(benchmark.summary.run_count, 2)
        self.assertEqual(
            benchmark.summary.contract_pass_count,
            sum(
                item.evaluation.contract_passed
                for item in benchmark.evaluations
            ),
        )
        self.assertEqual(
            benchmark.summary.mean_required_evidence_coverage,
            sum(
                item.evaluation.required_evidence_coverage
                for item in benchmark.evaluations
            ) / 2,
        )
        self.assertEqual(
            benchmark.quality_claim,
            "not_established",
        )

    def test_benchmark_rejects_empty_runs(self):
        with self.assertRaises(ValueError):
            build_benchmark(())


    def test_repeatability_is_perfect_for_identical_runs(self):
        run = self.accepted_run()

        result = evaluate_repeatability((run, run))

        self.assertEqual(result.run_count, 2)
        self.assertEqual(result.contract_pass_count, 2)
        self.assertEqual(result.case_context_match_count, 2)

        self.assertEqual(result.distinct_evidence_selections, 1)
        self.assertEqual(result.distinct_hypothesis_orders, 1)
        self.assertEqual(result.distinct_question_orders, 1)
        self.assertEqual(result.distinct_next_step_orders, 1)

        self.assertEqual(result.evidence_selection_agreement, 1.0)
        self.assertEqual(result.hypothesis_order_agreement, 1.0)
        self.assertEqual(result.question_order_agreement, 1.0)
        self.assertEqual(result.next_step_order_agreement, 1.0)

        self.assertEqual(result.quality_claim, "not_established")

    def test_repeatability_detects_different_valid_priority_orders(self):
        first = self.accepted_run()

        candidate = deepcopy(proposal_template(self.case, self.report))
        candidate["hypothesis_order"].reverse()

        second = self.accepted_run(candidate)

        result = evaluate_repeatability((first, second))

        self.assertEqual(result.run_count, 2)
        self.assertEqual(result.contract_pass_count, 2)

        self.assertEqual(result.distinct_evidence_selections, 1)
        self.assertEqual(result.distinct_hypothesis_orders, 2)

        self.assertEqual(result.evidence_selection_agreement, 1.0)
        self.assertEqual(result.hypothesis_order_agreement, 0.5)

        self.assertEqual(result.question_order_agreement, 1.0)
        self.assertEqual(result.next_step_order_agreement, 1.0)

    def test_repeatability_requires_at_least_two_runs(self):
        run = self.accepted_run()

        with self.assertRaises(ValueError):
            evaluate_repeatability((run,))


if __name__ == "__main__":
    unittest.main()


class EvaluationProvenanceTests(unittest.TestCase):
    def test_evaluation_contains_execution_provenance(self):

        from reconforge.evaluation_demo import evaluate_case

        result = asyncio.run(
            evaluate_case("case_bank_shortfall_001")
        )

        self.assertEqual(result.mode, "scripted_offline")
        self.assertIsNone(result.requested_model)
        self.assertEqual(result.returned_models, ())
        self.assertGreaterEqual(result.elapsed_seconds, 0.0)
        self.assertTrue(result.evaluated_at.endswith("+00:00"))
        self.assertRegex(result.python_runtime, r"^\d+\.\d+\.\d+$")

    def test_negative_elapsed_time_is_rejected(self):

        from reconforge.evaluation_demo import evaluate_case

        result = asyncio.run(
            evaluate_case("case_bank_shortfall_001")
        )

        from reconforge.evaluation import evaluate_run

        run = asyncio.run(
            run_mcp_investigation("case_bank_shortfall_001")
        )

        with self.assertRaises(ValueError):
            evaluate_run(run, elapsed_seconds=-1)

    def test_quality_claim_remains_not_established(self):

        from reconforge.evaluation_demo import evaluate_case

        result = asyncio.run(
            evaluate_case("case_bank_shortfall_001")
        )

        self.assertEqual(result.quality_claim, "not_established")

class InvestigationMultiCaseRepeatabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups = []

        for case_id in (
            CASE_ID,
            BANK_CASE_ID,
            TIMING_CASE_ID,
        ):
            run = asyncio.run(
                run_mcp_investigation(case_id)
            )
            cls.groups.append((run, run))

        cls.groups = tuple(cls.groups)

    def test_aggregates_each_case_independently(self):
        result = evaluate_multi_case_repeatability(
            self.groups
        )

        self.assertIsInstance(
            result,
            InvestigationMultiCaseRepeatability,
        )
        self.assertEqual(result.case_count, 3)
        self.assertEqual(result.repeat_count, 2)
        self.assertEqual(result.total_run_count, 6)
        self.assertEqual(result.contract_pass_count, 6)
        self.assertEqual(result.case_context_match_count, 6)

        self.assertEqual(
            result.mean_evidence_selection_agreement,
            1.0,
        )
        self.assertEqual(
            result.mean_hypothesis_order_agreement,
            1.0,
        )
        self.assertEqual(
            result.mean_question_order_agreement,
            1.0,
        )
        self.assertEqual(
            result.mean_next_step_order_agreement,
            1.0,
        )

        self.assertEqual(
            tuple(result.case_id for result in result.case_results),
            (
                CASE_ID,
                BANK_CASE_ID,
                TIMING_CASE_ID,
            ),
        )

        self.assertEqual(
            result.quality_claim,
            "not_established",
        )

    def test_rejects_duplicate_case_groups(self):
        with self.assertRaisesRegex(
            ValueError,
            "Each case may appear only once",
        ):
            evaluate_multi_case_repeatability(
                (
                    self.groups[0],
                    self.groups[0],
                )
            )

    def test_rejects_mixed_repeat_counts(self):
        with self.assertRaisesRegex(
            ValueError,
            "same repeat count",
        ):
            evaluate_multi_case_repeatability(
                (
                    self.groups[0],
                    self.groups[1] + (self.groups[1][0],),
                )
            )

    def test_rejects_empty_input(self):
        with self.assertRaisesRegex(
            ValueError,
            "At least one repeated case group",
        ):
            evaluate_multi_case_repeatability(())

