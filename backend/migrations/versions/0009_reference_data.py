"""Reference data tables: languages, regions, country_packs, region_language_profiles, regional_moments.

Schema only. The rows (36 Indian states and union territories, languages, the IN pack, curated moments) are loaded by
`python -m scripts.seed_reference_data`, which is idempotent and safe to re-run, so a data fix never needs a migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17 14:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "languages",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("native_name", sa.String(), nullable=True),
        sa.Column("script", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("code_standard", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("direction IN ('ltr', 'rtl')", name=op.f("ck_languages_direction")),
        sa.CheckConstraint("code_standard IN ('iso639-1', 'iso639-3')", name=op.f("ck_languages_code_standard")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_languages")),
    )
    op.create_table(
        "regions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("primary_language_code", sa.String(), nullable=True),
        sa.Column("primary_script", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('state', 'union_territory')", name=op.f("ck_regions_kind")),
        sa.ForeignKeyConstraint(["primary_language_code"], ["languages.code"], name=op.f("fk_regions_primary_language_code_languages")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regions")),
        sa.UniqueConstraint("code", name=op.f("uq_regions_code")),
    )
    op.create_index("ix_regions_country_code_name", "regions", ["country_code", "name"], unique=False)
    op.create_table(
        "country_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("pack", JSON, nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_country_packs")),
        sa.UniqueConstraint("country_code", "version", name=op.f("uq_country_packs_country_code_version")),
    )
    op.create_table(
        "region_language_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("region_id", sa.Uuid(), nullable=False),
        sa.Column("language_code", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("script", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.CheckConstraint("role IN ('primary', 'secondary', 'code_mixed')", name=op.f("ck_region_language_profiles_role")),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], name=op.f("fk_region_language_profiles_region_id_regions")),
        sa.ForeignKeyConstraint(["language_code"], ["languages.code"], name=op.f("fk_region_language_profiles_language_code_languages")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_region_language_profiles")),
        sa.UniqueConstraint("region_id", "language_code", name=op.f("uq_region_language_profiles_region_id_language_code")),
    )
    op.create_table(
        "regional_moments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("region_id", sa.Uuid(), nullable=True),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("recurrence", sa.String(), nullable=False),
        sa.Column("typical_months", JSON, nullable=False),
        sa.Column("calendar", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.CheckConstraint("kind IN ('festival', 'holiday', 'season', 'event')", name=op.f("ck_regional_moments_kind")),
        sa.CheckConstraint("calendar IN ('solar', 'lunisolar', 'civil')", name=op.f("ck_regional_moments_calendar")),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], name=op.f("fk_regional_moments_region_id_regions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regional_moments")),
        sa.UniqueConstraint("country_code", "slug", "region_id", name=op.f("uq_regional_moments_country_code_slug_region_id")),
    )


def downgrade() -> None:
    op.drop_table("regional_moments")
    op.drop_table("region_language_profiles")
    op.drop_table("country_packs")
    op.drop_index("ix_regions_country_code_name", table_name="regions")
    op.drop_table("regions")
    op.drop_table("languages")
