"""Business logic. Routes call these; these call repositories."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.ext.asyncio import AsyncSession

from ivcommon.schemas.core import StudentProfile, Verdict

from ..models.tables import Approval, DimensionScoreRow, Idea, IdeaVersion, Profile, Run, User, VerdictRow
from ..repositories.repos import (
    ApprovalRepo,
    ConversationRepo,
    IdeaRepo,
    ProfileRepo,
    RunRepo,
    UserRepo,
    VerdictRepo,
)

_ph = PasswordHasher()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class AccountService:
    def __init__(self, s: AsyncSession) -> None:
        self.users = UserRepo(s)

    async def register(self, email: str, password: str) -> User:
        email = email.strip().lower()
        if await self.users.by_email(email):
            raise Conflict("email already registered")
        return await self.users.add(User(id=new_id("u"), email=email, hash=_ph.hash(password)))

    async def verify(self, email: str, password: str) -> User | None:
        u = await self.users.by_email(email.strip().lower())
        if u is None:
            return None
        try:
            _ph.verify(u.hash, password)
        except VerifyMismatchError:
            return None
        return u


PROFILE_FIELDS = ("skills", "hours_per_week", "weeks_available", "team_size", "compute", "goal", "interests")


def profile_to_schema(p: Profile) -> StudentProfile:
    return StudentProfile(
        user_id=p.user_id,
        skills=p.skills,
        hours_per_week=p.hours_per_week,
        weeks_available=p.weeks_available,
        team_size=p.team_size,
        compute=p.compute,  # type: ignore[arg-type]
        goal=p.goal,
        interests=p.interests,
        profile_version=p.profile_version,
    )  # type: ignore[arg-type]


class ProfileService:
    def __init__(self, s: AsyncSession) -> None:
        self.repo = ProfileRepo(s)

    async def get(self, uid: str) -> StudentProfile | None:
        p = await self.repo.get(uid)
        return None if p is None else profile_to_schema(p)

    async def upsert(self, uid: str, data: StudentProfile) -> StudentProfile:
        """Every edit bumps profile_version (it is part of every cache key)."""
        p = await self.repo.get(uid)
        vals = {f: getattr(data, f) for f in PROFILE_FIELDS}
        if p is None:
            p = Profile(user_id=uid, profile_version=1, **vals)
        else:
            changed = any(getattr(p, f) != v for f, v in vals.items())
            for f, v in vals.items():
                setattr(p, f, v)
            if changed:
                p.profile_version += 1
        return profile_to_schema(await self.repo.save(p))


class IdeaService:
    def __init__(self, s: AsyncSession) -> None:
        self.repo = IdeaRepo(s)
        self.verdicts = VerdictRepo(s)
        self.conv = ConversationRepo(s)

    async def create(self, uid: str, title: str, text: str, source: str = "own") -> tuple[Idea, IdeaVersion]:
        idea = Idea(id=new_id("idea"), user_id=uid, title=title or text[:80], source=source)
        v1 = IdeaVersion(idea_id=idea.id, version=1, text=text)
        await self.repo.add(idea, v1)
        return idea, v1

    async def add_version(self, idea_id: str, text: str, change: str | None) -> IdeaVersion:
        if await self.repo.get(idea_id) is None:
            raise NotFound(idea_id)
        n = await self.repo.max_version(idea_id) + 1
        return await self.repo.add_version(IdeaVersion(idea_id=idea_id, version=n, text=text, change_applied=change))

    async def list_for_user(self, uid: str) -> list[dict[str, Any]]:
        out = []
        for i in await self.repo.for_user(uid):
            vs = await self.repo.versions(i.id)
            latest = await self.verdicts.latest(i.id, vs[-1].version) if vs else None
            out.append(
                {
                    "id": i.id,
                    "title": i.title,
                    "source": i.source,
                    "created_at": i.created_at,
                    "versions": len(vs),
                    "latest_verdict": None
                    if latest is None
                    else {"verdict": latest.verdict, "stability": latest.stability, "score": latest.score},
                }
            )
        return out

    async def versions(self, idea_id: str) -> list[dict[str, Any]]:
        out = []
        for v in await self.repo.versions(idea_id):
            vr = await self.verdicts.latest(idea_id, v.version)
            out.append(
                {
                    "version": v.version,
                    "text": v.text,
                    "change_applied": v.change_applied,
                    "created_at": v.created_at,
                    "verdict": None if vr is None else vr.payload,
                }
            )
        return out

    async def save_verdict(self, v: Verdict) -> int:
        row = VerdictRow(
            idea_id=v.idea_id,
            version=v.version,
            run_id=v.run_id,
            verdict=v.verdict,
            stability=v.stability,
            score=v.score,
            confidence=v.confidence,
            payload=v.model_dump(mode="json"),
        )
        scores = [
            DimensionScoreRow(
                dimension=s.dimension,
                score=s.score,
                conf=s.confidence,
                evidence=s.evidence_ids,
                rubric_version=s.rubric_version,
                model=s.model,
            )
            for s in v.scores
        ]
        return (await self.verdicts.add(row, scores)).id

    async def verdict(self, idea_id: str, version: int) -> dict[str, Any] | None:
        r = await self.verdicts.latest(idea_id, version)
        return None if r is None else r.payload

    async def add_turn(self, idea_id: str, turn: dict[str, Any]) -> None:
        await self.conv.append(idea_id, turn)


class RunService:
    def __init__(self, s: AsyncSession) -> None:
        self.repo = RunRepo(s)
        self.approvals = ApprovalRepo(s)

    async def create(
        self,
        uid: str,
        kind: str,
        budget: float,
        idea_id: str | None = None,
        version: int | None = None,
        run_id: str | None = None,
    ) -> Run:
        return await self.repo.add(
            Run(
                id=run_id or new_id("run"),
                user_id=uid,
                kind=kind,
                state="INTAKE",
                idea_id=idea_id,
                version=version,
                budget_usd=budget,
                context={},
            )
        )

    async def get(self, rid: str) -> Run | None:
        return await self.repo.get(rid)

    async def update(self, rid: str, fields: dict[str, Any]) -> Run:
        r = await self.repo.get(rid)
        if r is None:
            raise NotFound(rid)
        if fields.get("state") in ("DONE", "FAILED") and r.finished_at is None:
            fields["finished_at"] = datetime.now(UTC)
        return await self.repo.update(r, fields)

    async def request_approval(self, run_id: str, action: str, cost: float) -> Approval:
        return await self.approvals.add(
            Approval(id=new_id("appr"), run_id=run_id, action=action, estimated_cost=cost, decision="pending")
        )

    async def decide_approval(self, aid: str, approve: bool) -> Approval:
        a = await self.approvals.get(aid)
        if a is None:
            raise NotFound(aid)
        a.decision = "approved" if approve else "declined"
        a.decided_at = datetime.now(UTC)
        await self.approvals.save()
        return a
