"""Demo hook for Creative Studio Tier 3, for `services/demo_journey.py` to call once the version tree exists.

Format Fit and Script Check are computed on every read, so the Aamod journey already shows them. Claim Guard stores its
checks, so this seeds one: the original Maharashtra version, wording rules first and then the labelled fixture second pass, so
the planted "सर्वोत्तम" (best) claim and the implied delivery promise are on the Claim Guard tab the first time it opens.
Nothing is reviewed: a person still has to decide each finding.
"""

from uuid import UUID

from app.schemas import studio_t3 as t
from app.services import claim_guard


async def seed_studio_t3_demo(user_id: UUID, campaign_id: UUID, version_id: UUID) -> UUID:
    """Run Claim Guard (rules and the fixture model pass; no provider, no network) on `version_id`. Returns the check id."""
    check = await claim_guard.run_check(user_id, campaign_id, t.ClaimGuardRun(version_id=version_id, include_model_pass=True))
    return check.id
