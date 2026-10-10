"""Read-only MCP entry point for locally registered synthetic test batches.

Do not expose stdio to untrusted clients. No case registration/write tools.
"""

from .imported_cases import open_case_store
from .mcp_server import create_server


def main() -> None:
    create_server(open_case_store()).run(transport='stdio')


if __name__ == '__main__':
    main()
