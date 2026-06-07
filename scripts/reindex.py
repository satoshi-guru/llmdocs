#!/usr/bin/env python3
"""Regenerate a library's INDEX.md from the doc pages already on disk (no network).

Repairs INDEX drift — when the INDEX link-rows disagree with the real *.md files:
  - truncated INDEX that orphans real pages (e.g. ruff: 978 files, 6 indexed),
  - inflated INDEX with anchor/dup rows (e.g. zod: 12 files, 199 rows),
  - dangling rows left after asset files were pruned.
The pages on disk are the source of truth; this rebuilds the INDEX to match them,
reading each page's frontmatter (title, url) and preserving the existing INDEX's
Source/Engine/Fetched header lines. Use after store_doctor --prune-assets, or any
time `store_doctor` reports drift, instead of a full re-fetch.

Usage:
  python scripts/reindex.py <slug> [<slug> ...]   # specific libraries
  python scripts/reindex.py --all                  # every library in the store
  LLMDOCS_HOME=/path python scripts/reindex.py --all
"""
from __future__ import annotations
import argparse, os, re, urllib.parse
from pathlib import Path

HOME = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs"))
STORE = HOME / "docs"
GENERATED = {"INDEX.md", "COMPACT.md", "LOOKUP.md"}


def _frontmatter(p: Path) -> tuple[str, str | None]:
    t = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^title:\s*"?(.*?)"?\s*$', t, re.M)
    title = m.group(1).strip() if m else ""
    m = re.search(r'^url:\s*(\S+)', t, re.M)
    url = m.group(1).strip() if m else None
    if not title:
        m = re.search(r'^#\s+(.+)', t, re.M)
        title = m.group(1).strip() if m else p.stem.replace("-", " ").title()
    return title, url


def reindex(slug_dir: Path) -> int:
    pages = sorted(p for p in slug_dir.rglob("*.md") if p.name not in GENERATED)
    entries = []
    for p in pages:
        title, url = _frontmatter(p)
        rel = str(p.relative_to(slug_dir))
        entries.append({"title": title, "url": url or rel, "file": rel})

    idx = slug_dir / "INDEX.md"
    src = name = eng = fetched = None
    if idx.exists():
        h = idx.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'Source:\s*(\S+)', h); src = m.group(1) if m else None
        m = re.search(r'^#\s+(.+?)\s+—', h, re.M); name = m.group(1).strip() if m else None
        m = re.search(r'Engine:\s*(\S+)', h); eng = m.group(1) if m else None
        m = re.search(r'Fetched:\s*(\S+)', h); fetched = m.group(1) if m else None
    name = name or slug_dir.name

    sections: dict[str, list[dict]] = {}
    for e in entries:
        parts = [x for x in urllib.parse.urlparse(e["url"]).path.split("/") if x]
        sec = parts[1] if len(parts) > 1 else (parts[0] if parts else "root")
        sections.setdefault(sec, []).append(e)

    prov = f"Engine: {eng}  \nFetched: {fetched}  \n" if eng else ""
    lines = [f"# {name} — LLM Index",
             f"\nSource: {src or '?'}  \nPages: {len(entries)}  \n{prov}\n---\n"]
    for sec, es in sorted(sections.items()):
        lines.append(f"\n## {sec.replace('-', ' ').replace('_', ' ').title()}\n")
        for e in es:
            lines.append(f"- [{e['title']}]({e['file']})")
    idx.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="library slugs to reindex")
    ap.add_argument("--all", action="store_true", help="reindex every library in the store")
    args = ap.parse_args()
    if not STORE.is_dir():
        print(f"no store at {STORE}"); return 2
    targets = ([d.name for d in sorted(STORE.iterdir()) if d.is_dir()]
               if args.all else args.slugs)
    if not targets:
        ap.error("give slug(s) or --all")
    for s in targets:
        d = STORE / s
        if not d.is_dir():
            print(f"skip {s} (absent)"); continue
        print(f"reindexed {s}: {reindex(d)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
