"""The whole daily pipeline: collect → dedupe → summarise → archive → build."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import archive, classify, collect, site, summarise
from .config import ROOT, load_config, load_feeds

ARCHIVE_DIR = ROOT / "data" / "archive"
SITE_DIR = ROOT / "_site"


class PipelineError(Exception):
    """A problem serious enough that nothing should be published."""


def run(dry_run: bool = False, rebuild_only: bool = False, now: Optional[datetime] = None) -> None:
    cfg = load_config()
    pcfg, ccfg = cfg["pipeline"], cfg["claude"]
    now = now or datetime.now(timezone.utc)
    today = now.date()

    if rebuild_only:
        digests = archive.load_digests(ARCHIVE_DIR, today, pcfg["archive_days"])
        if not digests:
            raise PipelineError("no saved days in data/archive to rebuild from")
        pages = site.build_site(digests, cfg, SITE_DIR)
        print(f"Rebuilt {len(pages)} pages into {SITE_DIR}")
        return

    mode = cfg.get("summariser", "auto")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_claude = not dry_run and (mode == "claude" or (mode == "auto" and has_key))
    if mode == "claude" and not dry_run and not has_key:
        raise PipelineError(
            "ANTHROPIC_API_KEY is not set. Set it (see README), use --dry-run, "
            'or set summariser: "auto" or "free" in config.yaml.'
        )

    # 1. Collect
    feeds = load_feeds()
    print(f"\n[1/5] Fetching {len(feeds)} feeds…")
    items, failures = collect.fetch_all(feeds)
    feeds_ok = len(feeds) - len(failures)
    if not items:
        raise PipelineError("every feed failed — not publishing")

    # 2. Dedupe and choose
    print("\n[2/5] Merging duplicate stories…")
    window = max(pcfg["max_age_hours"], pcfg.get("backfill_hours", 0))
    recent = collect.filter_recent(items, window, now)
    stories = classify.preclassify(collect.dedupe(recent, pcfg["dedupe_threshold"]), cfg)
    cells = continent_topic_cells(cfg)
    per_cell = pcfg.get("min_per_topic", 0)
    fresh_after = (now - timedelta(hours=pcfg["max_age_hours"])).isoformat(timespec="seconds")
    chosen = collect.select_stories(stories, pcfg["max_stories"], cells, per_cell, fresh_after)
    multi = sum(1 for s in chosen if len(s["sources"]) > 1)
    print(f"  {len(items)} items → {len(recent)} recent → {len(stories)} unique stories "
          f"→ {len(chosen)} selected ({multi} covered by 2+ outlets)")
    report_gaps(chosen, cells, per_cell, "pre_region", "pre_topic")

    # 3. Summarise (reusing anything an earlier run today already did)
    saved = archive.load_digests(ARCHIVE_DIR, today, pcfg["archive_days"])
    earlier_today = next((d for d in saved if d["date"] == today.isoformat()), None)
    results = None
    if use_claude:
        _, todo = summarise.reuse_previous(chosen, earlier_today)
        est_in, est_out = summarise.estimate_tokens(todo, ccfg["batch_size"])
        est_cost = summarise.cost_of(est_in, est_out, ccfg["input_price_per_mtok"], ccfg["output_price_per_mtok"])
        print(f"\n[3/5] Summarising with {ccfg['model']}"
              f" — estimate: ~{est_in:,} input + ~{est_out:,} output tokens ≈ ${est_cost:.4f}")
        try:
            results, top_ids, usage = summarise.summarise(chosen, cfg, previous=earlier_today)
            print(f"  actual usage: {usage.report()}")
        except summarise.FatalAPIError as exc:
            if mode == "claude":
                raise PipelineError(str(exc)) from exc
            print(f"  ! {exc}\n  ! Falling back to free mode for today.")
    if results is None:
        print("\n[3/5] Sorting stories (free mode: keyword rules and the outlets' own summaries, $0)")
        results, top_ids, usage = classify.free_summarise(chosen, cfg)
    if use_claude:
        report_gaps(results, cells, per_cell, "region", "topic")
    if len(results) < pcfg["min_stories"]:
        raise PipelineError(
            f"only {len(results)} stories summarised (minimum is {pcfg['min_stories']}) — not publishing"
        )

    # 4. Build the site (today's digest + saved days)
    print("\n[4/5] Building the website…")
    stats = {
        "feeds_ok": feeds_ok,
        "feeds_failed": len(failures),
        "items": len(items),
        "stories": len(results),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost(), 5),
    }
    digest = archive.make_digest(today, now.isoformat(timespec="seconds"), results, top_ids, stats)
    older = [d for d in saved if d["date"] != digest["date"]]
    pages = site.build_site([digest] + older, cfg, SITE_DIR)
    check_site(SITE_DIR, len(top_ids))
    print(f"  {len(pages)} pages written to {SITE_DIR.relative_to(ROOT)}/")

    # 5. Save today to the archive (only once the site built cleanly)
    print("\n[5/5] Updating the archive…")
    if dry_run:
        print("  (dry run: today's digest is not saved)")
    else:
        path = archive.save_digest(ARCHIVE_DIR, digest)
        print(f"  saved {path.relative_to(ROOT)}")
    removed = archive.prune(ARCHIVE_DIR, today, pcfg["archive_days"])
    if removed:
        print(f"  removed {len(removed)} day(s) older than {pcfg['archive_days']} days")

    print("\nDone.")
    print(f"  Stories: {len(results)} · Top stories: {len(top_ids)} · Feeds OK: {feeds_ok}/{len(feeds)}")
    if failures:
        print(f"  Skipped feeds ({len(failures)}):")
        for f in failures:
            print(f"    - {f}")
    print(f"  Cost this run: ${usage.cost():.4f}")


def continent_topic_cells(cfg: dict) -> list[tuple]:
    """Every (continent, topic) pair that should have stories. Global is excluded."""
    return [(r["name"], t["name"]) for r in cfg["regions"] if r["slug"] != "global" for t in cfg["topics"]]


def report_gaps(stories: list[dict], cells: list[tuple], per_cell: int, rkey: str, tkey: str) -> None:
    """Print any continent/topic with fewer than `per_cell` stories."""
    if not per_cell:
        return
    counts: dict[tuple, int] = {}
    for s in stories:
        key = (s.get(rkey), s.get(tkey))
        counts[key] = counts.get(key, 0) + 1
    gaps = [f"{r} / {t} ({counts.get((r, t), 0)})" for r, t in cells if counts.get((r, t), 0) < per_cell]
    if gaps:
        print(f"  ! fewer than {per_cell} stories (the feeds had no more): " + ", ".join(gaps))
    else:
        print(f"  every continent has at least {per_cell} stories in every topic")


def check_site(site_dir: Path, top_count: int) -> None:
    """Basic sanity checks before anything is published."""
    index = site_dir / "index.html"
    if not index.exists():
        raise PipelineError("site build produced no index.html")
    html = index.read_text(encoding="utf-8")
    # Top stories appear as full stories ("story") or compact cards ("card").
    shown = html.count('class="story') + html.count('class="card"')
    if top_count == 0 or shown < min(top_count, 3):
        raise PipelineError("homepage has no top stories — not publishing")


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Planet Briefing pipeline.")
    parser.add_argument("--dry-run", action="store_true",
                        help="use free mode and don't save today to the archive (no API key needed, costs nothing)")
    parser.add_argument("--rebuild", action="store_true",
                        help="only rebuild the website from saved days (no fetching, no API calls)")
    args = parser.parse_args(argv)
    try:
        run(dry_run=args.dry_run, rebuild_only=args.rebuild)
    except PipelineError as exc:
        print(f"\nRUN FAILED: {exc}", file=sys.stderr)
        return 1
    return 0
