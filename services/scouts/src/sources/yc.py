"""YC companies from a public open dataset (TODO(human): confirm the dataset's licence/terms in a decision record;
the URL is configured with YC_DATASET_URL and must be on M5's allow-list)."""

from __future__ import annotations

import os

from .base import RawItem, Source


class YC(Source):
    name = "yc"
    connector = "yc"
    rate_per_s = 0.5

    async def fetch_since(
        self, cursor: str | None, query: str | None = None, max_pages: int = 1
    ) -> tuple[list[RawItem], str | None]:
        url = os.environ.get("YC_DATASET_URL", "https://www.ycombinator.com/companies/export.json")
        data = await self.fetch(url)
        rows = data if isinstance(data, list) else data.get("companies", []) if isinstance(data, dict) else []
        items = [
            RawItem(
                source=self.name,
                external_id=str(c.get("id") or c.get("slug")),
                url=c.get("website") or c.get("url", ""),
                title=c.get("name", ""),
                text=f"{c.get('one_liner', '')}. {c.get('long_description', '')}",
                published_at=f"{c['launched_at']}"[:10] if c.get("launched_at") else None,
                extra={"batch": c.get("batch"), "status": c.get("status"), "industry": c.get("industry")},
            )
            for c in rows
            if c.get("name")
        ]
        return items, cursor
