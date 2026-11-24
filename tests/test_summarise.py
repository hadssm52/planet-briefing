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
