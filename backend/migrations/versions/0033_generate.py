"""Generate studio: image, voice-over and jingle runs (Omnicult; additive).

Two CHECK constraints widen, no table changes:
- agent_runs.run_type gains `generate_image`, `generate_voice` and `generate_jingle` (the 15 types of 0023 plus these three);
- assets.derived_role gains `generate_image`, `generate_voice`, `generate_jingle` (AI-generated outputs).

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-18 20:00:00

Chained after 0032 (Remake: Video), so the prior lists carry `remake_video` and its derived roles.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIOR_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation', "
    "'transcreate', 'creative_xray', 'voice_direct', 'remake_visual', 'remake_sound', 'remake_video'"
)
RUN_TYPES = PRIOR_RUN_TYPES + ", 'generate_image', 'generate_voice', 'generate_jingle'"
PRIOR_ROLES = (
    "'keyframe', 'thumbnail', 'audio_track', 'remake_plate', 'remake_visual', 'remake_voiceover', 'remake_music', "
    "'remake_video', 'remake_frame'"
)
ROLES = PRIOR_ROLES + ", 'generate_image', 'generate_voice', 'generate_jingle'"


def _widen(table: str, constraint: str, column: str, values: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{constraint}"), type_="check")
        batch.create_check_constraint(constraint, f"{column} IN ({values})")


def upgrade() -> None:
    _widen("agent_runs", "run_type", "run_type", RUN_TYPES)
    _widen("assets", "derived_role", "derived_role", ROLES)


def downgrade() -> None:
    op.execute("DELETE FROM asset_blobs WHERE asset_id IN (SELECT id FROM assets WHERE derived_role LIKE 'generate_%')")
    op.execute("DELETE FROM assets WHERE derived_role LIKE 'generate_%' AND parent_asset_id IS NOT NULL")
    op.execute("DELETE FROM assets WHERE derived_role LIKE 'generate_%'")
    op.execute("DELETE FROM agent_runs WHERE run_type IN ('generate_image', 'generate_voice', 'generate_jingle')")
    _widen("assets", "derived_role", "derived_role", PRIOR_ROLES)
    _widen("agent_runs", "run_type", "run_type", PRIOR_RUN_TYPES)
