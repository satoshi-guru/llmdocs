#!/usr/bin/env python3
"""Regenerate the global doc-store manifest.

Scans the append-only store at $LLMDOCS_HOME/docs (default ~/.llmdocs/docs) and
writes MANIFEST.md next to it — a single index of every library we've ever
gathered, so the store stays trackable over time.

Usage:
  python scripts/manifest.py
  LLMDOCS_HOME=/some/where python scripts/manifest.py
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HOME = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs"))
STORE = HOME / "docs"
MANIFEST = HOME / "MANIFEST.md"

SKIP_FILES = {"COMPACT.md", "INDEX.md", "LOOKUP.md"}


def est_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Shared by bench/ and store_index.

    Deliberately dependency-free — good enough for relative token comparisons
    across compaction strategies and store dashboard reduction percentages.
    """
    return len(text) // 4


def _pages(lib: Path) -> int:
    return sum(1 for p in lib.rglob("*.md") if p.name not in SKIP_FILES)


def _du(path: Path) -> str:
    try:
        out = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True)
        return out.stdout.split("\t", 1)[0].strip() or "?"
    except Exception:
        return "?"


def main() -> int:
    if not STORE.is_dir():
        print(f"No store at {STORE} — nothing to index.")
        return 1

    libs = sorted(p for p in STORE.iterdir() if p.is_dir())
    total_pages = 0
    rows = []
    for lib in libs:
        pages = _pages(lib)
        total_pages += pages
        indexed = "✓" if (lib / "COMPACT.md").exists() else ""
        rows.append((lib.name, pages, indexed))

    lines = [
        "# llmdocs — Global Doc Store Manifest",
        "",
        "Append-only knowledge store shared by **every** repo. "
        "Path: `~/.llmdocs/docs/` (also `~/.claude/docs/`).",
        "New fetches **add** to this store; nothing is ever replaced. "
        "Versions don't matter — we keep everything we've gathered.",
        "",
        f"**{len(libs)} libraries · {total_pages} markdown pages · {_du(STORE)}** · "
        "regenerate with `python -m scripts.manifest`",
        "",
        "| Library | Pages | Indexed |",
        "|---------|------:|:-------:|",
    ]
    lines += [f"| {name} | {pages} | {indexed} |" for name, pages, indexed in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST}  ({len(libs)} libraries, {total_pages} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
