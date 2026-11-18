"""Remake: Visuals and Remake: Sound (Omnicult; additive).

Three CHECK constraints widen, no table changes:
- agent_runs.run_type gains `remake_visual` and `remake_sound` (the union of the list at 0017 plus these two);
- operations.kind gains `remake` (a generated asset written into a new version node);
- assets.derived_role gains `remake_plate`, `remake_visual`, `remake_voiceover`, `remake_music` (AI-generated outputs).

Revision ID: 0023
Revises: 0028
Create Date: 2026-11-18 12:00:00

The lead re-chains this revision when merging (the Phase 3 contract gives every stream `down_revision = "0017"`).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIOR_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation', "
    "'transcreate', 'creative_xray', 'voice_direct'"
)
RUN_TYPES = PRIOR_RUN_TYPES + ", 'remake_visual', 'remake_sound'"
PRIOR_KINDS = (
    "'manual_edit', 'replace_text', 'transcreate', 'apply_chip', 'swap_reference', 'change_setting', 'tone_shift', 'restore'"
)
KINDS = PRIOR_KINDS + ", 'remake'"
PRIOR_ROLES = "'keyframe', 'thumbnail', 'audio_track'"
ROLES = PRIOR_ROLES + ", 'remake_plate', 'remake_visual', 'remake_voiceover', 'remake_music'"


def _widen(table: str, constraint: str, column: str, values: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{constraint}"), type_="check")
        batch.create_check_constraint(constraint, f"{column} IN ({values})")


def upgrade() -> None:
    _widen("agent_runs", "run_type", "run_type", RUN_TYPES)
    _widen("operations", "kind", "kind", KINDS)
    _widen("assets", "derived_role", "derived_role", ROLES)


def downgrade() -> None:
    op.execute("DELETE FROM asset_blobs WHERE asset_id IN (SELECT id FROM assets WHERE derived_role LIKE 'remake_%')")
    op.execute("DELETE FROM assets WHERE derived_role LIKE 'remake_%'")
    op.execute("DELETE FROM operations WHERE kind = 'remake'")
    op.execute("DELETE FROM agent_runs WHERE run_type IN ('remake_visual', 'remake_sound')")
    _widen("assets", "derived_role", "derived_role", PRIOR_ROLES)
    _widen("operations", "kind", "kind", PRIOR_KINDS)
    _widen("agent_runs", "run_type", "run_type", PRIOR_RUN_TYPES)
