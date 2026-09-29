import unittest

from mcp import Client

from reconforge.cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID, CaseStore
from reconforge.mcp_demo import run_round_trip
from reconforge.mcp_server import create_server


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_round_trip(self):
        case, evidence, names = await run_round_trip()
        self.assertEqual(names, ["get_case", "get_evidence", "get_investigation_report", "list_cases"])
        self.assertEqual(case.facts.comparisons.ledger_to_provider.residual_minor, 25000)
        self.assertEqual(evidence.reference.record_number, 7)
        self.assertEqual(evidence.row.event_id, "evt_invoice_001")
        self.assertTrue(case.facts.review_required)
        self.assertFalse(case.facts.external_completeness_verified)

    async def test_second_case_runs_through_real_stdio(self):
        case, evidence, names = await run_round_trip(BANK_CASE_ID)
        self.assertEqual(case.case_id, BANK_CASE_ID)
        self.assertEqual(case.facts.comparisons.ledger_to_provider.residual_minor, 0)
        self.assertEqual(case.facts.comparisons.provider_to_bank.residual_minor, 15000)
        self.assertEqual(evidence.row.amount_eur, "81850.00")
        self.assertEqual(evidence.reference.file, "bank_entries.csv")
        self.assertEqual(evidence.reference.record_number, 1)
        self.assertEqual(evidence.case_id, BANK_CASE_ID)

    async def test_list_cases_exposes_all_residuals_and_stable_order(self):
        async with Client(create_server()) as client:
            result = await client.call_tool("list_cases", {})
            self.assertFalse(result.is_error)
            summaries = result.structured_content["cases"]
            self.assertEqual([item["case_id"] for item in summaries], sorted([CASE_ID, BANK_CASE_ID, TIMING_CASE_ID]))
            bank = next(item for item in summaries if item["case_id"] == BANK_CASE_ID)
            self.assertEqual(bank["ledger_to_provider_residual_minor"], 0)
            self.assertEqual(bank["provider_to_bank_residual_minor"], 15000)
            self.assertTrue(bank["review_required"])

    async def test_other_case_evidence_and_version_are_rejected_by_mcp(self):
        store = CaseStore()
        invoice = store.get_case(CASE_ID)
        bank = store.get_case(BANK_CASE_ID)
        async with Client(create_server(store)) as client:
            result = await client.call_tool("get_evidence", {
                "case_id": BANK_CASE_ID, "case_version": bank.case_version,
                "evidence_id": invoice.evidence[0].evidence_id,
            })
            self.assertTrue(result.is_error)
            self.assertIn("Unknown evidence ID for this case", result.content[0].text)
            result = await client.call_tool("get_evidence", {
                "case_id": BANK_CASE_ID, "case_version": invoice.case_version,
                "evidence_id": bank.evidence[0].evidence_id,
            })
            self.assertTrue(result.is_error)
            self.assertIn("Case version changed", result.content[0].text)

    async def test_catalogue_is_read_only_and_returns_structured_schemas(self):
        store = CaseStore()
        async with Client(create_server(store)) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {"get_case", "get_evidence", "get_investigation_report", "list_cases"})
            for tool in tools:
                with self.subTest(tool=tool.name):
                    self.assertTrue(tool.annotations.read_only_hint)
                    self.assertFalse(tool.annotations.destructive_hint)
                    self.assertFalse(tool.annotations.open_world_hint)
                    self.assertIsNotNone(tool.output_schema)
            result = await client.call_tool("get_case", {"case_id": CASE_ID})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content, store.get_case(CASE_ID).model_dump(mode="json"))

    async def test_bad_ids_types_and_stale_versions_fail_through_the_protocol(self):
        store = CaseStore()
        case = store.get_case(CASE_ID)
        async with Client(create_server(store)) as client:
            for value in ["unknown", "../../etc/passwd", 123, "a" * 81]:
                with self.subTest(case_id=value):
                    result = await client.call_tool("get_case", {"case_id": value})
                    self.assertTrue(result.is_error)
            result = await client.call_tool("get_evidence", {
                "case_id": CASE_ID, "case_version": "0" * 64,
                "evidence_id": case.evidence[0].evidence_id,
            })
            self.assertTrue(result.is_error)
            self.assertIn("Case version changed", result.content[0].text)
