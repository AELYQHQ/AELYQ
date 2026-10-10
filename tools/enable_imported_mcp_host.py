"""Apply the one guarded, backward-compatible MCP-host integration edit.

Invoke from repository root: python tools/enable_imported_mcp_host.py
Aborts rather than guessing if investigator.py differs from the inspected API.
"""

import ast
from pathlib import Path

path = Path('reconforge/investigator.py')
source = path.read_text()

# Idempotent on a previously integrated branch.
if 'server_module: str = "reconforge.mcp_server"' in source:
    print('Imported MCP-host integration already installed.')
    raise SystemExit(0)

old_signature = '''async def run_mcp_investigation(
    case_id: str,
    model: DecisionModel | None = None,
) -> InvestigationRun:
'''
new_signature = '''async def run_mcp_investigation(
    case_id: str,
    model: DecisionModel | None = None,
    *,
    server_module: str = "reconforge.mcp_server",
) -> InvestigationRun:
    if server_module not in (
        "reconforge.mcp_server",
        "reconforge.imported_mcp_server",
    ):
        raise InvestigationError("Unsupported read-only MCP server module.")
'''
old_args = 'args=["-m", "reconforge.mcp_server"],'
new_args = 'args=["-m", server_module],'

if source.count(old_signature) != 1 or source.count(old_args) != 1:
    raise SystemExit('Current investigator differs from inspected contract; no changes made.')

updated = source.replace(old_signature, new_signature, 1).replace(old_args, new_args, 1)
ast.parse(updated)
compile(updated, str(path), 'exec')
path.write_text(updated)
print('Added allowlisted imported MCP server option to investigator host.')
