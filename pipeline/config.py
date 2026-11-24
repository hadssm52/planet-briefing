"""Loading config.yaml and feeds.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path = ROOT / "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_feeds(path: Path = ROOT / "feeds.yaml") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    feeds = []
    for feed in data.get("feeds") or []:
        if not feed.get("url") or feed.get("enabled", True) is False:
            continue
        feeds.append({
            "name": feed.get("name") or feed["url"],
            "url": feed["url"],
            "region": feed.get("region"),  # optional hints used by free mode
            "topic": feed.get("topic"),
        })
    return feeds
