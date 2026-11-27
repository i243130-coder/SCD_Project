"""Repositories: data access only, no business logic."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tables import (
    Approval,
    Conversation,
    DimensionScoreRow,
    Idea,
    IdeaVersion,
    Profile,
    Run,
    User,
    VerdictRow,
)


class UserRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def by_email(self, email: str) -> User | None:
        return (await self.s.execute(select(User).where(User.email == email))).scalar_one_or_none()

    async def get(self, uid: str) -> User | None:
        return await self.s.get(User, uid)

    async def add(self, user: User) -> User:
        self.s.add(user)
        await self.s.commit()
        return user


class ProfileRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def get(self, uid: str) -> Profile | None:
        return await self.s.get(Profile, uid)

    async def save(self, p: Profile) -> Profile:
        self.s.add(p)
        await self.s.commit()
        await self.s.refresh(p)
        return p


class IdeaRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def add(self, idea: Idea, first: IdeaVersion) -> Idea:
        self.s.add(idea)
        await self.s.flush()
        self.s.add(first)
        await self.s.commit()
        return idea

    async def get(self, idea_id: str) -> Idea | None:
        return await self.s.get(Idea, idea_id)

    async def for_user(self, uid: str) -> list[Idea]:
        q = select(Idea).where(Idea.user_id == uid).order_by(Idea.created_at.desc())
        return list((await self.s.execute(q)).scalars())

    async def versions(self, idea_id: str) -> list[IdeaVersion]:
        q = select(IdeaVersion).where(IdeaVersion.idea_id == idea_id).order_by(IdeaVersion.version)
        return list((await self.s.execute(q)).scalars())

    async def max_version(self, idea_id: str) -> int:
        q = select(func.max(IdeaVersion.version)).where(IdeaVersion.idea_id == idea_id)
        return int((await self.s.execute(q)).scalar() or 0)

    async def add_version(self, v: IdeaVersion) -> IdeaVersion:
        self.s.add(v)
        await self.s.commit()
        return v


class RunRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def add(self, r: Run) -> Run:
        self.s.add(r)
        await self.s.commit()
        return r

    async def get(self, rid: str) -> Run | None:
        return await self.s.get(Run, rid)

    async def update(self, r: Run, fields: dict[str, Any]) -> Run:
        for k, v in fields.items():
            setattr(r, k, v)
        await self.s.commit()
        return r


class VerdictRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def add(self, v: VerdictRow, scores: list[DimensionScoreRow]) -> VerdictRow:
        self.s.add(v)
        await self.s.flush()
        for d in scores:
            d.verdict_id = v.id
            self.s.add(d)
        await self.s.commit()
        return v

    async def latest(self, idea_id: str, version: int) -> VerdictRow | None:
        q = (
            select(VerdictRow)
            .where(VerdictRow.idea_id == idea_id, VerdictRow.version == version)
            .order_by(VerdictRow.id.desc())
            .limit(1)
        )
        return (await self.s.execute(q)).scalar_one_or_none()

    async def for_idea(self, idea_id: str) -> list[VerdictRow]:
        q = select(VerdictRow).where(VerdictRow.idea_id == idea_id).order_by(VerdictRow.version, VerdictRow.id)
        return list((await self.s.execute(q)).scalars())


class ApprovalRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def add(self, a: Approval) -> Approval:
        self.s.add(a)
        await self.s.commit()
        return a

    async def get(self, aid: str) -> Approval | None:
        return await self.s.get(Approval, aid)

    async def save(self) -> None:
        await self.s.commit()


class ConversationRepo:
    def __init__(self, s: AsyncSession) -> None:
        self.s = s

    async def append(self, idea_id: str, turn: dict[str, Any]) -> Conversation:
        c = await self.s.get(Conversation, idea_id)
        if c is None:
            c = Conversation(idea_id=idea_id, turns=[turn])
            self.s.add(c)
        else:
            c.turns = [*c.turns, turn]
        await self.s.commit()
        return c

    async def get(self, idea_id: str) -> Conversation | None:
        return await self.s.get(Conversation, idea_id)
