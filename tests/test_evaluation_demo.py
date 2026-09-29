import unittest

from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID
from reconforge.evaluation_demo import (
    evaluate_case,
    evaluate_cases,
    render_evaluation,
    render_evaluation_summary,
)


class EvaluationDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_synthetic_cases_evaluate_offline_through_real_mcp(self):
        for case_id in (CASE_ID, BANK_CASE_ID, TIMING_CASE_ID):
            with self.subTest(case_id=case_id):
                result = await evaluate_case(case_id)
                self.assertTrue(result.contract_passed)
                self.assertTrue(result.case_context_matches)
                self.assertEqual(result.required_evidence_coverage, 1.0)
                self.assertEqual(result.extra_evidence_count, 0)
                self.assertEqual(result.quality_claim, "not_established")

    async def test_human_output_keeps_reference_agreement_separate_from_quality(self):
        result = await evaluate_case(BANK_CASE_ID)
        rendered = render_evaluation(result)
        self.assertIn("Required evidence coverage: **100%**", rendered)
        self.assertIn("Quality claim: `not_established`", rendered)
        self.assertIn("does not establish that a model chose optimal priorities", rendered)

    async def test_multi_run_summary_evaluates_all_bundled_cases_offline(self):
        result = await evaluate_cases()

        self.assertEqual(result.run_count, 3)
        self.assertEqual(result.contract_pass_count, 3)
        self.assertEqual(result.case_context_match_count, 3)
        self.assertEqual(result.mean_required_evidence_coverage, 1.0)
        self.assertEqual(result.total_extra_evidence_count, 0)
        self.assertEqual(result.hypothesis_order_match_rate, 1.0)
        self.assertEqual(result.question_order_match_rate, 1.0)
        self.assertEqual(result.next_step_order_match_rate, 1.0)
        self.assertEqual(result.quality_claim, "not_established")

        rendered = render_evaluation_summary(result)
        self.assertIn("Runs evaluated: **3**", rendered)
        self.assertIn("Contract passed: **3/3**", rendered)
        self.assertIn("Quality claim: `not_established`", rendered)
        self.assertIn("do not establish model quality", rendered)


if __name__ == "__main__":
    unittest.main()
