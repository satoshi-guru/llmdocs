#!/usr/bin/env python3
"""Merge one library's LOOKUP lines into the global grep tier.

The global lookup table lives at $LLMDOCS_HOME/docs/LOOKUP.md (default
~/.llmdocs/docs/LOOKUP.md) — one `lib | signature | note` line per API, shared by
every repo. `doc-indexer` emits a fresh block of lines for a library; this script
does the mechanical append: drop that library's existing lines, add the new ones,
keep the file sorted by library name. The store stays append-only — other
libraries' lines are never touched.

Usage:
  python -m scripts.lookup_merge <lib> < newlines.txt
  printf '%s\\n' 'fastapi | FastAPI(title, lifespan) | create app' | python -m scripts.lookup_merge fastapi
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

STORE = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs")) / "docs"
LOOKUP = STORE / "LOOKUP.md"


def _lib_of(line: str) -> str:
    """Library name = text before the first '|', stripped."""
    return line.split("|", 1)[0].strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m scripts.lookup_merge <lib>  (new lines on stdin)", file=sys.stderr)
        return 2
    lib = sys.argv[1].strip()

    new = [ln.rstrip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    existing = []
    if LOOKUP.exists():
        existing = [ln.rstrip() for ln in LOOKUP.read_text(encoding="utf-8").splitlines() if ln.strip()]

    # Keep every other library's lines; replace this lib's block with the new one.
    kept = [ln for ln in existing if _lib_of(ln) != lib]
    merged = sorted(kept + new, key=lambda ln: (_lib_of(ln).lower(), ln))

    STORE.mkdir(parents=True, exist_ok=True)
    LOOKUP.write_text("\n".join(merged) + "\n", encoding="utf-8")
    print(f"LOOKUP.md: {len(new)} lines for '{lib}' merged ({len(merged)} total across "
          f"{len({_lib_of(ln) for ln in merged})} libraries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
