"""Daily digests saved as small JSON files in data/archive/ (one per day)."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def make_digest(day: date, generated_at: str, stories: list[dict], top_ids: list[int], stats: dict) -> dict:
    keep = ("id", "headline", "bullets", "why_it_matters", "excerpt", "image", "region", "topic", "significance", "published")
    return {
        "date": day.isoformat(),
        "generated_at": generated_at,
        "top_ids": top_ids,
        "stats": stats,
        "stories": [
            {**{k: s.get(k) for k in keep},
             "sources": [{"name": src["name"], "link": src["link"]} for src in s["sources"]]}
            for s in stories
        ],
    }


def save_digest(archive_dir: Path, digest: dict) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{digest['date']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=1)
    return path


def load_digests(archive_dir: Path, today: date, keep_days: int) -> list[dict]:
    """All saved digests within the retention window, newest first."""
    cutoff = today - timedelta(days=keep_days - 1)
    digests = []
    if archive_dir.exists():
        for path in archive_dir.iterdir():
            m = DATE_FILE.match(path.name)
            if m and date.fromisoformat(m.group(1)) >= cutoff:
                with open(path, encoding="utf-8") as f:
                    digests.append(json.load(f))
    digests.sort(key=lambda d: d["date"], reverse=True)
    return digests


def prune(archive_dir: Path, today: date, keep_days: int) -> list[str]:
    """Delete digests older than the retention window. Returns removed names."""
    cutoff = today - timedelta(days=keep_days - 1)
    removed = []
    if archive_dir.exists():
        for path in archive_dir.iterdir():
            m = DATE_FILE.match(path.name)
            if m and date.fromisoformat(m.group(1)) < cutoff:
                path.unlink()
                removed.append(path.name)
    return sorted(removed)
