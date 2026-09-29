import unittest

from mcp import Client

from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID, CaseStore
from reconforge.mcp_server import create_server
from reconforge.report_demo import run_report_round_trip


class ReportMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_reports_cross_real_stdio_with_exact_amounts(self):
        for case_id, residuals in ((CASE_ID, [25000, 0]), (BANK_CASE_ID, [0, 15000]), (TIMING_CASE_ID, [0, 1000000])):
            with self.subTest(case_id=case_id):
                verified = await run_report_round_trip(case_id)
                self.assertEqual(verified.report.case_id, case_id)
                self.assertEqual(verified.verification.status, "passed")
                self.assertEqual([f.amount_minor for f in verified.report.findings[3:5]], residuals)
                self.assertTrue(all(h.status == "unverified" for h in verified.report.hypotheses))

    async def test_missing_stale_and_unknown_report_inputs_fail_through_mcp(self):
        case = CaseStore().get_case(CASE_ID)
        async with Client(create_server()) as client:
            for arguments in (
                {"case_id": CASE_ID},
                {"case_id": CASE_ID, "case_version": "0" * 64},
                {"case_id": "unknown", "case_version": case.case_version},
            ):
                with self.subTest(arguments=arguments):
                    result = await client.call_tool("get_investigation_report", arguments)
                    self.assertTrue(result.is_error)
