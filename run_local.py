#!/usr/bin/env python3
"""Run the whole Planet Briefing pipeline on your own computer.

    python3 run_local.py --dry-run    # test for free, placeholder summaries
    python3 run_local.py              # real run (needs ANTHROPIC_API_KEY)
    python3 run_local.py --rebuild    # just rebuild pages from saved days

Then open _site/index.html in your browser.

Your API key can be in the environment, or in a file called `.env` in this
folder containing one line:  ANTHROPIC_API_KEY=sk-ant-...
(.env is listed in .gitignore, so it is never committed.)
"""
import os
import sys
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    from pipeline.main import main

    sys.exit(main())
