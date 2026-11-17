from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.schemas.search import SearchKind, SearchResults
from app.services import search as service

router = APIRouter(tags=["search"])


@router.get("/projects/{project_id}/search", response_model=SearchResults)
async def search_project(
    project_id: UUID,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=300)],
    kinds: Annotated[list[SearchKind] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
    region_code: Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$", description="Only hits about this region.")] = None,
) -> SearchResults:
    """Semantic search with stored embeddings over evidence, brand examples, claims and their sources, and results.
    Searches only what the project's workspace can see. status=unavailable (never fabricated hits) when not configured."""
    return await service.search(user.id, project_id, q, kinds, limit, region_code)
