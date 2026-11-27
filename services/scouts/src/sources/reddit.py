"""Reddit official API (optional; TODO(human): OAuth app credentials, respect the Reddit API terms)."""

from __future__ import annotations

from datetime import UTC, datetime

from .base import RawItem, Source

SUBS = ("SideProject", "startups", "Entrepreneur")


class Reddit(Source):
    name = "reddit"
    connector = "reddit"
    rate_per_s = 1.0

    async def fetch_since(
        self, cursor: str | None, query: str | None = None, max_pages: int = 2
    ) -> tuple[list[RawItem], str | None]:
        since = float(cursor or 0)
        items, newest = [], since
        for sub in SUBS:
            data = await self.fetch(
                f"https://oauth.reddit.com/r/{sub}/search",
                {"q": query or "is there a tool", "restrict_sr": 1, "sort": "new", "limit": 100},
            )
            for ch in (data or {}).get("data", {}).get("children", []) if isinstance(data, dict) else []:
                d = ch["data"]
                if d["created_utc"] <= since:
                    continue
                newest = max(newest, d["created_utc"])
                items.append(
                    RawItem(
                        source=self.name,
                        external_id=d["id"],
                        url=f"https://www.reddit.com{d['permalink']}",
                        title=d["title"],
                        text=d.get("selftext", "")[:3000],
                        published_at=datetime.fromtimestamp(d["created_utc"], UTC).date().isoformat(),
                    )
                )
        return items, str(newest)
