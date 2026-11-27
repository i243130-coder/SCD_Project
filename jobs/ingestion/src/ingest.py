"""M6i ingestion: raw items (scouts) or the snapshot -> normalised IdeaCards -> dedupe -> upsert -> snapshot.

Idempotent: card_id = "card_" + sha1(canonical_url)[:8]; an upsert keyed on the card id + content_hash means a second
run adds 0 cards. Near-duplicates (same normalised name) merge into one card with an extra `sources` row, which is how
one product seen on HN and GitHub counts as 2 platforms.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING = re.compile(r"^(utm_|ref$|ref_|fbclid|gclid|mc_)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_MENTION = re.compile(r"(?<![\w/])@[A-Za-z0-9_]{2,}|\bu/[A-Za-z0-9_-]+")
SOURCE_MAP = {
    "hn": "hackernews",
    "hackernews": "hackernews",
    "github": "github",
    "producthunt": "producthunt",
    "yc": "yc",
    "reddit": "reddit",
}


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)]
    host = (p.hostname or "").lower().removeprefix("www.")
    path = p.path.rstrip("/") or ""
    return urlunparse(("https", host, path, "", urlencode(sorted(q)), ""))


def card_id(url: str) -> str:
    return "card_" + hashlib.sha1(canonical_url(url).encode()).hexdigest()[:8]


def norm_name(name: str) -> str:
    n = re.sub(r"^(show hn|ask hn|launch hn)\s*:\s*", "", name.lower())
    n = re.split(r"\s[-–—:|]\s", n)[0]
    return re.sub(r"[^a-z0-9]+", "", n)


def clean(text: str) -> str:
    return USER_MENTION.sub("[user]", EMAIL.sub("[email]", text or "")).strip()


def normalise(raw: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    src = SOURCE_MAP[raw["source"]]
    text = clean(raw.get("text") or raw.get("title", ""))
    title = clean(raw.get("title") or "")
    summary = (text.split(". ")[0] or title)[:200]
    tags = raw.get("extra", {}).get("topics") or []
    stage = {"yc": "seed"}.get(src, "launched" if src in ("producthunt", "github") else "unknown")
    status = (raw.get("extra", {}).get("status") or "").lower()
    if status in ("acquired", "inactive", "dead"):
        stage = "acquired" if status == "acquired" else "dead"
    body = f"{title}. {text}" if title and title not in text else text
    return {
        "id": card_id(raw["url"]),
        "name": title or summary[:60],
        "summary": summary,
        "problem": "",
        "customer": "",
        "niche_tags": list(tags)[:5],
        "stage": stage,
        "funding_usd": None,
        "source": src,
        "url": raw["url"],
        "canonical_url": canonical_url(raw["url"]),
        "published_at": raw.get("published_at"),
        "fetched_at": fetched_at,
        "text": body,
        "content_hash": hashlib.sha1(body.encode()).hexdigest(),
        "sources": [{"platform": src, "url": raw["url"], "fetched_at": fetched_at}],
    }


class CardStore:
    def __init__(self, cards: list[dict[str, Any]] | None = None) -> None:
        self.cards: dict[str, dict[str, Any]] = {c["id"]: c for c in cards or []}
        self.by_name = {norm_name(c["name"]): c["id"] for c in self.cards.values() if norm_name(c["name"])}

    def upsert(self, card: dict[str, Any]) -> str:
        """Returns 'added' | 'updated' | 'unchanged' | 'merged'."""
        cur = self.cards.get(card["id"])
        if cur is not None:
            if cur["content_hash"] == card["content_hash"]:
                return "unchanged"
            cur.update({k: card[k] for k in ("text", "summary", "content_hash", "fetched_at")})
            return "updated"
        nn = norm_name(card["name"])
        twin = self.by_name.get(nn) if len(nn) >= 4 else None
        if twin is not None:
            t = self.cards[twin]
            if not any(s["url"] == card["url"] for s in t["sources"]):
                t["sources"].append(card["sources"][0])
                t["text"] = t["text"] + "\n" + card["text"]
                t["content_hash"] = hashlib.sha1(t["text"].encode()).hexdigest()
                return "merged"
            return "unchanged"
        self.cards[card["id"]] = card
        if nn:
            self.by_name[nn] = card["id"]
        return "added"


def ingest(raw_items: list[dict[str, Any]], store: CardStore, fetched_at: str | None = None) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now(UTC).isoformat()
    counts: Counter[str] = Counter()
    per_source: Counter[str] = Counter()
    for raw in raw_items:
        if not raw.get("url") or raw.get("source") not in SOURCE_MAP:
            counts["dropped_invalid"] += 1
            continue
        res = store.upsert(normalise(raw, fetched_at))
        counts[res] += 1
        if res == "added":
            per_source[SOURCE_MAP[raw["source"]]] += 1
    return {
        "added": counts["added"],
        "updated": counts["updated"],
        "dropped": counts["unchanged"] + counts["merged"],
        "merged": counts["merged"],
        "invalid": counts["dropped_invalid"],
        "added_per_source": dict(per_source),
        "total_cards": len(store.cards),
    }


def load_jsonl(p: Path) -> list[dict[str, Any]]:
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        return [json.loads(line) for line in f if line.strip()]


def write_snapshot(store: CardStore, p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for c in sorted(store.cards.values(), key=lambda c: c["id"]):
            f.write(json.dumps(c, sort_keys=True) + "\n")


def count_table(store: CardStore) -> str:
    c = Counter(card["source"] for card in store.cards.values())
    plat = Counter(len({s["platform"] for s in card["sources"]}) for card in store.cards.values())
    rows = ["| Source | Cards |", "|---|---|"] + [f"| {s} | {n} |" for s, n in sorted(c.items())]
    rows += [
        f"| **total** | **{sum(c.values())}** |",
        "",
        f"Cards seen on 2+ platforms: {sum(v for k, v in plat.items() if k >= 2)}",
    ]
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="/data/raw")
    ap.add_argument("--snapshot", default="/data/snapshot/cards.jsonl.gz")
    ap.add_argument("--from-snapshot", action="store_true", help="only (re)load the snapshot, no raw items")
    a = ap.parse_args()
    snap = Path(a.snapshot)
    store = CardStore(load_jsonl(snap) if snap.exists() else [])
    raw: list[dict[str, Any]] = []
    if not a.from_snapshot:
        for f in sorted(Path(a.raw_dir).glob("*.jsonl")):
            if f.name != "cursors.json":
                raw += load_jsonl(f)
    rep = ingest(raw, store)
    write_snapshot(store, snap)
    rep["finished_at"] = datetime.now(UTC).isoformat()
    print(json.dumps(rep))
    print(count_table(store), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
