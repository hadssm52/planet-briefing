"""Fetching RSS feeds, cleaning items, and merging duplicate stories.

Only the headline, short description and link from each feed are used.
"""
from __future__ import annotations

import calendar
import html
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import requests

USER_AGENT = "PlanetBriefing/1.0 (+RSS news digest; reads public feeds only)"
DESCRIPTION_LIMIT = 400

STOPWORDS = set(
    """
    the a an and or but of to in on at for from by with as is are was were be been
    being it its this that these those after before over under into amid about
    against says said say new news live update updates latest how why what who when
    where will would could should can may might has have had not no than then more
    most up out off his her their our your you we they he she them us top day week
    year years first two three one video watch report reports mean means
    analysis explainer opinion explained could
    january february march april june july august september october november december
    """.split()
)

# Daily round-ups, newsletters and picture galleries aren't single stories.
ROUNDUP_RE = re.compile(
    r"news bulletin|newsletter|podcast|pix of the day|pictures of the|in pictures|photos of the"
    r"|morning briefing|evening briefing|today\s*[-–|:]\s*\w+ \d|what we know so far|quiz",
    re.IGNORECASE,
)
# Footers some feeds append to every description.
BOILERPLATE_RE = re.compile(
    r"\s*(The post .+? appeared first on .+?$|Continue reading\W*$|Read more\W*$|\[(…|\.\.\.)\]\s*$)",
    re.IGNORECASE,
)
PREFIX_RE = re.compile(r"^(live|watch|video|analysis|explainer|opinion|breaking)\s*[:|–-]\s*", re.IGNORECASE)


# ---------------------------------------------------------------- fetching


def fetch_feed(feed: dict, timeout: int = 20) -> list[dict]:
    """Download one feed and return its cleaned items. Raises on failure."""
    resp = requests.get(feed["url"], timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return parse_feed(resp.content, feed)


def parse_feed(content: bytes, feed: dict) -> list[dict]:
    """Turn raw RSS/Atom bytes into a list of item dicts."""
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"could not parse feed: {parsed.bozo_exception}")
    items = []
    for entry in parsed.entries:
        title = PREFIX_RE.sub("", clean_text(entry.get("title", "")))
        link = (entry.get("link") or "").strip()
        if not title or not link.startswith("http") or ROUNDUP_RE.search(title):
            continue
        description = clean_text(entry.get("summary") or entry.get("description") or "")
        description = BOILERPLATE_RE.sub("", description).strip()
        if description.lower() == title.lower():
            description = ""
        items.append(
            {
                "title": title,
                "description": truncate(description, DESCRIPTION_LIMIT),
                "link": link,
                "source": feed["name"],
                "feed_url": feed["url"],
                "region_hint": feed.get("region"),
                "topic_hint": feed.get("topic"),
                "published": entry_time(entry),
            }
        )
    return items


def fetch_all(feeds: list[dict], workers: int = 12) -> tuple[list[dict], list[str]]:
    """Fetch every feed in parallel. Failed feeds are skipped and reported."""
    items: list[dict] = []
    failures: list[str] = []

    def work(feed):
        try:
            return feed, fetch_feed(feed), None
        except Exception as exc:  # any failure just skips this feed
            return feed, [], exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for feed, feed_items, err in pool.map(work, feeds):
            if err is not None:
                failures.append(f"{feed['name']} ({feed['url']}): {err}")
                print(f"  ✗ {feed['name']:<26} skipped — {type(err).__name__}: {err}")
            else:
                print(f"  ✓ {feed['name']:<26} {len(feed_items):>3} items")
                items.extend(feed_items)
    return items, failures


# ---------------------------------------------------------------- cleaning


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    text = TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def entry_time(entry) -> Optional[str]:
    """Return the entry's publish time as an ISO string in UTC, if it has one."""
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            dt = datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
            return dt.isoformat(timespec="seconds")
    return None


def filter_recent(items: list[dict], max_age_hours: float, now: Optional[datetime] = None) -> list[dict]:
    """Drop items older than max_age_hours. Items without a date are kept."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    kept = []
    for item in items:
        if item["published"] is None or datetime.fromisoformat(item["published"]) >= cutoff:
            kept.append(item)
    return kept


# ---------------------------------------------------------------- dedupe


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower().replace("'s", ""))
    tokens = set()
    for w in words:
        if len(w) < 3 or w in STOPWORDS or re.fullmatch(r"(19|20)\d\d|\d+(st|nd|rd|th)", w):
            continue  # skip filler words, years and dates like "24th"
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]  # crude plural folding: "talks" ~ "talk"
        tokens.add(w)
    return tokens


def similar(a: set[str], b: set[str], threshold: float) -> bool:
    """Two headlines match when they share at least 3 key words and
    `threshold` of the shorter headline's key words."""
    if not a or not b:
        return False
    shared = len(a & b)
    return shared >= 3 and shared / min(len(a), len(b)) >= threshold


def dedupe(items: list[dict], threshold: float = 0.6) -> list[dict]:
    """Merge items that describe the same story. Returns story dicts with
    a combined `sources` list (one entry per outlet)."""
    # Newest first, so each story's main text comes from the freshest report.
    ordered = sorted(items, key=lambda i: i["published"] or "", reverse=True)
    stories: list[dict] = []
    by_link: dict[str, dict] = {}

    for item in ordered:
        tokens = title_tokens(item["title"])
        match = by_link.get(item["link"])
        if match is None:
            for story in stories:
                if any(similar(tokens, t, threshold) for t in story["_tokens"]):
                    match = story
                    break
        if match is None:
            match = {
                "title": item["title"],
                "description": item["description"],
                "published": item["published"],
                "region_hint": item.get("region_hint"),
                "topic_hint": item.get("topic_hint"),
                "sources": [],
                "_tokens": [],
                "_feeds": set(),
            }
            stories.append(match)
        elif not match["description"] and item["description"]:
            match["description"] = item["description"]
        for key in ("region_hint", "topic_hint"):
            match[key] = match.get(key) or item.get(key)

        by_link[item["link"]] = match
        match["_tokens"].append(tokens)
        match["_feeds"].add(item["feed_url"])
        if all(s["name"] != item["source"] for s in match["sources"]):
            match["sources"].append({"name": item["source"], "link": item["link"], "title": item["title"]})

    for n, story in enumerate(stories, start=1):
        story["id"] = n
    return stories


def select_stories(stories: list[dict], limit: int) -> list[dict]:
    """Pick up to `limit` stories: everything covered by 2+ outlets first,
    then the rest taken in turn from each feed so no region is crowded out."""
    multi = [s for s in stories if len(s["sources"]) >= 2]
    multi.sort(key=lambda s: (len(s["sources"]), s["published"] or ""), reverse=True)
    chosen = multi[:limit]

    queues: dict[str, list[dict]] = defaultdict(list)
    for s in stories:
        if len(s["sources"]) < 2:
            queues[sorted(s["_feeds"])[0]].append(s)
    queue_list = list(queues.values())
    while len(chosen) < limit and any(queue_list):
        for q in queue_list:
            if q and len(chosen) < limit:
                chosen.append(q.pop(0))

    result = []
    for n, s in enumerate(chosen, start=1):
        clean = {k: v for k, v in s.items() if not k.startswith("_")}
        clean["id"] = n
        result.append(clean)
    return result
