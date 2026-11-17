"""Creative Studio: the version tree, operations, locks, Tweak Chips, Transcreate and the Brand Glossary.

Everything is scoped by campaign and authorized by workspace membership (a stranger gets 404; viewers and reviewers get
403 on writes). Operations never change the version they start from; a locked element refuses the operation (409).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import versions as v
from app.schemas.runs import RunAccepted
from app.services import chips, glossary, transcreate, versions

router = APIRouter(tags=["creative-studio"])

# --- version tree -----------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/versions", response_model=v.VersionPage)
async def list_versions(campaign_id: UUID, user: CurrentUser, limit: Limit = 50, offset: Offset = 0) -> v.VersionPage:
    """Every node of the campaign's version tree, oldest first. `parent_id` gives the tree."""
    return await versions.list_versions(user.id, campaign_id, limit, offset)


@router.post("/campaigns/{campaign_id}/versions", status_code=status.HTTP_201_CREATED, response_model=v.VersionNode)
async def create_version(campaign_id: UUID, body: v.VersionCreate, user: CurrentUser) -> v.VersionNode:
    """Import an original as a root version (from the campaign's current copy unless elements are given)."""
    return await versions.create_version(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/versions/{version_id}", response_model=v.VersionNode)
async def get_version(campaign_id: UUID, version_id: UUID, user: CurrentUser) -> v.VersionNode:
    return await versions.get_version(user.id, campaign_id, version_id)


@router.get("/campaigns/{campaign_id}/versions/{from_id}/diff/{to_id}", response_model=v.VersionDiff)
async def diff_versions(campaign_id: UUID, from_id: UUID, to_id: UUID, user: CurrentUser) -> v.VersionDiff:
    """Added, removed, changed and preserved elements between any two versions of the campaign, and setting changes."""
    return await versions.diff_versions(user.id, campaign_id, from_id, to_id)


@router.post(
    "/campaigns/{campaign_id}/versions/{version_id}/restore", status_code=status.HTTP_201_CREATED, response_model=v.OperationResult
)
async def restore_version(
    campaign_id: UUID, version_id: UUID, user: CurrentUser, body: v.RestoreRequest = v.RestoreRequest()
) -> v.OperationResult:
    """A new version that copies an earlier one. Refused (409) if it would change a locked element."""
    return await versions.restore_version(user.id, campaign_id, version_id, body)


# --- operations -------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/operations", status_code=status.HTTP_201_CREATED, response_model=v.OperationResult)
async def apply_operation(campaign_id: UUID, body: v.OperationRequest, user: CurrentUser) -> v.OperationResult:
    """Apply one operation to a version: a new version is created and the source is untouched. An operation that targets
    a locked element is refused with 409 and recorded as a rejected operation."""
    return await versions.apply_operation(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/operations", response_model=v.OperationPage)
async def list_operations(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 50, offset: Offset = 0, version_id: UUID | None = None,
    operation_status: Annotated[v.OperationStatus | None, Query(alias="status")] = None,
    kind: v.OperationKind | None = None,
) -> v.OperationPage:
    """Newest first, including refused operations. `version_id` matches the source or the result version."""
    return await versions.list_operations(user.id, campaign_id, limit, offset, version_id, operation_status, kind)


@router.get("/campaigns/{campaign_id}/operations/{operation_id}", response_model=v.Operation)
async def get_operation(campaign_id: UUID, operation_id: UUID, user: CurrentUser) -> v.Operation:
    """One operation. A transcreate operation's `params.lines` hold every line with its back-translation and checks."""
    return await versions.get_operation(user.id, campaign_id, operation_id)


# --- locks ----------------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/locks", response_model=v.LockPage)
async def list_locks(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 100, offset: Offset = 0, include_released: bool = False
) -> v.LockPage:
    """Active locks; `include_released` adds the history of released ones."""
    return await versions.list_locks(user.id, campaign_id, limit, offset, include_released)


@router.put("/campaigns/{campaign_id}/locks/{element_id}", response_model=v.Lock)
async def set_lock(campaign_id: UUID, element_id: v.ElementId, user: CurrentUser, body: v.LockCreate = v.LockCreate()) -> v.Lock:
    """Lock an element in every version of the campaign. Idempotent."""
    return await versions.set_lock(user.id, campaign_id, element_id, body)


@router.delete("/campaigns/{campaign_id}/locks/{element_id}", response_model=v.Lock)
async def unset_lock(campaign_id: UUID, element_id: v.ElementId, user: CurrentUser) -> v.Lock:
    """Release the active lock (kept in the history). 404 when the element is not locked."""
    return await versions.unset_lock(user.id, campaign_id, element_id)


# --- Tweak Chips ----------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/chips/generate", status_code=status.HTTP_201_CREATED, response_model=v.ChipsGenerated)
async def generate_chips(campaign_id: UUID, body: v.ChipGenerate, user: CurrentUser) -> v.ChipsGenerated:
    """Propose chips for one element from the region's claims. One model call; proposals that cite unknown claims, cannot
    be applied or break a glossary rule are dropped in code (`dropped`, `notes`)."""
    return await chips.generate_chips(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/chips", response_model=v.ChipPage)
async def list_chips(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 50, offset: Offset = 0, version_id: UUID | None = None,
    element_id: str | None = None, chip_status: Annotated[v.ChipStatus | None, Query(alias="status")] = None,
) -> v.ChipPage:
    return await chips.list_chips(user.id, campaign_id, limit, offset, version_id, element_id, chip_status)


@router.post("/campaigns/{campaign_id}/chips/{chip_id}/apply", status_code=status.HTTP_201_CREATED, response_model=v.ChipApplied)
async def apply_chip(campaign_id: UUID, chip_id: UUID, user: CurrentUser, body: v.ChipApply = v.ChipApply()) -> v.ChipApplied:
    """Apply a chip through the operation engine: a new version, locks enforced (409 if its element is locked)."""
    return await chips.apply_chip(user.id, campaign_id, chip_id, body)


# --- Transcreate -----------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/transcreate", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_transcreate(campaign_id: UUID, body: v.TranscreateRequest, user: CurrentUser) -> RunAccepted:
    """Transcreate text elements into a regional language (run_type transcreate; honours Idempotency-Key). The result is
    a new version (run result `version`) or, when nothing could be applied, a refused operation (`operation`)."""
    return await transcreate.start_transcreate(user.id, campaign_id, body)


# --- Brand Glossary (the brand's glossary, reached through any of its campaigns) --------------------------------


@router.get("/campaigns/{campaign_id}/glossary", response_model=v.GlossaryTermPage)
async def list_glossary(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 100, offset: Offset = 0, language: str | None = None
) -> v.GlossaryTermPage:
    return await glossary.list_terms(user.id, campaign_id, limit, offset, language)


@router.post("/campaigns/{campaign_id}/glossary", status_code=status.HTTP_201_CREATED, response_model=v.GlossaryTerm)
async def create_glossary_term(campaign_id: UUID, body: v.GlossaryTermCreate, user: CurrentUser) -> v.GlossaryTerm:
    return await glossary.create_term(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/glossary/{term_id}", response_model=v.GlossaryTerm)
async def get_glossary_term(campaign_id: UUID, term_id: UUID, user: CurrentUser) -> v.GlossaryTerm:
    return await glossary.get_term(user.id, campaign_id, term_id)


@router.patch("/campaigns/{campaign_id}/glossary/{term_id}", response_model=v.GlossaryTerm)
async def update_glossary_term(campaign_id: UUID, term_id: UUID, body: v.GlossaryTermUpdate, user: CurrentUser) -> v.GlossaryTerm:
    return await glossary.update_term(user.id, campaign_id, term_id, body)


@router.delete("/campaigns/{campaign_id}/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(campaign_id: UUID, term_id: UUID, user: CurrentUser) -> Response:
    await glossary.delete_term(user.id, campaign_id, term_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
