import unittest
from datetime import datetime

from reconforge.cases import TIMING_CASE_ID, CaseStore
from reconforge.investigation import proposal_template, required_evidence, validate_proposal
from reconforge.reports import get_investigation_report


class SettlementTimingScenarioTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore()
        self.case = self.store.get_case(TIMING_CASE_ID)
        self.report = get_investigation_report(
            self.store, TIMING_CASE_ID, self.case.case_version
        )

    def test_reconciliation_is_balanced_to_provider_but_short_at_bank(self):
        facts = self.case.facts
        self.assertEqual(facts.totals_minor.ledger, 6_940_000)
        self.assertEqual(facts.totals_minor.provider, 6_940_000)
        self.assertEqual(facts.totals_minor.bank, 5_940_000)
        self.assertEqual(facts.comparisons.ledger_to_provider.residual_minor, 0)
        self.assertEqual(facts.comparisons.provider_to_bank.residual_minor, 1_000_000)
        self.assertEqual(facts.event_differences, ())
        self.assertTrue(facts.review_required)
        self.assertFalse(facts.external_completeness_verified)

    def test_late_provider_event_timestamp_is_after_supplied_bank_payout(self):
        provider_ref = next(
            ref for ref in self.case.evidence
            if ref.file == "psp_events.csv" and ref.event_id == "evt_capture_late_001"
        )
        bank_ref = next(ref for ref in self.case.evidence if ref.file == "bank_entries.csv")
        provider = self.store.get_evidence(
            TIMING_CASE_ID, self.case.case_version, provider_ref.evidence_id
        )
        bank = self.store.get_evidence(
            TIMING_CASE_ID, self.case.case_version, bank_ref.evidence_id
        )
        provider_time = datetime.fromisoformat(provider.row.effective_at.replace("Z", "+00:00"))
        bank_time = datetime.fromisoformat(bank.row.effective_at.replace("Z", "+00:00"))
        self.assertGreater(provider_time, bank_time)
        self.assertEqual(provider.row.amount_eur, "10000.00")
        self.assertEqual(bank.row.amount_eur, "59400.00")

    def test_report_keeps_timing_as_unverified_hypothesis_not_finding(self):
        report = self.report.report
        self.assertEqual(
            tuple(item.code for item in report.hypotheses),
            ("payout_timing_or_reporting", "adjustment_or_data_error"),
        )
        self.assertTrue(all(item.status == "unverified" for item in report.hypotheses))
        self.assertIn("bank_difference_cause", {item.code for item in report.unresolved_questions})
        self.assertIn("compare_payout_advice", {item.code for item in report.next_steps})
        finding_text = " ".join(item.statement.lower() for item in report.findings)
        self.assertNotIn("timing", finding_text)
        self.assertNotIn("confirmed cause", finding_text)

    def test_bounded_proposal_preserves_undetermined_conclusion(self):
        rows = {
            evidence_id: self.store.get_evidence(
                TIMING_CASE_ID, self.case.case_version, evidence_id
            )
            for evidence_id in required_evidence(self.report)
        }
        proposal = validate_proposal(
            proposal_template(self.case, self.report), self.case, self.report, rows
        )
        self.assertEqual(proposal.conclusion, "cause_undetermined")
        self.assertEqual(
            proposal.hypothesis_order,
            ("payout_timing_or_reporting", "adjustment_or_data_error"),
        )


if __name__ == "__main__":
    unittest.main()
