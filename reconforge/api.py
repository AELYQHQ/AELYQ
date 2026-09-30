"""Local read-only HTTP interface to the same case store used by MCP."""

from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .cases import (
    CaseId, CaseList, CaseStore, CaseVersionMismatch, EvidenceId, EvidenceRecord,
    ReconciliationCase, UnknownCaseError, UnknownEvidenceError,
)
from .reports import ReportLimitError, ReportValidationError, VerifiedReport, get_investigation_report
from .operator_ui import render_operator_case, render_operator_index


def create_app(store: CaseStore | None = None) -> FastAPI:
    store = store if store is not None else CaseStore()
    app = FastAPI(
        title="AELYQ — synthetic case API", version=__version__,
        description="Read-only local demonstration. No authentication or financial actions.",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.exception_handler(UnknownCaseError)
    @app.exception_handler(UnknownEvidenceError)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(CaseVersionMismatch)
    async def stale_version(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ReportValidationError)
    @app.exception_handler(ReportLimitError)
    async def report_rejected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "synthetic_read_only", "version": __version__}

    @app.get("/operator", response_class=HTMLResponse, include_in_schema=False)
    def operator_index() -> HTMLResponse:
        return HTMLResponse(
            render_operator_index(store.list_cases()),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/operator/cases/{case_id}", response_class=HTMLResponse, include_in_schema=False)
    def operator_case(case_id: CaseId) -> HTMLResponse:
        case = store.get_case(case_id)
        report = get_investigation_report(store, case_id, case.case_version)
        evidence = tuple(
            store.get_evidence(case_id, case.case_version, reference.evidence_id)
            for reference in case.evidence
        )
        return HTMLResponse(
            render_operator_case(case, report, evidence),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/cases", response_model=CaseList)
    def list_cases() -> CaseList:
        return store.list_cases()

    @app.get("/cases/{case_id}", response_model=ReconciliationCase)
    def get_case(case_id: CaseId) -> ReconciliationCase:
        return store.get_case(case_id)

    @app.get("/cases/{case_id}/report", response_model=VerifiedReport)
    def get_report(
        case_id: CaseId,
        case_version: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
    ) -> VerifiedReport:
        return get_investigation_report(store, case_id, case_version)

    @app.get("/cases/{case_id}/evidence/{evidence_id}", response_model=EvidenceRecord)
    def get_evidence(
        case_id: CaseId, evidence_id: EvidenceId,
        case_version: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
    ) -> EvidenceRecord:
        return store.get_evidence(case_id, case_version, evidence_id)

    return app


app = create_app()
