"""Campaign Desk: the versioned Campaign Brief, the Brand Kit, and the demo seam.

Brief: every save that changes the content adds a new immutable `campaign_briefs` row; the highest version is current.
Saving also mirrors what other workspaces already read from the campaign record (objective, and target regions as
`target_markets` entries that carry a `region_code`, the convention `services.campaign_regions` reads), so Audience Lab, Proof and
the evidence graph pick the brief's regions up without any change of their own.

Brand Kit: the brand record stays in `brand_kits` (projects service); the design half is one validated JSON document per
brand in `brand_kit_designs`. Contrast ratios are calculated here, never stored or supplied by a client.

Demo seam: `apply_demo_brief_and_brand` maps the two Omnicult demo fixtures onto this schema.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.reference.india import REGIONS
from app.schemas import desk as v
from app.schemas.common import ErrorDetail
from app.services.audit import record_audit
from app.services.common import get_owned, get_project, not_found, paginate, require_writable, touch
from app.services.identity import WRITE_ROLES

REGION_NAME = {r.code: r.name for r in REGIONS}
DEMO_LOCKED = "Demo records are fixed so that the demo fixtures stay truthful. Create a live brand and campaign to write your own."
REQUIRED_LABELS: dict[str, str] = {
    "objective": "an objective",
    "origin_region": "the region the original was made for",
    "target_regions": "at least one target region",
    "languages": "languages for every target region",
    "channels": "at least one channel",
    "budget": "a budget",
    "dates": "campaign dates",
    "success_metric": "a primary success metric",
}


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


# --- brief: pure helpers ----------------------------------------------------------------------------------------


def completeness(content: v.BriefContent) -> v.BriefCompleteness:
    """Which required parts are empty. Rules in code; the list order is the order people fill the brief in."""
    targets = content.regions.targets
    checks: dict[str, bool] = {
        "objective": bool(content.objective),
        "origin_region": content.regions.origin is not None,
        "target_regions": bool(targets),
        "languages": bool(targets) and all(content.languages.get(code) for code in targets),
        "channels": bool(content.channels),
        "budget": content.budget is not None,
        "dates": content.dates is not None,
        "success_metric": content.success_metric is not None,
    }
    missing = [k for k, ok in checks.items() if not ok]
    return v.BriefCompleteness(
        complete=not missing, missing=missing, filled=len(checks) - len(missing), required=len(checks)  # type: ignore[arg-type]
    )


def changed_fields(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    """Top-level fields whose value differs. The first version reports every field it sets."""
    if old is None:
        return sorted(k for k, value in new.items() if value not in (None, [], {}, False))
    return sorted(k for k in new.keys() | old.keys() if new.get(k) != old.get(k))


def region_markets(codes: list[str]) -> list[dict[str, str]]:
    return [{"country_code": code.split("-")[0], "display_name": REGION_NAME[code], "region_code": code} for code in codes]


def derived_content(campaign: m.Campaign) -> v.BriefContent:
    """What a campaign with no saved brief already says: its objective and any region-coded target markets."""
    codes = [t["region_code"] for t in campaign.target_markets if isinstance(t, dict) and t.get("region_code") in REGION_NAME]
    return v.BriefContent(objective=campaign.objective, regions=v.BriefRegions(targets=list(dict.fromkeys(codes))))


def _normalise(content: v.BriefContent, project: m.Project) -> v.BriefContent:
    """A demo project's budget is always labelled sample; the server decides, whatever the client sent."""
    if project.mode == "demo" and content.budget is not None:
        content.budget.sample = True
    return content


def _lock_reason(project: m.Project) -> str | None:
    if project.mode == "demo":
        return DEMO_LOCKED
    if project.status == "archived":
        return "This project is archived and read-only."
    if project.access_role not in WRITE_ROLES:
        return "Your role in this workspace is read-only."
    return None


async def _latest(s: AsyncSession, campaign_id: UUID) -> m.CampaignBriefRow | None:
    stmt = select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
    return (await s.execute(stmt.order_by(m.CampaignBriefRow.version_number.desc()).limit(1))).scalar_one_or_none()


async def _count(s: AsyncSession, campaign_id: UUID) -> int:
    stmt = select(func.count()).select_from(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
    return int(await s.scalar(stmt) or 0)


def _brief_view(campaign: m.Campaign, project: m.Project, row: m.CampaignBriefRow | None, count: int) -> v.CampaignBrief:
    content = _normalise(v.BriefContent.model_validate(row.content) if row else derived_content(campaign), project)
    return v.CampaignBrief(
        campaign_id=campaign.id, project_id=project.id, version=row.version_number if row else 0, saved=row is not None,
        content=content, completeness=completeness(content), change_note=row.change_note if row else None,
        created_at=row.created_at if row else None, created_by=row.created_by if row else None,
        provenance=v.DeskProvenance.model_validate(row.provenance or {}) if row else v.DeskProvenance(),
        version_count=count, mode=project.mode,  # type: ignore[arg-type]
        editable=_lock_reason(project) is None, locked_reason=_lock_reason(project),
    )


async def get_brief(user_id: UUID, campaign_id: UUID) -> v.CampaignBrief:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        return _brief_view(campaign, project, await _latest(s, campaign_id), await _count(s, campaign_id))


def _write_brief(
    s: AsyncSession, campaign: m.Campaign, project: m.Project, latest: m.CampaignBriefRow | None, content: v.BriefContent,
    *, note: str | None, user_id: UUID | None, provenance: v.DeskProvenance,
) -> m.CampaignBriefRow | None:
    """Add the next version unless the content is unchanged; mirror the shared parts onto the campaign. Returns the new row."""
    data = content.model_dump(mode="json")
    if latest is not None and latest.content == data:
        return None
    now = utcnow()
    row = m.CampaignBriefRow(
        id=uuid4(), campaign_id=campaign.id, project_id=project.id, version_number=(latest.version_number if latest else 0) + 1,
        content=data, change_note=note, provenance=provenance.model_dump(mode="json"), created_by=user_id, created_at=now,
    )
    s.add(row)
    if content.objective is not None:
        campaign.objective = content.objective
    if content.regions.targets:  # a brief with no targets leaves the campaign's markets alone
        campaign.target_markets = region_markets(content.regions.targets)
    campaign.updated_at = now
    touch(project)
    return row


async def save_brief(user_id: UUID, campaign_id: UUID, body: v.BriefUpdate) -> v.CampaignBrief:
    async with session() as s, s.begin():
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        if project.mode == "demo":
            raise Conflict(DEMO_LOCKED)
        latest = await _latest(s, campaign_id)
        current = latest.version_number if latest else 0
        if body.expected_version is not None and body.expected_version != current:
            raise Conflict(f"The brief changed since you opened it: version {current} is now current. Reload and apply your edit again.")
        content = _normalise(body.content, project)
        row = _write_brief(s, campaign, project, latest, content, note=body.change_note, user_id=user_id, provenance=v.DeskProvenance())
        if row is not None:
            await s.flush()
            await record_audit(
                s, action="desk.brief_saved", target_type="campaign_brief", target_id=str(row.id), workspace_id=project.workspace_id,
                actor_user_id=user_id, detail={"campaign_id": str(campaign_id), "version": row.version_number},
            )
        saved = row or latest
        return _brief_view(campaign, project, saved, await _count(s, campaign_id))


async def list_brief_versions(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> v.BriefVersionPage:
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.CampaignBriefRow.version_number.desc()), limit, offset)
        previous = {}
        if rows:  # the version just below the page, for the diff of its oldest row
            below = await s.scalar(
                select(m.CampaignBriefRow.content).where(
                    m.CampaignBriefRow.campaign_id == campaign_id, m.CampaignBriefRow.version_number == rows[-1].version_number - 1
                )
            )
            previous = {rows[-1].version_number - 1: below}
    by_version = {r.version_number: r.content for r in rows} | previous
    items = [
        v.BriefVersionSummary(
            version=r.version_number, created_at=r.created_at, created_by=r.created_by, change_note=r.change_note,
            changed_fields=changed_fields(by_version.get(r.version_number - 1), r.content),
            provenance=v.DeskProvenance.model_validate(r.provenance or {}),
        )
        for r in rows
    ]
    return v.BriefVersionPage(items=items, limit=limit, offset=offset, total=total)


async def get_brief_version(user_id: UUID, campaign_id: UUID, version: int) -> v.BriefVersion:
    async with read_session() as s:
        _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        rows = {
            r.version_number: r
            for r in (
                await s.execute(
                    select(m.CampaignBriefRow).where(
                        m.CampaignBriefRow.campaign_id == campaign_id, m.CampaignBriefRow.version_number.in_([version, version - 1])
                    )
                )
            ).scalars()
        }
    row = rows.get(version)
    if row is None:
        raise not_found("Brief version")
    previous = rows.get(version - 1)
    return v.BriefVersion(
        campaign_id=campaign_id, version=version, content=_normalise(v.BriefContent.model_validate(row.content), project),
        change_note=row.change_note, created_at=row.created_at, created_by=row.created_by,
        changed_fields=changed_fields(previous.content if previous else None, row.content),
        provenance=v.DeskProvenance.model_validate(row.provenance or {}),
    )


# --- brand kit --------------------------------------------------------------------------------------------------


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    """WCAG 2.x relative luminance of #RRGGBB."""
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast_ratio(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def grade(ratio: float) -> str:
    return "AAA" if ratio >= 7 else "AA" if ratio >= 4.5 else "AA large" if ratio >= 3 else "fail"


def contrast_results(design: v.KitDesign) -> list[v.KitContrastResult]:
    colour = {c.id: c.hex for c in design.colours}
    results = []
    for pair in design.contrast_pairs:
        ratio = round(contrast_ratio(colour[pair.text], colour[pair.background]), 2)
        results.append(v.KitContrastResult(
            text=pair.text, background=pair.background, text_hex=colour[pair.text], background_hex=colour[pair.background],
            ratio=ratio, grade=grade(ratio), note=pair.note,  # type: ignore[arg-type]
        ))
    return results


async def _brand_record(s: AsyncSession, project_id: UUID) -> m.BrandKit:
    return (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one()


async def _glossary_link(s: AsyncSession, project_id: UUID) -> v.KitGlossaryLink:
    terms = (await s.execute(select(m.GlossaryTerm).where(m.GlossaryTerm.project_id == project_id))).scalars().all()
    return v.KitGlossaryLink(
        term_count=len(terms), protected_count=sum(1 for t in terms if t.protected),
        never_translate_count=sum(1 for t in terms if t.never_translate),
        languages=sorted({t.language for t in terms if t.language != "*"}),
    )


async def _kit_row(s: AsyncSession, project_id: UUID) -> m.BrandKitDesignRow | None:
    return (await s.execute(select(m.BrandKitDesignRow).where(m.BrandKitDesignRow.project_id == project_id))).scalar_one_or_none()


def _kit_view(project: m.Project, brand: m.BrandKit, row: m.BrandKitDesignRow | None, glossary: v.KitGlossaryLink) -> v.BrandKit:
    design = v.KitDesign.model_validate(row.design) if row else v.KitDesign()
    return v.BrandKit(
        project_id=project.id, revision=row.revision if row else 0, saved=row is not None,
        updated_at=row.updated_at if row else None, updated_by=row.updated_by if row else None,
        provenance=v.DeskProvenance.model_validate(row.provenance or {}) if row else v.DeskProvenance(),
        name=brand.name, description=brand.description, voice=brand.voice, communication_style=brand.communication_style,
        target_audience=brand.target_audience, preferred_terms=brand.preferred_terms, prohibited_terms=brand.prohibited_terms,
        protected_terms=brand.protected_terms, design=design, contrast=contrast_results(design), glossary=glossary,
        mode=project.mode,  # type: ignore[arg-type]
        editable=_lock_reason(project) is None, locked_reason=_lock_reason(project),
    )


async def get_brand_kit(user_id: UUID, project_id: UUID) -> v.BrandKit:
    async with read_session() as s:
        project = await get_project(s, user_id, project_id)
        return _kit_view(project, await _brand_record(s, project_id), await _kit_row(s, project_id), await _glossary_link(s, project_id))


def _asset_ids(design: v.KitDesign) -> set[UUID]:
    return {x.asset_id for x in [*design.logo.lockups, *design.product_images] if x.asset_id}


async def save_brand_kit(user_id: UUID, project_id: UUID, body: v.KitUpdate) -> v.BrandKit:
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        if project.mode == "demo":
            raise Conflict(DEMO_LOCKED)
        row = await _kit_row(s, project_id)
        current = row.revision if row else 0
        if body.expected_revision is not None and body.expected_revision != current:
            raise Conflict(f"The Brand Kit changed since you opened it: revision {current} is now current. Reload and apply your edit again.")
        wanted = _asset_ids(body.design)
        if wanted:  # an image must be one of this brand's own uploads
            found = set((await s.execute(select(m.Asset.id).where(m.Asset.project_id == project_id, m.Asset.id.in_(wanted)))).scalars())
            if wanted - found:
                raise _invalid("design", "A linked image is not one of this brand's uploads.")
        data = body.design.model_dump(mode="json")
        now = utcnow()
        if row is None:
            row = m.BrandKitDesignRow(
                id=uuid4(), project_id=project_id, revision=1, design=data, provenance=v.DeskProvenance().model_dump(mode="json"),
                updated_by=user_id, created_at=now, updated_at=now,
            )
            s.add(row)
        elif row.design != data:
            row.design, row.revision, row.updated_by, row.updated_at = data, row.revision + 1, user_id, now
            row.provenance = v.DeskProvenance().model_dump(mode="json")
        else:
            return _kit_view(project, await _brand_record(s, project_id), row, await _glossary_link(s, project_id))
        touch(project)
        await s.flush()
        await record_audit(
            s, action="desk.brand_kit_saved", target_type="brand_kit_design", target_id=str(row.id), workspace_id=project.workspace_id,
            actor_user_id=user_id, detail={"project_id": str(project_id), "revision": row.revision},
        )
        return _kit_view(project, await _brand_record(s, project_id), row, await _glossary_link(s, project_id))


async def link_kit_assets(s: AsyncSession, project_id: UUID) -> int:
    """Point Brand Kit images at the project's uploads that carry the same file name as the fixture path. Returns links made.

    Used after demo seeding: the fixture names `brand/logo.png`, the upload is called `logo.png`. Nothing is guessed beyond that."""
    row = await _kit_row(s, project_id)
    if row is None:
        return 0
    assets = (await s.execute(select(m.Asset).where(m.Asset.project_id == project_id, m.Asset.parent_asset_id.is_(None)))).scalars().all()
    by_name = {a.filename.casefold(): a for a in sorted(assets, key=lambda a: a.created_at)}  # the newest upload of a name wins
    design = v.KitDesign.model_validate(row.design)
    made = 0
    for item in [*design.logo.lockups, *design.product_images]:
        path = getattr(item, "source_path", None)
        asset = by_name.get(path.rsplit("/", 1)[-1].casefold()) if path else None
        if asset is not None and item.asset_id != asset.id:
            item.asset_id = asset.id
            made += 1
    if made:
        row.design = design.model_dump(mode="json")
        row.updated_at = utcnow()
    return made


# --- demo seam --------------------------------------------------------------------------------------------------


def _provenance(fixture: dict[str, Any]) -> v.DeskProvenance:
    f = fixture.get("fixture") or {}
    return v.DeskProvenance(source="demo_fixture", fixture_id=f.get("id"), fixture_version=f.get("version"), label=f.get("label"))


def brief_from_fixture(fixture: dict[str, Any]) -> v.BriefContent:
    """`campaign_brief.json` onto the brief schema. Fixture ids that name other fixtures (creatives) stay opaque references."""
    product = fixture.get("product") or {}
    price_inr = product.get("price_inr")
    cta = fixture.get("cta") or {}
    budget = fixture.get("budget")
    payload: dict[str, Any] = {
        "status": fixture.get("status", "planning"),
        "objective": fixture.get("objective"),
        "product": {
            "name": product["name"], "description": product.get("description"), "net_weight_g": product.get("net_weight_g"),
            "price": {"currency": "INR", "amount": price_inr} if price_inr is not None else None, "price_note": product.get("price_note"),
        } if product else None,
        "target_audience": fixture.get("target_audience"),
        "regions": fixture.get("regions") or {},
        "languages": fixture.get("languages") or {},
        "scripts": fixture.get("scripts") or {},
        "channels": [
            {"id": c["id"], "name": c["name"], "format": c.get("format"), "creative_ref": c.get("creative_id")}
            for c in fixture.get("channels") or []
        ],
        "budget": {**budget, "sample": True} if budget else None,  # demo money is always sample money
        "dates": fixture.get("dates"),
        "success_metric": fixture.get("success_metric"),
        "primary_message": fixture.get("primary_message"),
        "cta": {k: cta.get(k) for k in ("text_en", "festival_hook", "original")} if cta else None,
        "original_creative_refs": fixture.get("original_creative_ids") or [],
        "constraints": fixture.get("constraints") or [],
    }
    return v.BriefContent.model_validate(payload)


def kit_from_fixture(fixture: dict[str, Any]) -> v.KitDesign:
    """`brand_kit.json` onto the design schema. Declared contrast ratios are dropped: they are recalculated from the colours."""
    logo = fixture.get("logo") or {}
    payload: dict[str, Any] = {
        "fictional": bool(fixture.get("fictional")),
        "name_meaning": fixture.get("name_meaning"),
        "category": fixture.get("category"),
        "name_check": fixture.get("name_check"),
        "logo": {
            "description": logo.get("description"),
            "lockups": [
                {"id": x["id"], "use": x["use"], "source_path": x.get("png"), "vector_path": x.get("svg")}
                for x in logo.get("lockups") or []
            ],
            "clear_space": logo.get("clear_space"), "min_width_px": logo.get("min_width_px") or {}, "rules": logo.get("rules") or [],
        },
        "colours": fixture.get("colours") or [],
        "contrast_pairs": [
            {"text": p["text"], "background": p["background"], "note": p.get("note")}
            for p in (fixture.get("contrast") or {}).get("pairs") or []
        ],
        "fonts": fixture.get("fonts") or [],
        "typography_rules": fixture.get("typography_rules") or [],
        "tone_of_voice": fixture.get("tone_of_voice") or {},
        "tagline": fixture.get("tagline"),
        "protected_term_rules": fixture.get("protected_terms") or [],
        "never_change": fixture.get("never_change") or [],
        "product_images": [
            {
                "id": x["id"], "source_path": x.get("path"), "width": x.get("width"), "height": x.get("height"),
                "background": x.get("background"), "description": x.get("description"), "provenance": x.get("provenance"),
            }
            for x in fixture.get("product_images") or []
        ],
        "claims_policy": fixture.get("claims_policy") or {},
    }
    return v.KitDesign.model_validate(payload)


def _clip(text: str | None, n: int) -> str | None:
    return text[:n] if text else None


def brand_record_from_fixtures(design: v.KitDesign, kit: dict[str, Any], brief: v.BriefContent) -> dict[str, Any]:
    """The brand-record fields the Brand Kit and brief state: what Studio, Audience Lab and Risk Check read as Brand Memory."""
    constraints = [*brief.constraints, *(f"Do not claim: {c}" for c in design.claims_policy.forbidden)]
    tagline = design.tagline
    return {
        "name": kit["name"],
        "description": _clip(kit.get("description"), 1000),
        "voice": [t[:40] for t in design.tone_of_voice.traits[:10]],
        "communication_style": _clip(design.tone_of_voice.summary, 1000),
        "target_audience": _clip(brief.target_audience.summary if brief.target_audience else None, 300),
        "protected_terms": [p.term[:100] for p in design.protected_term_rules[:30]],
        "approved_examples": [{"text": tagline.text, "note": "Locked brand tagline"}] if tagline else [],
        "constraints": [c[:300] for c in dict.fromkeys(constraints)][:20],
    }


async def apply_demo_brief_and_brand(
    session: AsyncSession, *, project_id: UUID, campaign_id: UUID, brief: dict, brand_kit: dict
) -> None:
    """Seed the demo brief and Brand Kit from `campaign_brief.json` and `brand_kit.json`.

    Runs inside the caller's transaction (flushes, never commits). Idempotent: unchanged content adds no version or revision.
    Sets the campaign name, objective and region-coded target markets, the brand record fields the fixtures state, the brief
    (version 1, provenance `demo_fixture`) and the Brand Kit design. Brand images are linked to uploads of the same file name when
    those uploads already exist; call `link_kit_assets` after uploading them otherwise.
    """
    campaign = await session.get(m.Campaign, campaign_id)
    if campaign is None or campaign.project_id != project_id:
        raise _invalid("campaign_id", "The campaign does not belong to this project.")
    project = await session.get(m.Project, project_id)
    assert project is not None
    content = brief_from_fixture(brief)
    design = kit_from_fixture(brand_kit)
    if brief.get("name"):
        campaign.name = brief["name"][:120]

    latest = await _latest(session, campaign_id)
    _write_brief(session, campaign, project, latest, content, note="Loaded from the demonstration fixture", user_id=None, provenance=_provenance(brief))

    brand = await _brand_record(session, project_id)
    for field, value in brand_record_from_fixtures(design, brand_kit, content).items():
        setattr(brand, field, value)
    now = utcnow()
    brand.updated_at = now

    data = design.model_dump(mode="json")
    row = await _kit_row(session, project_id)
    provenance = _provenance(brand_kit).model_dump(mode="json")
    if row is None:
        session.add(m.BrandKitDesignRow(
            id=uuid4(), project_id=project_id, revision=1, design=data, provenance=provenance, updated_by=None, created_at=now, updated_at=now,
        ))
    elif row.design != data:
        row.design, row.revision, row.provenance, row.updated_at = data, row.revision + 1, provenance, now
    await session.flush()
    await link_kit_assets(session, project_id)
    await session.flush()
