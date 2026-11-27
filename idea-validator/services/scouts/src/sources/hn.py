"""Hacker News via the official Algolia search API (Show HN launches + Ask HN requests -> gaps)."""

from __future__ import annotations

from datetime import UTC, datetime

from .base import RawItem, Source

ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNews(Source):
    name = "hackernews"
    connector = "hn_algolia"
    rate_per_s = 1.0

    async def fetch_since(
        self, cursor: str | None, query: str | None = None, max_pages: int = 5
    ) -> tuple[list[RawItem], str | None]:
        since = int(cursor or 0)
        items: list[RawItem] = []
        newest = since
        for tag in ("show_hn", "ask_hn"):
            for page in range(max_pages):
                data = await self.fetch(
                    ALGOLIA,
                    {
                        "tags": tag,
                        "query": query or "",
                        "page": page,
                        "hitsPerPage": 100,
                        "numericFilters": f"created_at_i>{since}",
                    },
                )
                hits = data.get("hits", []) if isinstance(data, dict) else []
                for h in hits:
                    ts = int(h.get("created_at_i", 0))
                    newest = max(newest, ts)
                    items.append(
                        RawItem(
                            source=self.name,
                            external_id=str(h["objectID"]),
                            url=h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                            title=h.get("title") or "",
                            text=h.get("story_text") or h.get("title") or "",
                            published_at=datetime.fromtimestamp(ts, UTC).date().isoformat() if ts else None,
                            extra={"kind": tag, "points": h.get("points", 0)},
                        )
                    )
                if not hits or page + 1 >= data.get("nbPages", 0):
                    break
        return items, str(newest)
