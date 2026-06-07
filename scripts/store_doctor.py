#!/usr/bin/env python3
"""Audit (and optionally repair) the global doc store for data-quality defects.

Scans the append-only store at $LLMDOCS_HOME/docs (default ~/.llmdocs/docs) and
flags, per slug:
  - asset files: binary assets (.pdf/.png/.zip/.woff/.css/.js/...) the old crawler
    decoded as text and saved as garbage `.md` (fixed going forward by the
    asset-skip in crawler.py; existing ones still pollute the store).
  - INDEX drift: link-rows in INDEX.md disagreeing with real files on disk
    (truncated -> orphaned pages invisible to docs-prime/LOOKUP; inflated -> phantom
    rows from anchor/trailing-slash dups).

Modes:
  --report           (default) read-only audit, prints a table + summary
  --prune-assets     delete the asset `.md` files (DESTRUCTIVE; prompts unless --yes)
  --check            exit non-zero if any defect is found (for CI)
  --yes              skip the confirmation prompt for --prune-assets

Usage:
  python scripts/store_doctor.py
  python scripts/store_doctor.py --check
  LLMDOCS_HOME=/some/where python scripts/store_doctor.py --prune-assets --yes

Repairing INDEX drift is intentionally NOT automated here: the correct fix is to
re-fetch the slug with the current (fixed) engine, which regenerates a truthful
INDEX. This tool only *reports* drift so you know which slugs to re-fetch.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HOME = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs"))
STORE = HOME / "docs"

# Mirror llmdocs._ASSET_EXT_RE (kept in sync intentionally) — a binary/non-document
# extension at the end of the output filename, before the engine's `.md` suffix.
ASSET_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|svg|ico|bmp|tiff?|pdf|zip|tar|gz|tgz|bz2|xz|rar|7z|"
    r"woff2?|ttf|eot|otf|mp4|mov|avi|webm|mkv|mp3|wav|ogg|flac|css|js|mjs|map|"
    r"dmg|exe|bin|wasm|apk|deb|rpm|msi|doc|docx|ppt|pptx|xls|xlsx)\.md$",
    re.IGNORECASE,
)
_GENERATED = {"INDEX.md", "COMPACT.md", "LOOKUP.md"}


def _page_files(slug_dir: Path) -> list[Path]:
    return [p for p in slug_dir.rglob("*.md") if p.name not in _GENERATED]


def _index_rows(slug_dir: Path) -> int:
    idx = slug_dir / "INDEX.md"
    if not idx.is_file():
        return -1
    return sum(1 for ln in idx.read_text(encoding="utf-8", errors="replace").splitlines()
               if ln.startswith("- ["))


def audit(store: Path) -> list[dict]:
    rows = []
    for slug_dir in sorted(p for p in store.iterdir() if p.is_dir()):
        pages = _page_files(slug_dir)
        assets = [p for p in pages if ASSET_RE.search(p.name)]
        idx_rows = _index_rows(slug_dir)
        clean = len(pages) - len(assets)
        drift = idx_rows >= 0 and idx_rows != len(pages)
        rows.append({
            "slug": slug_dir.name, "dir": slug_dir,
            "files": len(pages), "clean": clean,
            "assets": len(assets), "asset_paths": assets,
            "index_rows": idx_rows, "drift": drift,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prune-assets", action="store_true",
                    help="delete asset .md files (destructive)")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any defect found (CI)")
    ap.add_argument("--yes", action="store_true", help="skip prune confirmation")
    args = ap.parse_args()

    if not STORE.is_dir():
        print(f"no store at {STORE}", file=sys.stderr)
        return 2

    rows = audit(STORE)
    defect_rows = [r for r in rows if r["assets"] or r["drift"]]

    print(f"# store doctor — {STORE}  ({len(rows)} slugs)\n")
    print(f"{'slug':24} {'files':>6} {'clean':>6} {'assets':>6} {'index':>6}  drift")
    for r in sorted(defect_rows, key=lambda r: (-r["assets"], r["slug"])):
        print(f"{r['slug']:24} {r['files']:6} {r['clean']:6} {r['assets']:6} "
              f"{r['index_rows']:6}  {'DRIFT' if r['drift'] else ''}")
    total_assets = sum(r["assets"] for r in rows)
    drift_slugs = [r["slug"] for r in rows if r["drift"]]
    print(f"\nasset .md files: {total_assets} across "
          f"{sum(1 for r in rows if r['assets'])} slugs")
    print(f"INDEX-drift slugs: {len(drift_slugs)}  "
          f"(re-fetch with current engine to repair)")

    if args.prune_assets:
        victims = [p for r in rows for p in r["asset_paths"]]
        if not victims:
            print("\nno asset files to prune.")
        else:
            print(f"\nWILL DELETE {len(victims)} asset .md files.")
            if not args.yes:
                resp = input("proceed? [y/N] ").strip().lower()
                if resp != "y":
                    print("aborted.")
                    return 0
            for p in victims:
                p.unlink()
            print(f"deleted {len(victims)} files. "
                  f"Re-run scripts/store_index.py + manifest.py to refresh indexes.")

    if args.check:
        return 1 if defect_rows else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
