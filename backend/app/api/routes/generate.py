"""Generate studio: new creative assets from the campaign's brief and Brand Kit (image, voice-over, jingle).

The three starters return 202 with a run (run_types generate_image, generate_voice, generate_jingle; Idempotency-Key honoured).
A live project must set `confirm_cost`; 503 when the model it needs is not configured. The gallery is the campaign's finished
generate runs, failed ones included, so a provider error is never hidden.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import generate as g
from app.schemas.runs import RunAccepted
from app.services import generate

router = APIRouter(prefix="/campaigns/{campaign_id}/generate", tags=["generate"])


@router.get("/capabilities", response_model=g.GenerateCapabilities)
async def generate_capabilities(campaign_id: UUID, user: CurrentUser) -> g.GenerateCapabilities:
    """The generator registry (which generators exist here, their model and estimated cost), the formats, voices, languages and
    jingle options, and what the Brand Kit and brief give the generators. Makes no model call."""
    return await generate.capabilities(user.id, campaign_id)


@router.post("/image", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_generate_image(campaign_id: UUID, body: g.GenerateImageRequest, user: CurrentUser) -> RunAccepted:
    """A key visual or social post for a region and format (run_type generate_image)."""
    return await generate.start_image(user.id, campaign_id, body)


@router.post("/voice", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_generate_voice(campaign_id: UUID, body: g.GenerateVoiceRequest, user: CurrentUser) -> RunAccepted:
    """A voice-over of the given lines, joined into one track with timings (run_type generate_voice)."""
    return await generate.start_voice(user.id, campaign_id, body)


@router.post("/jingle", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_generate_jingle(campaign_id: UUID, body: g.GenerateJingleRequest, user: CurrentUser) -> RunAccepted:
    """A short instrumental jingle from Lyria (run_type generate_jingle; Vertex AI only)."""
    return await generate.start_jingle(user.id, campaign_id, body)


@router.get("/items", response_model=g.GenerateItemPage)
async def list_generated_items(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, kind: Annotated[g.GenerateKind | None, Query()] = None,
) -> g.GenerateItemPage:
    """Finished generate runs, newest first: what each made, its provenance and cost, or the error of a run that failed."""
    return await generate.list_items(user.id, campaign_id, limit, offset, kind)


@router.get("/items/{run_id}", response_model=g.GenerateItem)
async def get_generated_item(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> g.GenerateItem:
    return await generate.get_item(user.id, campaign_id, run_id)


@router.post("/items/{run_id}/use-in-studio", status_code=status.HTTP_201_CREATED, response_model=g.GenerateUsed)
async def use_generated_item_in_studio(
    campaign_id: UUID, run_id: UUID, user: CurrentUser, body: g.GenerateUseInStudioRequest = g.GenerateUseInStudioRequest(),
) -> g.GenerateUsed:
    """Add the output to a Studio version as a new element: a new version node, the source untouched. 409 when the campaign has
    no version, the run made no file, or the output is already an element of that version."""
    return await generate.use_in_studio(user.id, campaign_id, run_id, body)
