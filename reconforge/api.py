"""Local read-only HTTP interface to the same case store used by MCP."""

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .cases import (
    CaseId, CaseList, CaseStore, CaseVersionMismatch, EvidenceId, EvidenceRecord,
    ReconciliationCase, UnknownCaseError, UnknownEvidenceError,
)
from .reports import ReportLimitError, ReportValidationError, VerifiedReport, get_investigation_report
from .investigation import InvestigationError
from .investigation_store import InvestigationArtifactError, InvestigationArtifactStore
from .investigator import run_mcp_investigation
from .operator_ui import (
    render_operator_case,
    render_operator_error,
    render_operator_index,
    render_operator_investigation,
    render_operator_investigation_error,
)


def create_app(
    store: CaseStore | None = None,
    artifact_store: InvestigationArtifactStore | None = None,
) -> FastAPI:
    store = store if store is not None else CaseStore()
    artifact_store = (
        artifact_store
        if artifact_store is not None
        else InvestigationArtifactStore(Path(".aelyq/investigation-runs"))
    )
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

    @app.post(
        "/operator/cases/{case_id}/investigate",
        include_in_schema=False,
    )
    async def operator_investigate(case_id: CaseId):
        case = store.get_case(case_id)

        try:
            run = await run_mcp_investigation(case_id)
        except InvestigationError as exc:
            return HTMLResponse(
                render_operator_error(case, str(exc)),
                status_code=422,
                headers={"Cache-Control": "no-store"},
            )

        try:
            artifact = artifact_store.save(run)
        except InvestigationArtifactError as exc:
            return HTMLResponse(
                render_operator_investigation_error(str(exc)),
                status_code=500,
                headers={"Cache-Control": "no-store"},
            )

        return RedirectResponse(
            url=f"/operator/investigations/{artifact.run_id}",
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )

    @app.get(
        "/operator/investigations/{run_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def operator_investigation(run_id: str) -> HTMLResponse:
        try:
            artifact = artifact_store.get(run_id)
        except InvestigationArtifactError as exc:
            status_code = 404 if str(exc) == "Investigation run not found." else 500
            return HTMLResponse(
                render_operator_investigation_error(str(exc)),
                status_code=status_code,
                headers={"Cache-Control": "no-store"},
            )

        return HTMLResponse(
            render_operator_investigation(
                artifact.run,
                artifact=artifact,
            ),
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
