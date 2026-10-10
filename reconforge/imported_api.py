"""Local read-only API over the operator's registered synthetic cases.

Launch only on loopback: uvicorn reconforge.imported_api:app --host 127.0.0.1
Restart to see newly registered cases; the snapshot is immutable per process.
"""

from .api import create_app
from .imported_cases import open_case_store

app = create_app(open_case_store())
