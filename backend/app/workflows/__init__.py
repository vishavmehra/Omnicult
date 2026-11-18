"""AI workflows: one LangGraph StateGraph per run type, four stages each.

Workflows are pure (no database access). The run engine (app/services/runs.py) builds the inputs,
passes a progress callback, and persists the returned outcome.
"""

from app.core.config import Settings
from app.llm.gateway import LLMGateway
from app.schemas.common import DataMode
from app.workflows.followup import answer_followup, answer_group_question
from app.workflows.remake import run_remake_sound, run_remake_visual
from app.workflows.transcreate import run_transcreate
from app.workflows.remake_video import run_remake_video
from app.workflows.xray import run_creative_xray
from app.workflows.types import (
    AssetBlob,
    BrandContext,
    OutcomeStatus,
    ProgressFn,
    WorkflowContext,
    WorkflowDeps,
)


def _transcribe_capability(llm: LLMGateway):  # type: ignore[no-untyped-def]
    """The gateway's `transcribe` adapter when it has one; until it does, the transcript is reported unavailable."""
    try:
        return llm.capability("transcribe")
    except KeyError:
        return None


def build_workflow_deps(mode: DataMode, settings: Settings) -> WorkflowDeps:
    """demo -> fixture model provider and fixture culture sources (no network); live -> the Google gateway and the
    live culture adapters."""
    from app.integrations.culture import build_culture_service
    from app.services.media import MediaPipeline  # local ffmpeg work: allowed in demo too, it calls no provider

    if mode == "demo":  # demo never sends uploads or prompts to a provider: no vision, fixture LLM
        return WorkflowDeps(llm=LLMGateway(settings, fixture=True), media=MediaPipeline(),
                            culture=build_culture_service(settings, mode="demo"))
    llm = LLMGateway(settings)
    return WorkflowDeps(
        llm=llm, vision=llm.capability("vision"), media=MediaPipeline(), transcribe=_transcribe_capability(llm),
        culture=build_culture_service(settings, mode="live", research=llm.capability("grounded_research")),
    )


__all__ = [
    "AssetBlob",
    "BrandContext",
    "OutcomeStatus",
    "ProgressFn",
    "WorkflowContext",
    "WorkflowDeps",
    "build_workflow_deps",
    "run_transcreate",
    "run_creative_xray",
    "run_remake_visual",
    "run_remake_sound",
    "run_remake_video",
    "answer_followup",
    "answer_group_question",
]
