from datetime import datetime, timezone
from pathlib import Path

from pipeline import collect
from pipeline.config import load_feeds

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"
FEED = {"name": "Sample News", "url": "https://example.com/rss"}
NOW = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)


def item(title, source, link=None, published="2026-11-24T01:00:00+00:00", feed_url=None):
    return {
        "title": title,
        "description": "",
        "link": link or f"https://{source.lower().replace(' ', '')}.example/{abs(hash(title))}",
        "source": source,
        "feed_url": feed_url or f"https://{source}.example/rss",
        "published": published,
    }


# ---- feed parsing

def test_parse_feed_reads_items_and_strips_html():
    items = collect.parse_feed(FIXTURE.read_bytes(), FEED)
    titles = [i["title"] for i in items]
    assert "Leaders agree climate deal at summit in Brazil" in titles
    assert "Item with no link is skipped" not in titles
    deal = items[0]
    assert deal["description"] == "Negotiators from 190 countries reached agreement late on Friday."
    assert deal["source"] == "Sample News"
    assert deal["published"] == "2026-11-23T22:00:00+00:00"


def test_filter_recent_drops_old_items():
    items = collect.parse_feed(FIXTURE.read_bytes(), FEED)
    recent = collect.filter_recent(items, max_age_hours=30, now=NOW)
    assert [i["title"] for i in recent] == [
        "Leaders agree climate deal at summit in Brazil",
        "Central bank holds interest rates steady",
    ]


def test_broken_feed_is_skipped(monkeypatch):
    def fake_fetch(feed, timeout=20):
        if feed["name"] == "Broken":
            raise ConnectionError("timed out")
        return collect.parse_feed(FIXTURE.read_bytes(), feed)

    monkeypatch.setattr(collect, "fetch_feed", fake_fetch)
    items, failures = collect.fetch_all([FEED, {"name": "Broken", "url": "https://broken.example"}])
    assert len(items) == 3
    assert len(failures) == 1 and "Broken" in failures[0]


def test_feeds_yaml_loads_and_skips_disabled():
    feeds = load_feeds()
    assert len(feeds) > 20
    assert all(f["url"].startswith("https://") for f in feeds)
    assert "NHK World" not in [f["name"] for f in feeds]  # disabled in feeds.yaml


# ---- deduplication

def test_same_story_from_different_outlets_is_merged():
    items = [
        item("Leaders agree climate deal at Brazil summit", "BBC"),
        item("Climate deal agreed by leaders at summit in Brazil", "DW"),
        item("Central bank holds interest rates steady", "BBC"),
    ]
    stories = collect.dedupe(items)
    assert len(stories) == 2
    deal = next(s for s in stories if "climate" in s["title"].lower())
    assert sorted(s["name"] for s in deal["sources"]) == ["BBC", "DW"]


def test_unrelated_stories_with_one_shared_word_stay_separate():
    items = [
        item("Floods hit northern Italy after record rainfall", "Euronews"),
        item("Italy wins Davis Cup final in Malaga", "BBC Sport"),
    ]
    assert len(collect.dedupe(items)) == 2


def test_same_link_is_merged_and_outlet_listed_once():
    items = [
        item("Protests continue in capital", "BBC", link="https://bbc.example/a"),
        item("Protests continue in capital city", "BBC", link="https://bbc.example/a"),
    ]
    stories = collect.dedupe(items)
    assert len(stories) == 1
    assert len(stories[0]["sources"]) == 1


def test_select_prefers_multi_source_and_mixes_feeds():
    items = [
        item("Leaders agree climate deal at Brazil summit", "BBC"),
        item("Climate deal agreed by leaders at summit in Brazil", "DW"),
    ]
    africa = ["Kenya election results announced", "Nigeria fuel prices rise", "Ghana cocoa harvest falls",
              "Senegal opens new port", "Egypt hosts trade forum"]
    asia = ["Seoul subway strike ends", "Typhoon nears Philippines coast", "Tokyo stocks close higher",
            "India launches weather satellite", "Vietnam signs chip agreement"]
    items += [item(t, "Africanews") for t in africa]
    items += [item(t, "Yonhap") for t in asia]
    chosen = collect.select_stories(collect.dedupe(items), limit=5)
    assert len(chosen) == 5
    assert len(chosen[0]["sources"]) == 2
    names = {c["sources"][0]["name"] for c in chosen[1:]}
    assert names == {"Africanews", "Yonhap"}
    assert [c["id"] for c in chosen] == [1, 2, 3, 4, 5]
    assert all("_tokens" not in c for c in chosen)


def test_feed_boilerplate_is_removed():
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
    <item><title>Port opens in Dakar</title><link>https://x.example/a</link>
    <description>The new port opened on Monday. The post Port opens in Dakar appeared first on Example News.</description></item>
    </channel></rss>"""
    items = collect.parse_feed(xml, FEED)
    assert items[0]["description"] == "The new port opened on Monday."
