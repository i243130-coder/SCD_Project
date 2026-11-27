"""Product Hunt API v2 (GraphQL) with a developer token (TODO(human): obtain PRODUCTHUNT_TOKEN)."""

from __future__ import annotations

from .base import RawItem, Source

API = "https://api.producthunt.com/v2/api/graphql"
QUERY = """query($after: String, $postedAfter: DateTime) { posts(first: 50, after: $after, postedAfter: $postedAfter) {
  pageInfo { endCursor hasNextPage } edges { node { id name tagline description url createdAt
  topics { edges { node { name } } } } } } }"""


class ProductHunt(Source):
    name = "producthunt"
    connector = "producthunt"
    rate_per_s = 0.5

    async def fetch_since(
        self, cursor: str | None, query: str | None = None, max_pages: int = 5
    ) -> tuple[list[RawItem], str | None]:
        after, items, newest = None, [], cursor or "2024-01-01T00:00:00Z"
        for _ in range(max_pages):
            data = await self.fetch(
                API, method="POST", json_body={"query": QUERY, "variables": {"after": after, "postedAfter": cursor}}
            )
            posts = (data or {}).get("data", {}).get("posts", {}) if isinstance(data, dict) else {}
            for e in posts.get("edges", []):
                n = e["node"]
                newest = max(newest, n["createdAt"])
                items.append(
                    RawItem(
                        source=self.name,
                        external_id=n["id"],
                        url=n["url"],
                        title=n["name"],
                        text=f"{n.get('tagline', '')}. {n.get('description') or ''}",
                        published_at=n["createdAt"][:10],
                        extra={"topics": [t["node"]["name"] for t in n.get("topics", {}).get("edges", [])]},
                    )
                )
            if not posts.get("pageInfo", {}).get("hasNextPage"):
                break
            after = posts["pageInfo"]["endCursor"]
        return items, newest
