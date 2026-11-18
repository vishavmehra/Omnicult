"""The Aamod demo journey's Live Pulse Tier 3 data: version links, the default alert rules, one evaluation and one stored comparison.

`seed_pulse_t3` is the single hook for `app/services/demo_journey.py`. Call it after `pulse.load_sample` (the readiness
verdicts are stored earlier in the journey), with the demo user and campaign:

    await pulse_t3_demo.seed_pulse_t3(user_id, campaign_id)

It uses the real services over the stored fixture records, so nothing here is a separate copy of a result and no model or
network is involved. The links say which Studio version each sample Pulse version stands for: the Maharashtra original ran as
"v1 Original", and each regional adaptation ran as "v2 Adapted A" in its own state. "v3 Adapted B" has no Studio version and so
no prediction: it is never compared. One alert is acknowledged, so the inbox shows more than one status.
"""

from uuid import UUID

from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
from app.schemas import pulse_t3 as v
from app.services import pulse_sample as sample, pulse_t3, pulse_t3_alerts
from app.services.pulse_t3 import latest_verdicts

ACK_NOTE = "Replacing the Marathi original in Kerala with the Kerala adaptation once its Launch Room verdict is Go."


async def seed_pulse_t3(user_id: UUID, campaign_id: UUID) -> None:
    """Links, default rules, an evaluation and a stored comparison for the campaign. Idempotent: a second call changes nothing."""
    async with read_session() as s:
        verdicts = await latest_verdicts(s, campaign_id)
        links = list((await s.execute(select(m.PulseVersionLink).where(m.PulseVersionLink.campaign_id == campaign_id))).scalars())
    if not links:
        newest: dict[str, tuple[UUID, object]] = {}
        for (region, version_id), (row, _) in verdicts.items():
            if region not in newest or row.computed_at > newest[region][1]:  # type: ignore[operator]
                newest[region] = (version_id, row.computed_at)
        for region, (version_id, _) in sorted(newest.items()):
            label = sample.ORIGINAL if region == "IN-MH" else sample.ADAPTED_A
            await pulse_t3.set_link(user_id, campaign_id, v.PvaLinkSet(region_code=region, pulse_version=label, version_id=version_id))
    if not (await pulse_t3_alerts.list_rules(user_id, campaign_id)).items:
        await pulse_t3_alerts.create_default_rules(user_id, campaign_id)
    await pulse_t3_alerts.evaluate_now(user_id, campaign_id)
    inbox = await pulse_t3_alerts.inbox(user_id, campaign_id, "open")
    kerala = next((a for a in inbox.items if a.region_code == "IN-KL" and a.alert_type == "ctr_drop"), None)
    if kerala is not None:
        await pulse_t3_alerts.transition(user_id, campaign_id, kerala.id, v.AlertTransition(action="acknowledge", note=ACK_NOTE))
    await pulse_t3.save_snapshot(user_id, campaign_id, v.PvaSnapshotCreate(metric="ctr"))
