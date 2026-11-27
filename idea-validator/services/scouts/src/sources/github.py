"""GitHub REST search API (token from the Secret via M5's connector; respects rate limits through M5)."""

from __future__ import annotations

from .base import RawItem, Source

API = "https://api.github.com/search/repositories"


class GitHub(Source):
    name = "github"
    connector = "github"
    rate_per_s = 25 / 60

    async def fetch_since(
        self, cursor: str | None, query: str | None = None, max_pages: int = 5
    ) -> tuple[list[RawItem], str | None]:
        since = cursor or "2024-01-01"
        q = f"{query or 'topic:saas'} stars:>50 created:>{since}"
        items: list[RawItem] = []
        newest = since
        for page in range(1, max_pages + 1):
            data = await self.fetch(API, {"q": q, "sort": "stars", "per_page": 100, "page": page})
            repos = data.get("items", []) if isinstance(data, dict) else []
            for r in repos:
                created = (r.get("created_at") or "")[:10]
                newest = max(newest, created)
                items.append(
                    RawItem(
                        source=self.name,
                        external_id=str(r["id"]),
                        url=r["html_url"],
                        title=r["name"],
                        text=r.get("description") or "",
                        published_at=created or None,
                        extra={"stars": r.get("stargazers_count", 0), "topics": r.get("topics", [])},
                    )
                )
            if len(repos) < 100:
                break
        return items, newest
