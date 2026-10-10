"""Run an offline bounded MCP investigation for a registered synthetic case."""

import argparse
import asyncio

from .imported_cases import ImportRegistrationError, open_case_store
from .investigator import run_mcp_investigation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        store = open_case_store()
        store.get_case(args.case_id)
    except (ImportRegistrationError, LookupError) as exc:
        parser.exit(2, f'Unknown imported case: {exc}\n')
    run = asyncio.run(run_mcp_investigation(
        args.case_id, server_module='reconforge.imported_mcp_server',
    ))
    if args.json:
        print(run.model_dump_json(indent=2))
    else:
        print('Accepted read-only investigation for:', run.proposal.case_id)
        print('Case version:', run.proposal.case_version)
        print('Mode:', run.mode)


if __name__ == '__main__':
    main()
