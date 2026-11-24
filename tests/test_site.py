from datetime import date

from pipeline import archive, site
from pipeline.config import load_config

CFG = load_config()


def make_digest(day="2026-11-24"):
    stories = [
        {"id": 1, "headline": "Climate deal reached in Brazil", "bullets": ["Nearly 190 nations agreed.", "Talks ran late."],
         "region": "Latin America", "topic": "Environment", "significance": 9, "published": None,
         "sources": [{"name": "BBC", "link": "https://bbc.example/deal"}, {"name": "DW", "link": "https://dw.example/deal"}]},
        {"id": 2, "headline": "Rates <held> steady", "bullets": ["The bank kept rates at 4%."],
         "region": "Europe", "topic": "Economics", "significance": 6, "published": None,
         "sources": [{"name": "Euronews", "link": "https://euronews.example/rates"}]},
        {"id": 3, "headline": "Cup final won", "bullets": ["The home side won 2-1."],
         "region": "Africa", "topic": "Sport", "significance": 3, "published": None,
         "sources": [{"name": "Africanews", "link": "https://africanews.example/cup"}]},
    ]
    return archive.make_digest(date.fromisoformat(day), f"{day}T06:04:00+00:00", stories, [1, 2, 3],
                               {"feeds_ok": 40})


def test_build_site_writes_all_pages(tmp_path):
    digests = [make_digest("2026-11-24"), make_digest("2026-11-23")]
    site.build_site(digests, CFG, tmp_path)

    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "style.css").exists()
    for r in CFG["regions"]:
        assert (tmp_path / "region" / r["slug"] / "index.html").exists()
    for t in CFG["topics"]:
        assert (tmp_path / "topic" / t["slug"] / "index.html").exists()
    assert (tmp_path / "archive" / "index.html").exists()
    assert (tmp_path / "archive" / "2026-11-23" / "index.html").exists()


def test_pages_link_sources_and_show_last_updated(tmp_path):
    site.build_site([make_digest()], CFG, tmp_path)
    home = (tmp_path / "index.html").read_text()
    assert "Top stories today" in home
    assert 'href="https://bbc.example/deal"' in home and 'href="https://dw.example/deal"' in home
    assert "Rates &lt;held&gt; steady" in home  # text is HTML-escaped
    for page in tmp_path.rglob("*.html"):
        assert "Last updated: 24 November 2026, 06:04 UTC" in page.read_text(), page


def test_region_page_only_has_its_stories_and_relative_links(tmp_path):
    site.build_site([make_digest()], CFG, tmp_path)
    europe = (tmp_path / "region" / "europe" / "index.html").read_text()
    assert "Rates &lt;held&gt; steady" in europe
    assert "Climate deal" not in europe
    assert 'href="../../style.css"' in europe


def test_archive_prune(tmp_path):
    for day in ["2026-08-01", "2026-11-20", "2026-11-24"]:
        archive.save_digest(tmp_path, make_digest(day))
    removed = archive.prune(tmp_path, date(2026, 11, 24), keep_days=90)
    assert removed == ["2026-08-01.json"]
    assert [d["date"] for d in archive.load_digests(tmp_path, date(2026, 11, 24), 90)] == ["2026-11-24", "2026-11-20"]


def test_homepage_splits_each_region_into_topic_subheadings(tmp_path):
    site.build_site([make_digest()], CFG, tmp_path)
    home = (tmp_path / "index.html").read_text()
    # Each region with stories gets its own section, with a subheading per topic.
    assert 'id="latin-america"' in home and 'id="latin-america-environment"' in home
    assert 'id="europe-economics"' in home
    assert 'id="africa-sport"' in home
    assert 'id="europe-sport"' not in home  # empty topics are left out
    # Headlines link to the full story on the region page.
    assert 'href="region/europe/index.html#s2"' in home
    # The archive day page uses the same region → topic layout.
    day = (tmp_path / "archive" / "2026-11-24" / "index.html").read_text()
    assert 'id="latin-america-environment"' in day
