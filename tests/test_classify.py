from pipeline import classify
from pipeline.config import load_config

CFG = load_config()
REGIONS = {r["slug"]: r["name"] for r in CFG["regions"]}
TOPICS = {t["slug"]: t["name"] for t in CFG["topics"]}


def story(title, desc="", region_hint=None, topic_hint=None, n_sources=1, sid=1):
    return {"id": sid, "title": title, "description": desc, "published": None,
            "region_hint": region_hint, "topic_hint": topic_hint,
            "sources": [{"name": f"Outlet {i}", "link": f"https://o{i}.example/x", "title": title}
                        for i in range(n_sources)]}


def test_regions_from_keywords():
    assert classify.classify_region(story("Kenya election results announced"), REGIONS) == "Africa"
    assert classify.classify_region(story("Typhoon nears Philippines coast"), REGIONS) == "Asia-Pacific"
    assert classify.classify_region(story("Israeli strikes kill Hamas chief in Gaza"), REGIONS) == "Middle East"
    assert classify.classify_region(story("Car bomb destroys buildings in Colombian city"), REGIONS) == "Latin America"
    assert classify.classify_region(story("US Senate passes budget bill"), REGIONS) == "North America"
    assert classify.classify_region(story("Floods hit northern Italy"), REGIONS) == "Europe"


def test_latin_america_is_not_north_america():
    assert classify.classify_region(story("Latin America braces for storm season"), REGIONS) == "Latin America"


def test_lowercase_us_is_not_the_united_states():
    s = story("Join us for the festival", region_hint="Europe")
    assert classify.classify_region(s, REGIONS) == "Europe"


def test_region_falls_back_to_feed_hint_then_global():
    assert classify.classify_region(story("Mayor resigns", region_hint="Africa"), REGIONS) == "Africa"
    assert classify.classify_region(story("Mayor resigns"), REGIONS) == "Global"


def test_topics_from_keywords_and_hints():
    assert classify.classify_topic(story("Senegal reinstated as Afcon winners"), TOPICS) == "Sport"
    assert classify.classify_topic(story("Missile strike hits port"), TOPICS) == "Conflict"
    assert classify.classify_topic(story("Wildfires spread after record heatwave"), TOPICS) == "Environment"
    assert classify.classify_topic(story("Nvidia unveils new AI chip"), TOPICS) == "Science & Technology"
    assert classify.classify_topic(story("Central bank holds interest rates"), TOPICS) == "Economics"
    assert classify.classify_topic(story("Parliament votes on new law"), TOPICS) == "Politics"
    assert classify.classify_topic(story("Something happened", topic_hint="Culture"), TOPICS) == "Culture"


def test_excerpt_keeps_two_sentences():
    text = "First sentence here. Second one follows. Third is dropped."
    assert classify.excerpt(text) == "First sentence here. Second one follows."
    assert classify.excerpt("") == ""


def test_free_summarise_top_stories_spread_regions():
    stories = [story(f"Gaza ceasefire talks round {i}", n_sources=5, sid=i) for i in range(1, 6)]
    stories += [story("Kenya election results announced", "Votes counted.", n_sources=2, sid=6)]
    results, top, usage = classify.free_summarise(stories, CFG)
    assert usage.cost() == 0
    assert top.count(6) == 1
    middle_east = [i for i in top if i <= 5]
    assert len(middle_east) == 3  # at most 3 per region
    kenya = next(r for r in results if r["id"] == 6)
    assert kenya["excerpt"] == {"text": "Votes counted.", "source": "Outlet 0"}
    assert kenya["bullets"] == []
