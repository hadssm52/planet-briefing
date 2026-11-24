"""The whole daily pipeline: collect → dedupe → summarise → archive → build."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
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
    recent = collect.filter_recent(items, pcfg["max_age_hours"], now)
    stories = collect.dedupe(recent, pcfg["dedupe_threshold"])
    chosen = collect.select_stories(stories, pcfg["max_stories"])
    multi = sum(1 for s in chosen if len(s["sources"]) > 1)
    print(f"  {len(items)} items → {len(recent)} recent → {len(stories)} unique stories "
          f"→ {len(chosen)} selected ({multi} covered by 2+ outlets)")

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


def check_site(site_dir: Path, top_count: int) -> None:
    """Basic sanity checks before anything is published."""
    index = site_dir / "index.html"
    if not index.exists():
        raise PipelineError("site build produced no index.html")
    html = index.read_text(encoding="utf-8")
    if top_count == 0 or html.count('class="story"') < min(top_count, 3):
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
