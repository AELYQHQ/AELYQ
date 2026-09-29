"""Retrieve a verified investigation report over real MCP stdio; no model calls."""

import argparse
import asyncio
import json
import sys
from hashlib import sha256
from pathlib import Path

from mcp import Client, StdioServerParameters

from .cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID, ReconciliationCase
from .reports import VerifiedReport, render_markdown


async def run_report_round_trip(case_id: str = CASE_ID) -> VerifiedReport:
    process = StdioServerParameters(
        command=sys.executable, args=["-m", "reconforge.mcp_server"],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with asyncio.timeout(30):
        async with Client(process, raise_exceptions=True, read_timeout_seconds=10) as client:
            result = await client.call_tool("get_case", {"case_id": case_id})
            case = ReconciliationCase.model_validate(result.structured_content)
            result = await client.call_tool("get_investigation_report", {
                "case_id": case_id, "case_version": case.case_version,
            })
            verified = VerifiedReport.model_validate(result.structured_content)
            if verified.report.case_id != case_id or verified.report.case_version != case.case_version:
                raise RuntimeError("Report does not match the selected case snapshot.")
            canonical = json.dumps(verified.report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if verified.report_id != sha256(canonical.encode("utf-8")).hexdigest():
                raise RuntimeError("Report content does not match its returned identifier.")
            return verified


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=[CASE_ID, BANK_CASE_ID, TIMING_CASE_ID], default=CASE_ID)
    parser.add_argument("--json", action="store_true", help="Print the structured report and verification result.")
    args = parser.parse_args()
    verified = asyncio.run(run_report_round_trip(args.case_id))
    if args.json:
        print(verified.model_dump_json(indent=2))
    else:
        print(render_markdown(verified), end="")


if __name__ == "__main__":
    main()
