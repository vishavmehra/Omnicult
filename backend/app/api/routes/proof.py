"""Proof Vault: Proof Report v2, report exports, Run History, Data Health, and claim lookup."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.common import DataMode
from app.schemas.proof import (
    DataHealth,
    ProofExport,
    ProofExportCreate,
    ProofReport,
    ProofReportCreate,
    ProofReportPage,
    ProofSectionInfo,
    RunHistoryDetail,
    RunHistoryPage,
)
from app.schemas.regions import ClaimView
from app.schemas.runs import RunStatus, RunType
from app.services import claim_lookup, data_health, proof_reports, run_history

router = APIRouter(tags=["proof"])


@router.get("/proof-report-sections", response_model=list[ProofSectionInfo])
async def list_proof_report_sections(user: CurrentUser) -> list[ProofSectionInfo]:
    """The sections a Proof Report is made of, in order, and whether each has a provider wired in this build."""
    return proof_reports.list_sections()


@router.post("/campaigns/{campaign_id}/proof-reports", status_code=status.HTTP_201_CREATED, response_model=ProofReport)
async def create_proof_report(campaign_id: UUID, body: ProofReportCreate, user: CurrentUser) -> ProofReport:
    """Assemble and store the campaign's next Proof Report snapshot. Deterministic: no model is called. Sections whose
    provider is not wired, or whose data is missing, are listed as missing and make the report partial. Needs the
    owner or editor role."""
    return await proof_reports.create_report(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/proof-reports", response_model=ProofReportPage)
async def list_proof_reports(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> ProofReportPage:
    """Snapshots, newest first."""
    return await proof_reports.list_reports(user.id, campaign_id, limit, offset)


@router.get("/proof-reports/{report_id}", response_model=ProofReport)
async def get_proof_report(report_id: UUID, user: CurrentUser) -> ProofReport:
    return await proof_reports.get_report(user.id, report_id)


@router.get(
    "/proof-reports/{report_id}/export",
    response_class=Response,
    responses={200: {"description": "Report download (Content-Disposition: attachment).", "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/ProofReport"}},
        "text/markdown": {"schema": {"type": "string"}},
        "application/pdf": {"schema": {"type": "string", "format": "binary"}},
    }}},
)
async def export_proof_report(
    report_id: UUID, user: CurrentUser, fmt: Annotated[Literal["json", "markdown", "pdf"], Query(alias="format")] = "pdf"
) -> Response:
    """Download a snapshot now. The PDF shows Indic text as a Latin transliteration and says so; JSON and Markdown keep
    the original text."""
    exported = await proof_reports.export_inline(user.id, report_id, fmt)
    return Response(
        exported.data, media_type=exported.media_type,
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"', "Cache-Control": "private, no-store"},
    )


@router.post("/proof-reports/{report_id}/exports", status_code=status.HTTP_201_CREATED, response_model=ProofExport)
async def create_proof_export(report_id: UUID, body: ProofExportCreate, user: CurrentUser) -> ProofExport:
    """Store an export through the blob store and return a short-lived download link (see `expires_at`)."""
    return await proof_reports.create_export(user.id, report_id, body.format)


@router.get("/proof-exports/{export_id}/download", response_class=Response, responses={200: {"description": "The stored export."}})
async def download_proof_export(export_id: UUID, token: Annotated[str, Query(min_length=20, max_length=200)]) -> Response:
    """Download with the link's token instead of a bearer token. 404 for an unknown export, a wrong token, or an expired link."""
    return await proof_reports.download_export(export_id, token)


@router.get("/campaigns/{campaign_id}/run-history", response_model=RunHistoryPage)
async def get_campaign_run_history(
    campaign_id: UUID,
    user: CurrentUser,
    limit: Limit = 20,
    offset: Offset = 0,
    run_type: RunType | None = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> RunHistoryPage:
    """Runs of the campaign, newest first: status, models, prompt versions, tokens, estimated cost, errors. Totals cover
    every matching run, not just the page. Costs are estimates, never invoices."""
    return await run_history.campaign_run_history(
        user.id, campaign_id, limit=limit, offset=offset, run_type=run_type, status=run_status
    )


@router.get("/runs/{run_id}/history", response_model=RunHistoryDetail)
async def get_run_history_detail(run_id: UUID, user: CurrentUser) -> RunHistoryDetail:
    """One run with its stage traces, every metered call, and references to its inputs and result."""
    return await run_history.run_history_detail(user.id, run_id)


@router.get("/workspaces/{workspace_id}/data-health", response_model=DataHealth)
async def get_workspace_data_health(
    workspace_id: UUID, user: CurrentUser, mode: Annotated[DataMode, Query(description="live claims, or labeled demo fixtures.")] = "live"
) -> DataHealth:
    """Per source type: last stored retrieval, freshness, cache state, logged attempts and errors. Per region: coverage.
    Reads stored data only; it never calls a source."""
    return await data_health.workspace_data_health(user.id, workspace_id, mode)


@router.get("/workspaces/{workspace_id}/claims/{claim_id}", response_model=ClaimView)
async def get_workspace_claim(workspace_id: UUID, claim_id: UUID, user: CurrentUser) -> ClaimView:
    """One claim with its five tags and sources: the target of every claim link in a report, search hit, or graph."""
    return await claim_lookup.get_claim_view(user.id, workspace_id, claim_id)
