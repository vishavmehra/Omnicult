"""Remake: Video (Omnicult; additive).

Two CHECK constraints widen, no table changes:
- agent_runs.run_type gains `remake_video` (the union of the 15 types of 0023 plus this one);
- assets.derived_role gains `remake_video` (the clip) and `remake_frame` (its start frame), both AI-generated outputs.
`operations.kind` already holds `remake` (0023): the clip is one remake operation like the visual and the voice-over.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-18 18:00:00

The lead re-chains this revision when merging.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIOR_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation', "
    "'transcreate', 'creative_xray', 'voice_direct', 'remake_visual', 'remake_sound'"
)
RUN_TYPES = PRIOR_RUN_TYPES + ", 'remake_video'"
PRIOR_ROLES = "'keyframe', 'thumbnail', 'audio_track', 'remake_plate', 'remake_visual', 'remake_voiceover', 'remake_music'"
ROLES = PRIOR_ROLES + ", 'remake_video', 'remake_frame'"


def _widen(table: str, constraint: str, column: str, values: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{constraint}"), type_="check")
        batch.create_check_constraint(constraint, f"{column} IN ({values})")


def upgrade() -> None:
    _widen("agent_runs", "run_type", "run_type", RUN_TYPES)
    _widen("assets", "derived_role", "derived_role", ROLES)


def downgrade() -> None:
    # the clip's files go first (a joined clip points at the clip as delivered), then the operations that named them
    for _ in range(2):
        op.execute("DELETE FROM asset_blobs WHERE asset_id IN (SELECT id FROM assets WHERE derived_role IN ('remake_video', 'remake_frame') "
                   "AND id NOT IN (SELECT parent_asset_id FROM assets WHERE parent_asset_id IS NOT NULL))")
        op.execute("DELETE FROM assets WHERE derived_role IN ('remake_video', 'remake_frame') "
                   "AND id NOT IN (SELECT parent_asset_id FROM assets WHERE parent_asset_id IS NOT NULL)")
    op.execute("DELETE FROM operations WHERE kind = 'remake' AND result_version_id IN "
               "(SELECT id FROM version_nodes WHERE label LIKE 'Remake: Video%')")
    op.execute("DELETE FROM agent_runs WHERE run_type = 'remake_video'")
    _widen("assets", "derived_role", "derived_role", PRIOR_ROLES)
    _widen("agent_runs", "run_type", "run_type", PRIOR_RUN_TYPES)
