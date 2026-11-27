"""initial application tables (Section 6.1)

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

J = sa.JSON().with_variant(JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("hash", sa.String(255), nullable=False),
        sa.Column("created_at", TS),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("skills", J),
        sa.Column("hours_per_week", sa.Float),
        sa.Column("weeks_available", sa.Integer),
        sa.Column("team_size", sa.Integer),
        sa.Column("compute", sa.String(20)),
        sa.Column("goal", sa.String(20)),
        sa.Column("interests", J),
        sa.Column("profile_version", sa.Integer),
        sa.Column("updated_at", TS),
    )
    op.create_table(
        "ideas",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), index=True),
        sa.Column("title", sa.String(300)),
        sa.Column("source", sa.String(20)),
        sa.Column("created_at", TS),
    )
    op.create_table(
        "idea_versions",
        sa.Column("idea_id", sa.String(40), sa.ForeignKey("ideas.id"), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text),
        sa.Column("change_applied", sa.Text, nullable=True),
        sa.Column("created_at", TS),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), index=True),
        sa.Column("kind", sa.String(20)),
        sa.Column("state", sa.String(40)),
        sa.Column("idea_id", sa.String(40), nullable=True),
        sa.Column("version", sa.Integer, nullable=True),
        sa.Column("budget_usd", sa.Float),
        sa.Column("spent_usd", sa.Float),
        sa.Column("context", J),
        sa.Column("created_at", TS),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_table(
        "verdicts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("idea_id", sa.String(40), index=True),
        sa.Column("version", sa.Integer),
        sa.Column("run_id", sa.String(40)),
        sa.Column("verdict", sa.String(30)),
        sa.Column("stability", sa.String(20)),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float),
        sa.Column("payload", J),
    )
    op.create_table(
        "dimension_scores",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("verdict_id", sa.Integer, sa.ForeignKey("verdicts.id"), index=True),
        sa.Column("dimension", sa.String(30)),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("conf", sa.Float),
        sa.Column("evidence", J),
        sa.Column("rubric_version", sa.String(40)),
        sa.Column("model", sa.String(80)),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("run_id", sa.String(40), index=True),
        sa.Column("action", sa.String(60)),
        sa.Column("estimated_cost", sa.Float),
        sa.Column("decision", sa.String(20)),
        sa.Column("decided_at", TS, nullable=True),
    )
    op.create_table("conversations", sa.Column("idea_id", sa.String(40), primary_key=True), sa.Column("turns", J))
    op.create_table(
        "traces_index",
        sa.Column("run_id", sa.String(40), primary_key=True),
        sa.Column("cost", sa.Float),
        sa.Column("latency", sa.Integer),
        sa.Column("status", sa.String(20)),
        sa.Column("n_steps", sa.Integer),
        sa.Column("trace_file", sa.String(300)),
    )


def downgrade() -> None:
    for t in (
        "traces_index",
        "conversations",
        "approvals",
        "dimension_scores",
        "verdicts",
        "runs",
        "idea_versions",
        "ideas",
        "profiles",
        "users",
    ):
        op.drop_table(t)
