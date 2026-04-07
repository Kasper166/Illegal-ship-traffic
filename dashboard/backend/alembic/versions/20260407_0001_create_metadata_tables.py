"""Create metadata tables for dashboard backend.

Revision ID: 20260407_0001
Revises:
Create Date: 2026-04-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "detection_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("patch_id", sa.String(length=255), nullable=False),
        sa.Column("tile_id", sa.String(length=255), nullable=False),
        sa.Column("bbox_xyxy", sa.JSON(), nullable=False),
        sa.Column("pixel_coords", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("class_label", sa.String(length=128), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scene_id", sa.String(length=255), nullable=False),
        sa.Column("flagged_for_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_dark", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detection_records_patch_id", "detection_records", ["patch_id"], unique=False)
    op.create_index("ix_detection_records_tile_id", "detection_records", ["tile_id"], unique=False)
    op.create_index("ix_detection_records_confidence", "detection_records", ["confidence"], unique=False)
    op.create_index("ix_detection_records_class_label", "detection_records", ["class_label"], unique=False)
    op.create_index("ix_detection_records_lat", "detection_records", ["lat"], unique=False)
    op.create_index("ix_detection_records_lon", "detection_records", ["lon"], unique=False)
    op.create_index("ix_detection_records_timestamp", "detection_records", ["timestamp"], unique=False)
    op.create_index("ix_detection_records_scene_id", "detection_records", ["scene_id"], unique=False)
    op.create_index(
        "ix_detection_records_flagged_for_review",
        "detection_records",
        ["flagged_for_review"],
        unique=False,
    )
    op.create_index("ix_detection_records_is_dark", "detection_records", ["is_dark"], unique=False)
    op.create_index("ix_detection_records_created_at", "detection_records", ["created_at"], unique=False)

    op.create_table(
        "model_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("map50", sa.Float(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_metrics_model_name", "model_metrics", ["model_name"], unique=False)
    op.create_index("ix_model_metrics_map50", "model_metrics", ["map50"], unique=False)
    op.create_index("ix_model_metrics_evaluated_at", "model_metrics", ["evaluated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_metrics_evaluated_at", table_name="model_metrics")
    op.drop_index("ix_model_metrics_map50", table_name="model_metrics")
    op.drop_index("ix_model_metrics_model_name", table_name="model_metrics")
    op.drop_table("model_metrics")

    op.drop_index("ix_detection_records_created_at", table_name="detection_records")
    op.drop_index("ix_detection_records_is_dark", table_name="detection_records")
    op.drop_index("ix_detection_records_flagged_for_review", table_name="detection_records")
    op.drop_index("ix_detection_records_scene_id", table_name="detection_records")
    op.drop_index("ix_detection_records_timestamp", table_name="detection_records")
    op.drop_index("ix_detection_records_lon", table_name="detection_records")
    op.drop_index("ix_detection_records_lat", table_name="detection_records")
    op.drop_index("ix_detection_records_class_label", table_name="detection_records")
    op.drop_index("ix_detection_records_confidence", table_name="detection_records")
    op.drop_index("ix_detection_records_tile_id", table_name="detection_records")
    op.drop_index("ix_detection_records_patch_id", table_name="detection_records")
    op.drop_table("detection_records")
