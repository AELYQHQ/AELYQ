import unittest

from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID
from reconforge.evaluation_demo import (
    DEFAULT_EVALUATION_CASES,
    evaluate_benchmark,
    render_benchmark,
)


class EvaluationBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_benchmark_covers_all_bundled_cases(self):
        self.assertEqual(
            DEFAULT_EVALUATION_CASES,
            (CASE_ID, BANK_CASE_ID, TIMING_CASE_ID),
        )

        result = await evaluate_benchmark()

        self.assertEqual(result.schema_version, "0.1.0")
        self.assertEqual(result.summary.run_count, 3)
        self.assertEqual(result.summary.contract_pass_count, 3)
        self.assertEqual(result.summary.case_context_match_count, 3)
        self.assertEqual(result.summary.mean_required_evidence_coverage, 1.0)
        self.assertEqual(result.summary.total_extra_evidence_count, 0)
        self.assertEqual(result.summary.hypothesis_order_match_rate, 1.0)
        self.assertEqual(result.summary.question_order_match_rate, 1.0)
        self.assertEqual(result.summary.next_step_order_match_rate, 1.0)
        self.assertEqual(result.quality_claim, "not_established")

        case_ids = tuple(item.case_id for item in result.evaluations)

        self.assertEqual(
            case_ids,
            (CASE_ID, BANK_CASE_ID, TIMING_CASE_ID),
        )

    async def test_benchmark_render_contains_individual_and_aggregate_measurements(self):
        result = await evaluate_benchmark()
        rendered = render_benchmark(result)

        for case_id in DEFAULT_EVALUATION_CASES:
            self.assertIn(case_id, rendered)

        self.assertIn("Runs evaluated: **3**", rendered)
        self.assertIn("contract passed: **3/3**", rendered)
        self.assertIn("mean required evidence coverage: **100%**", rendered)
        self.assertIn("Quality claim: `not_established`", rendered)
        self.assertIn(
            "do not establish model quality or optimal priorities",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()


class EvaluationRepeatabilityTests(unittest.TestCase):
    def test_repeatable_case_returns_consistent_measurements(self):
        import asyncio

        from reconforge.evaluation_demo import evaluate_repeat

        result = asyncio.run(
            evaluate_repeat("case_bank_shortfall_001", 5)
        )

        self.assertEqual(result.run_count, 5)
        self.assertEqual(result.contract_pass_count, 5)
        self.assertEqual(result.case_context_match_count, 5)

        self.assertEqual(result.distinct_evidence_selections, 1)
        self.assertEqual(result.distinct_hypothesis_orders, 1)
        self.assertEqual(result.distinct_question_orders, 1)
        self.assertEqual(result.distinct_next_step_orders, 1)

        self.assertEqual(result.evidence_selection_agreement, 1.0)
        self.assertEqual(result.hypothesis_order_agreement, 1.0)
        self.assertEqual(result.question_order_agreement, 1.0)
        self.assertEqual(result.next_step_order_agreement, 1.0)

        self.assertEqual(result.quality_claim, "not_established")

    def test_repeat_count_must_be_at_least_two(self):
        import asyncio

        from reconforge.evaluation_demo import evaluate_repeat

        with self.assertRaises(ValueError):
            asyncio.run(
                evaluate_repeat("case_bank_shortfall_001", 1)
            )


if __name__ == "__main__":
    unittest.main()
