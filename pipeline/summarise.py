"""Classifying and summarising stories with Claude, in batches.

The API key is read by the Anthropic SDK from the ANTHROPIC_API_KEY
environment variable. It is never stored in this project.
"""
from __future__ import annotations

import json
import re
from typing import Optional

SYSTEM_PROMPT = """You are the editor of Planet Briefing, a neutral daily digest of world news.

For each story you receive (a headline and a short description from one or more outlets), return:
- region: where the story mainly takes place. Use "Global" only when it genuinely spans several regions (e.g. a worldwide summit or a global market move).
- topic: the single best-fitting topic.
- headline: a short, neutral headline (max 12 words) in your own words.
- bullets: 2 to 4 short bullet points (max 25 words each) stating the key facts.
- significance: 1-10, how important the story is to a general international reader (10 = major world event, 1 = minor or local interest).

Rules for the writing:
- Write everything in your own words. Never copy a phrase of more than five words from the input.
- Be neutral and factual. No opinions, adjectives of judgement, or speculation.
- Use only facts present in the input. If the input is thin, write 2 short bullets rather than inventing detail.
- Attribute disputed claims ("X said...", "according to Y...").
- Plain English, no markdown in the text."""

TOP_PROMPT = """Below are today's story headlines, each with an id and the number of outlets covering it.
Pick the 10 most significant stories for a general international reader: those with the widest impact on people, politics, economies or security worldwide.
Prefer a spread across regions where importance is similar. Return their ids, most significant first."""


def system_prompt(cfg: dict) -> str:
    """The editor instructions plus a short guide to what each topic covers."""
    guide = "\n".join(
        f"- {t['name']}: {t['about']}" if t.get("about") else f"- {t['name']}" for t in cfg["topics"]
    )
    return f"{SYSTEM_PROMPT}\n\nTopics and what belongs in each:\n{guide}"


def story_schema(regions: list[str], topics: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "stories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "region": {"type": "string", "enum": regions},
                        "topic": {"type": "string", "enum": topics},
                        "headline": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "significance": {"type": "integer"},
                    },
                    "required": ["id", "region", "topic", "headline", "bullets", "significance"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["stories"],
        "additionalProperties": False,
    }


TOP_SCHEMA = {
    "type": "object",
    "properties": {"top_ids": {"type": "array", "items": {"type": "integer"}}},
    "required": ["top_ids"],
    "additionalProperties": False,
}


class Usage:
    """Running total of tokens used, for the cost report."""

    def __init__(self, input_price: float, output_price: float):
        self.input_price = input_price
        self.output_price = output_price
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0

    def add(self, usage) -> None:
        self.requests += 1
        self.input_tokens += usage.input_tokens + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.output_tokens += usage.output_tokens

    def cost(self) -> float:
        return cost_of(self.input_tokens, self.output_tokens, self.input_price, self.output_price)

    def report(self) -> str:
        return (
            f"{self.requests} requests, {self.input_tokens:,} input + {self.output_tokens:,} output tokens "
            f"≈ ${self.cost():.4f}"
        )


def cost_of(input_tokens: int, output_tokens: int, input_price: float, output_price: float) -> float:
    return input_tokens / 1e6 * input_price + output_tokens / 1e6 * output_price


def estimate_tokens(stories: list[dict], batch_size: int) -> tuple[int, int]:
    """Rough pre-run estimate (about 4 characters per token)."""
    batches = max(1, -(-len(stories) // batch_size))
    story_chars = sum(len(json.dumps(story_input(s))) for s in stories)
    input_tokens = story_chars // 4 + batches * (len(SYSTEM_PROMPT) // 4 + 500)
    input_tokens += len(stories) * 25 + 300  # the top-stories request
    output_tokens = len(stories) * 110 + 100
    return input_tokens, output_tokens


def story_input(story: dict) -> dict:
    return {
        "id": story["id"],
        "headline": story["title"],
        "description": story["description"],
        "outlets": [s["name"] for s in story["sources"]],
    }


# ---------------------------------------------------------------- checks


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def copies_source(bullet: str, source_texts: list[str], run: int = 8) -> bool:
    """True if the bullet repeats `run` or more consecutive words from a source."""
    words = _words(bullet)
    if len(words) < run:
        return False
    shingles = {" ".join(words[i : i + run]) for i in range(len(words) - run + 1)}
    for text in source_texts:
        sw = _words(text)
        for i in range(len(sw) - run + 1):
            if " ".join(sw[i : i + run]) in shingles:
                return True
    return False


def apply_result(story: dict, result: dict, regions: list[str], topics: list[str]) -> Optional[dict]:
    """Merge Claude's output into a story, rejecting copied or empty bullets."""
    sources_text = [story["title"], story["description"]] + [s["title"] for s in story["sources"]]
    bullets = []
    for b in result.get("bullets") or []:
        b = b.strip().lstrip("-•* ").strip()
        if b and not copies_source(b, sources_text):
            bullets.append(b)
    if not bullets:
        return None
    out = dict(story)
    out["region"] = result.get("region") if result.get("region") in regions else "Global"
    out["topic"] = result.get("topic") if result.get("topic") in topics else topics[0]
    out["headline"] = (result.get("headline") or story["title"]).strip()
    out["bullets"] = bullets[:4]
    out["significance"] = max(1, min(10, int(result.get("significance") or 1)))
    return out


# ---------------------------------------------------------------- API calls


class FatalAPIError(Exception):
    """The API rejected the key or account. Retrying won't help."""


def is_fatal(exc: Exception) -> bool:
    """Bad/missing key (401), no access (403), or no credit left."""
    return getattr(exc, "status_code", None) in (401, 403) or "credit balance" in str(exc).lower()


def _call_json(client, model: str, system: str, prompt: str, schema: dict, usage: Usage, max_tokens: int) -> dict:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )
    usage.add(response.usage)
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined this batch")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("response was cut off (max_tokens)")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def summarise_batch(client, model, system, batch, regions, topics, usage) -> list[dict]:
    """Summarise one batch. If it fails, retry as two smaller batches."""
    prompt = "Summarise these stories:\n\n" + "\n".join(
        json.dumps(story_input(s), ensure_ascii=False) for s in batch
    )
    try:
        data = _call_json(
            client, model, system, prompt, story_schema(regions, topics), usage,
            max_tokens=max(2000, 260 * len(batch)),
        )
    except Exception as exc:
        if is_fatal(exc):
            raise FatalAPIError(
                f"the Anthropic API refused the request ({exc}). Check that the ANTHROPIC_API_KEY "
                "secret holds a valid key and that your Anthropic account has credit."
            ) from exc
        if len(batch) <= 3:
            print(f"    ! dropped {len(batch)} stories: {exc}")
            return []
        print(f"    ! batch of {len(batch)} failed ({exc}); retrying in two halves")
        mid = len(batch) // 2
        return (summarise_batch(client, model, system, batch[:mid], regions, topics, usage)
                + summarise_batch(client, model, system, batch[mid:], regions, topics, usage))

    by_id = {s["id"]: s for s in batch}
    done = []
    for result in data.get("stories", []):
        story = by_id.pop(result.get("id"), None)
        if story is None:
            continue
        merged = apply_result(story, result, regions, topics)
        if merged:
            done.append(merged)
    return done


def pick_top(client, model, stories, usage, count: int = 10) -> list[int]:
    """Ask Claude for the most significant story ids. Falls back to scores."""
    fallback = [s["id"] for s in sorted(
        stories, key=lambda s: (s["significance"], len(s["sources"])), reverse=True)][:count]
    lines = [
        json.dumps({"id": s["id"], "headline": s["headline"], "region": s["region"], "outlets": len(s["sources"])},
                   ensure_ascii=False)
        for s in stories
    ]
    try:
        data = _call_json(client, model, TOP_PROMPT, "\n".join(lines), TOP_SCHEMA, usage, max_tokens=1000)
    except Exception as exc:
        print(f"    ! top-stories request failed ({exc}); using significance scores")
        return fallback
    valid = {s["id"] for s in stories}
    ids = []
    for i in data.get("top_ids", []):
        if i in valid and i not in ids:
            ids.append(i)
    for i in fallback:  # top up if the model returned fewer than `count`
        if len(ids) >= count:
            break
        if i not in ids:
            ids.append(i)
    return ids[:count]


def summarise(stories: list[dict], cfg: dict, client=None) -> tuple[list[dict], list[int], Usage]:
    """Summarise all stories. Returns (summarised stories, top story ids, usage)."""
    import anthropic

    ccfg = cfg["claude"]
    regions = [r["name"] for r in cfg["regions"]]
    topics = [t["name"] for t in cfg["topics"]]
    usage = Usage(ccfg["input_price_per_mtok"], ccfg["output_price_per_mtok"])
    client = client or anthropic.Anthropic(max_retries=4, timeout=180)

    system = system_prompt(cfg)
    size = ccfg["batch_size"]
    results: list[dict] = []
    for start in range(0, len(stories), size):
        batch = stories[start : start + size]
        print(f"  batch {start // size + 1}: {len(batch)} stories")
        results.extend(summarise_batch(client, ccfg["model"], system, batch, regions, topics, usage))

    top_ids = pick_top(client, ccfg["model"], results, usage) if results else []
    return results, top_ids, usage
