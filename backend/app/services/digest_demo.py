"""Demo hook for Comment Pulse and the Weekly Digest on the Aamod journey (no provider, no network).

`seed_comment_pulse_and_digests` is called once from `services/demo_journey.py`, after the Live Pulse sample is loaded (and
after the readiness verdicts exist, so the digest has something to report): it loads the labelled sample comments, reads
them with the labelled fixture model, and stores the digests of the week in progress and the weeks before it, so the Digest
tab opens already populated with past digests. It calls the same services the API calls; nothing is written directly.
"""

from datetime import datetime, timedelta
from uuid import UUID

from app.db.base import utcnow
from app.schemas.digest import DigestCreate
from app.services import comment_pulse, digest
from app.services.digest_build import current_week

DEMO_WEEKS = 3


async def seed_comment_pulse_and_digests(user_id: UUID, campaign_id: UUID, *, now: datetime | None = None, weeks: int = DEMO_WEEKS) -> None:
    now = now or utcnow()
    await comment_pulse.load_sample(user_id, campaign_id)
    await comment_pulse.read(user_id, campaign_id, force=False)  # a demo project reads from fixtures: no model is called
    start = current_week(now).start
    for i in range(weeks):
        await digest.create_digest(user_id, campaign_id, DigestCreate(week_of=start - timedelta(days=7 * i)), now=now)
