"""Building the static website from the archived daily digests."""
from __future__ import annotations

import shutil
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT

TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["longdate"] = lambda iso: date.fromisoformat(iso).strftime("%A %-d %B %Y")
    env.filters["shortdate"] = lambda iso: date.fromisoformat(iso).strftime("%-d %b %Y")
    return env


def format_updated(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%-d %B %Y, %H:%M UTC")


def by_significance(stories: list[dict]) -> list[dict]:
    return sorted(stories, key=lambda s: (s["significance"], len(s["sources"])), reverse=True)


def group(stories: list[dict], key: str, order: list[str]) -> "OrderedDict[str, list[dict]]":
    groups: "OrderedDict[str, list[dict]]" = OrderedDict((name, []) for name in order)
    for s in by_significance(stories):
        groups.setdefault(s[key], []).append(s)
    return OrderedDict((k, v) for k, v in groups.items() if v)


def group_nested(stories: list[dict], region_order: list[str], topic_order: list[str]):
    """Region → topic → stories, in config order, skipping empty groups."""
    return OrderedDict(
        (region, group(items, "topic", topic_order))
        for region, items in group(stories, "region", region_order).items()
    )


def top_stories(digest: dict) -> list[dict]:
    by_id = {s["id"]: s for s in digest["stories"]}
    return [by_id[i] for i in digest["top_ids"] if i in by_id]


def build_site(digests: list[dict], cfg: dict, out_dir: Path) -> list[Path]:
    """Render every page into out_dir (replacing what was there).
    `digests` must be newest first; the first one is "today"."""
    if not digests:
        raise ValueError("no digests to build the site from")

    env = _env()
    latest = digests[0]
    regions, topics = cfg["regions"], cfg["topics"]
    region_names = [r["name"] for r in regions]
    topic_names = [t["name"] for t in topics]
    region_slug = {r["name"]: r["slug"] for r in regions}
    topic_slug = {t["name"]: t["slug"] for t in topics}

    region_counts = {r: 0 for r in region_names}
    topic_counts = {t: 0 for t in topic_names}
    for s in latest["stories"]:
        region_counts[s["region"]] = region_counts.get(s["region"], 0) + 1
        topic_counts[s["topic"]] = topic_counts.get(s["topic"], 0) + 1

    common = {
        "site": cfg["site"],
        "regions": regions,
        "topics": topics,
        "region_slug": region_slug,
        "topic_slug": topic_slug,
        "region_counts": region_counts,
        "topic_counts": topic_counts,
        "updated": format_updated(latest["generated_at"]),
        "today": latest["date"],
    }

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    shutil.copy(STATIC / "style.css", out_dir / "style.css")
    written: list[Path] = []

    def render(template: str, rel_path: str, **ctx) -> None:
        depth = rel_path.count("/")
        html = env.get_template(template).render(root="../" * depth, **common, **ctx)
        path = out_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        written.append(path)

    # Homepage
    render("index.html", "index.html", page="home", digest=latest, top=top_stories(latest),
           world=group_nested(latest["stories"], region_names, topic_names))

    # Region pages (stories grouped by topic)
    for r in regions:
        stories = [s for s in latest["stories"] if s["region"] == r["name"]]
        render("section.html", f"region/{r['slug']}/index.html", page="region:" + r["slug"],
               title=r["name"], kind="region", digest=latest, total=len(stories),
               groups=group(stories, "topic", topic_names))

    # Topic pages (stories grouped by region)
    for t in topics:
        stories = [s for s in latest["stories"] if s["topic"] == t["name"]]
        render("section.html", f"topic/{t['slug']}/index.html", page="topic:" + t["slug"],
               title=t["name"], kind="topic", digest=latest, total=len(stories),
               groups=group(stories, "region", region_names))

    # Archive index and one page per day
    render("archive.html", "archive/index.html", page="archive", digests=digests)
    for d in digests:
        render("day.html", f"archive/{d['date']}/index.html", page="archive", digest=d,
               top=top_stories(d), world=group_nested(d["stories"], region_names, topic_names))

    return written
