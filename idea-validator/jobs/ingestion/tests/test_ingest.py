from src.ingest import CardStore, canonical_url, card_id, ingest, normalise

RAW = [
    {
        "source": "hn",
        "external_id": "1",
        "url": "https://www.ClubHub.io/?utm_source=hn",
        "title": "Show HN: ClubHub - events for societies",
        "text": "Manage RSVPs. Contact me at me@x.io",
        "published_at": "2026-01-01",
    },
    {
        "source": "github",
        "external_id": "2",
        "url": "https://github.com/x/clubhub",
        "title": "ClubHub",
        "text": "Open source club event manager by @someone",
        "published_at": "2026-02-01",
    },
    {"source": "producthunt", "external_id": "3", "url": "https://rsvply.com", "title": "RSVPly", "text": "RSVP pages"},
]


def test_canonical_url_strips_tracking_and_slash():
    assert canonical_url("https://www.ClubHub.io/?utm_source=hn") == canonical_url("https://clubhub.io")
    assert card_id("https://clubhub.io/") == card_id("http://www.clubhub.io")


def test_idempotent_second_run_adds_nothing():
    store = CardStore()
    first = ingest(RAW, store, "2026-11-01T00:00:00+00:00")
    second = ingest(RAW, store, "2026-11-01T00:00:00+00:00")
    assert first["added"] == 2 and second["added"] == 0 and second["total_cards"] == first["total_cards"]


def test_near_duplicate_merge_adds_platform():
    store = CardStore()
    rep = ingest(RAW, store)
    assert rep["merged"] == 1
    hub = store.cards[card_id(RAW[0]["url"])]
    assert {s["platform"] for s in hub["sources"]} == {"hackernews", "github"}


def test_empty_input():
    rep = ingest([], CardStore())
    assert rep["added"] == 0 and rep["total_cards"] == 0


def test_pii_stripped():
    c = normalise(RAW[1], "t")
    assert "@someone" not in c["text"]
    assert "me@x.io" not in normalise(RAW[0], "t")["text"]
