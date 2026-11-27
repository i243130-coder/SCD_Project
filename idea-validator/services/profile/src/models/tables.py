"""SQLAlchemy tables for Section 6.1 (application data)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    skills: Mapped[list[str]] = mapped_column(JSONType, default=list)
    hours_per_week: Mapped[float] = mapped_column(Float)
    weeks_available: Mapped[int] = mapped_column(Integer)
    team_size: Mapped[int] = mapped_column(Integer)
    compute: Mapped[str] = mapped_column(String(20))
    goal: Mapped[str] = mapped_column(String(20))
    interests: Mapped[list[str]] = mapped_column(JSONType, default=list)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Idea(Base):
    __tablename__ = "ideas"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(20))  # own | generated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IdeaVersion(Base):
    __tablename__ = "idea_versions"
    idea_id: Mapped[str] = mapped_column(ForeignKey("ideas.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    change_applied: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(40))
    idea_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_usd: Mapped[float] = mapped_column(Float, default=0.05)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VerdictRow(Base):
    __tablename__ = "verdicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idea_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(30))
    stability: Mapped[str] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)


class DimensionScoreRow(Base):
    __tablename__ = "dimension_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    verdict_id: Mapped[int] = mapped_column(ForeignKey("verdicts.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    conf: Mapped[float] = mapped_column(Float)
    evidence: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rubric_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(60))
    estimated_cost: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(20), default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    idea_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)


class TraceIndex(Base):
    __tablename__ = "traces_index"
    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20))
    n_steps: Mapped[int] = mapped_column(Integer, default=0)
    trace_file: Mapped[str] = mapped_column(String(300))
