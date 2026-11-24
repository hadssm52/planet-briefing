import json
from types import SimpleNamespace

from pipeline import summarise
from pipeline.config import load_config

CFG = load_config()
REGIONS = [r["name"] for r in CFG["regions"]]
TOPICS = [t["name"] for t in CFG["topics"]]


def story(n, title="Leaders agree climate deal at Brazil summit", desc="Negotiators from 190 countries reached agreement late on Friday night."):
    return {"id": n, "title": title, "description": desc, "published": None,
            "sources": [{"name": "BBC", "link": f"https://bbc.example/{n}", "title": title}]}


def test_copied_bullet_is_rejected():
    s = story(1)
    result = {"region": "Latin America", "topic": "Environment", "headline": "Climate deal reached",
              "significance": 8,
              "bullets": ["Negotiators from 190 countries reached agreement late on Friday night.",
                          "Delegates from about 190 nations settled the terms on Friday."]}
    out = summarise.apply_result(s, result, REGIONS, TOPICS)
    assert out["bullets"] == ["Delegates from about 190 nations settled the terms on Friday."]


def test_unknown_region_falls_back_and_significance_is_clamped():
    out = summarise.apply_result(story(1), {"region": "Mars", "topic": "Science & Technology", "headline": "X",
                                            "bullets": ["A fact."], "significance": 42}, REGIONS, TOPICS)
    assert out["region"] == "Global"
    assert out["significance"] == 10


class FakeClient:
    """Stands in for anthropic.Anthropic() so tests never call the API."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        prompt = kwargs["messages"][0]["content"]
        if "top_ids" in json.dumps(kwargs["output_config"]):
            payload = {"top_ids": [2, 1]}
        else:
            ids = [json.loads(line)["id"] for line in prompt.splitlines() if line.startswith("{")]
            payload = {"stories": [{"id": i, "region": "Europe", "topic": "Politics", "headline": f"Story {i}",
                                    "bullets": ["First fact.", "Second fact."], "significance": 5}
                                   for i in ids]}
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )


def test_summarise_batches_and_tracks_cost():
    cfg = dict(CFG, claude=dict(CFG["claude"], batch_size=2))
    stories = [story(n, title=f"Headline {n}") for n in range(1, 6)]
    client = FakeClient()
    results, top, usage = summarise.summarise(stories, cfg, client=client)
    assert len(results) == 5
    assert client.calls == 4  # 3 batches + 1 top-stories request
    assert top[:2] == [2, 1] and len(top) == 5
    assert usage.input_tokens == 4000 and usage.output_tokens == 800
    assert abs(usage.cost() - (4000 * 0.10 + 800 * 0.50) / 1e6) < 1e-12


def test_system_prompt_includes_topic_guide():
    prompt = summarise.system_prompt(CFG)
    for t in CFG["topics"]:
        assert t["name"] in prompt
    assert "Environment: climate" in prompt


def test_bad_api_key_stops_immediately():
    class AuthError(Exception):
        status_code = 401

    class BadKeyClient(FakeClient):
        def create(self, **kwargs):
            self.calls += 1
            raise AuthError("invalid x-api-key")

    client = BadKeyClient()
    stories = [story(n, title=f"Headline {n}") for n in range(1, 30)]
    try:
        summarise.summarise(stories, CFG, client=client)
    except summarise.FatalAPIError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
    else:
        raise AssertionError("expected FatalAPIError")
    assert client.calls == 1  # no pointless retries


def test_earlier_summaries_are_reused_and_only_new_stories_sent():
    old = story(1, title="Headline 1")
    previous = {"date": "2026-11-24", "top_ids": [1], "stories": [
        {**old, "headline": "Old summary", "bullets": ["Done earlier."], "region": "Europe",
         "topic": "Politics", "significance": 7}]}
    stories = [story(1, title="Headline 1"), story(2, title="Headline 2")]
    client = FakeClient()
    results, top, usage = summarise.summarise(stories, CFG, client=client, previous=previous)
    by_id = {r["id"]: r for r in results}
    assert by_id[1]["bullets"] == ["Done earlier."]      # reused, not re-sent
    assert by_id[2]["headline"] == "Story 2"              # newly summarised
    assert client.calls == 2                              # 1 batch (story 2 only) + top stories


def test_no_new_stories_means_no_api_calls():
    many = [story(n, title=f"H{n}") for n in range(1, 7)]
    previous = {"date": "2026-11-24", "top_ids": [1, 2, 3, 4, 5, 6], "stories": [
        {**s, "headline": "Old", "bullets": ["Done."], "region": "Europe", "topic": "Politics",
         "significance": 5} for s in many]}
    client = FakeClient()
    results, top, usage = summarise.summarise(many, CFG, client=client, previous=previous)
    assert client.calls == 0
    assert top == [1, 2, 3, 4, 5, 6]
