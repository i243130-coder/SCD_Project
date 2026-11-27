import json

import httpx
import pytest
import respx

from src import main
from src.sources.base import SourceDown
from src.sources.hn import HackerNews

TOOLS = "http://tools.test"


async def no_sleep(_):
    return None


def fetch_ok(content):
    return httpx.Response(
        200, json={"status": 200, "content": json.dumps(content), "injection_flags": [], "from_cache": False}
    )


@pytest.fixture(autouse=True)
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RAW_DIR", tmp_path)
    monkeypatch.setattr(main, "CURSORS", tmp_path / "cursors.json")


def hn():
    return HackerNews(client=httpx.AsyncClient(), tools_url=TOOLS, sleep=no_sleep)


@respx.mock
async def test_empty_source_no_crash():
    respx.post(f"{TOOLS}/fetch").mock(return_value=fetch_ok({"hits": [], "nbPages": 0}))
    rep = await main.run_sources(["hn"], factory=lambda n: hn())
    assert rep["hn"] == {"status": "ok", "items": 0, "file": rep["hn"]["file"]}


@respx.mock
async def test_429_backoff_then_success():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"status": 429, "content": "", "injection_flags": [], "from_cache": False})
        return fetch_ok({"hits": [{"objectID": "1", "title": "Show HN: X", "created_at_i": 1760000000}], "nbPages": 1})

    respx.post(f"{TOOLS}/fetch").mock(side_effect=handler)
    items, cur = await hn().fetch_since(None, max_pages=1)
    assert len(calls) >= 2 and items[0].title == "Show HN: X" and cur == "1760000000"


@respx.mock
async def test_source_down_others_succeed():
    def handler(req):
        url = json.loads(req.content)["url"]
        if "algolia" in url:
            return httpx.Response(502)
        return fetch_ok(
            {
                "items": [
                    {
                        "id": 7,
                        "html_url": "https://github.com/a/b",
                        "name": "b",
                        "description": "d",
                        "created_at": "2026-01-02T00:00:00Z",
                    }
                ]
            }
        )

    respx.post(f"{TOOLS}/fetch").mock(side_effect=handler)
    from src.sources.github import GitHub

    fac = {"hn": hn, "github": lambda: GitHub(client=httpx.AsyncClient(), tools_url=TOOLS, sleep=no_sleep)}
    rep = await main.run_sources(["hn", "github"], factory=lambda n: fac[n]())
    assert rep["hn"]["status"] == "degraded" and rep["github"] == {**rep["github"], "status": "ok", "items": 1}


@respx.mock
async def test_circuit_breaker_marks_degraded():
    respx.post(f"{TOOLS}/fetch").mock(return_value=httpx.Response(200, json={"status": 404, "content": ""}))
    s = hn()
    for _ in range(3):
        with pytest.raises(SourceDown):
            await s.fetch("https://hn.algolia.com/x")
    assert s.degraded
