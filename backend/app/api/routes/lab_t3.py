"""Audience Lab sessions: Live Focus Group, Buzz Simulator and Message Check (Omnicult).

Like Quick Read, a session starts with 202 and finishes in the background; poll the result resource. Send an Idempotency-Key
header on the POST that starts one so a retry returns the run it already created. Every participant, turn, post and restatement is
synthetic. Counts, rates, themes and spread are computed by code from what was saved; none of it predicts real behaviour.
"""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas import audience as av
from app.schemas import lab_buzz as bv
from app.schemas import lab_focus_group as fv
from app.schemas import lab_message_check as mv
from app.schemas import lab_sessions as sv
from app.services import audience, lab_buzz, lab_focus_group, lab_message_check, lab_t3

router = APIRouter(tags=["audience-lab"])


@router.get("/campaigns/{campaign_id}/lab-session-defaults", response_model=sv.LabSessionDefaults)
async def get_lab_session_defaults(campaign_id: UUID, user: CurrentUser) -> sv.LabSessionDefaults:
    """What the Focus Group, Buzz and Message Check forms start from: the default guide, platforms, the brief's primary message and its
    key points, and the server limits."""
    return await lab_t3.session_defaults(user.id, campaign_id)


# --- Live Focus Group ----------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/focus-groups", status_code=status.HTTP_202_ACCEPTED, response_model=av.AudienceRunAccepted)
async def start_focus_group(campaign_id: UUID, body: fv.FocusGroupCreate, user: CurrentUser) -> av.AudienceRunAccepted:
    """A moderated text discussion among participants of a finished Quick Read or Audience Study. The moderator asks the guide's
    questions in turn and the participants reply to the question and to each other."""
    return await lab_focus_group.start_focus_group(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/focus-groups", response_model=av.AudienceRunPage)
async def list_focus_groups(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> av.AudienceRunPage:
    return await audience.list_runs(user.id, campaign_id, "focus_group", limit, offset)


@router.get("/campaigns/{campaign_id}/focus-groups/{run_id}", response_model=fv.FocusGroupResult)
async def get_focus_group(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> fv.FocusGroupResult:
    """The transcript so far, with themes, splits and position changes counted from it. Poll while status is queued or running."""
    return await lab_focus_group.get_session(user.id, campaign_id, run_id)


@router.post("/campaigns/{campaign_id}/focus-groups/{run_id}/interjections", status_code=status.HTTP_201_CREATED,
             response_model=fv.FocusGroupInterjectionView)
async def interject_in_focus_group(
    campaign_id: UUID, run_id: UUID, body: fv.FocusGroupInterjectionCreate, user: CurrentUser
) -> fv.FocusGroupInterjectionView:
    """Ask the group something while it runs. The moderator relays it at the next turn boundary. 409 once the session has finished."""
    return await lab_focus_group.interject(user.id, campaign_id, run_id, body)


# --- Buzz Simulator ------------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/buzz-simulations", status_code=status.HTTP_202_ACCEPTED, response_model=av.AudienceRunAccepted)
async def start_buzz_simulation(campaign_id: UUID, body: bv.BuzzCreate, user: CurrentUser) -> av.AudienceRunAccepted:
    """Synthetic posts, replies and reshares in response to a creative, per state and language. An illustration, not a forecast."""
    return await lab_buzz.start_buzz(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/buzz-simulations", response_model=av.AudienceRunPage)
async def list_buzz_simulations(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> av.AudienceRunPage:
    return await audience.list_runs(user.id, campaign_id, "buzz_sim", limit, offset)


@router.get("/campaigns/{campaign_id}/buzz-simulations/{run_id}", response_model=bv.BuzzResult)
async def get_buzz_simulation(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> bv.BuzzResult:
    return await lab_buzz.get_simulation(user.id, campaign_id, run_id)


# --- Message Check -------------------------------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/message-checks", status_code=status.HTTP_202_ACCEPTED, response_model=av.AudienceRunAccepted)
async def start_message_check(campaign_id: UUID, body: mv.MessageCheckCreate, user: CurrentUser) -> av.AudienceRunAccepted:
    """Check whether the intended message (default: the brief's primary message) lands in each region: comprehension, recall and
    misreadings, from synthetic participants who read only the regional copy."""
    return await lab_message_check.start_message_check(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/message-checks", response_model=av.AudienceRunPage)
async def list_message_checks(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> av.AudienceRunPage:
    return await audience.list_runs(user.id, campaign_id, "message_check", limit, offset)


@router.get("/campaigns/{campaign_id}/message-checks/{run_id}", response_model=mv.MessageCheckResult)
async def get_message_check(campaign_id: UUID, run_id: UUID, user: CurrentUser) -> mv.MessageCheckResult:
    return await lab_message_check.get_check(user.id, campaign_id, run_id)
