import unittest
from copy import deepcopy

from reconforge.cases import BANK_CASE_ID, CASE_ID, CaseStore
from reconforge.evaluation import evaluate_run
from reconforge.investigation import (
    InvestigationRun,
    proposal_template,
    required_evidence,
    validate_proposal,
)
from reconforge.reports import get_investigation_report


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


if __name__ == "__main__":
    unittest.main()
