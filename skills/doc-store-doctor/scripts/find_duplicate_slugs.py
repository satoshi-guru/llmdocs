#!/usr/bin/env python3
"""Detect duplicate / redundant library slugs in the global llmdocs store.

The append-only store accumulates the same docs under different slug names over time —
a trailing-slash variant (`hyperliquid` vs `hyperliquid-docs`), a re-fetch under a new
name, or a tiny failed crawl left beside the real one (`anthropic` 4pg vs `anthropic-api`
232pg). None of the other store scripts catch this; this one does, read-only, so the
caller can decide what to archive.

Three signals, in priority order:
  1. SAME-SOURCE   — two slugs whose INDEX.md `Source:` URL normalises to the same thing.
                     Almost always a true duplicate (e.g. trailing-slash variants).
  2. NAME-PAIR     — `X` and `X-docs` (or `X-doc`): the `-docs` suffix convention collides
                     with the bare alias. Flagged even if sources differ slightly.
  3. STUB-BESIDE   — a very small slug (< STUB_MAX pages) whose name is a prefix of a much
                     larger sibling (`anthropic` ⊂ `anthropic-api`): usually an old partial
                     crawl superseded by the real fetch.

For each group it recommends KEEPING the member with the newest content (freshest fetch),
preferring the shorter / canonical name on ties, and ARCHIVING the rest. The caller does the
moving — this never touches disk.

Usage:
  python find_duplicate_slugs.py                 # human table
  python find_duplicate_slugs.py --json          # machine-readable groups
  LLMDOCS_HOME=/path python find_duplicate_slugs.py
"""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path

STORE = Path(os.environ.get("LLMDOCS_HOME", Path.home() / ".llmdocs")) / "docs"
RESERVED = {"INDEX.md", "COMPACT.md", "LOOKUP.md"}
STUB_MAX = 5          # a slug with <= this many pages is "tiny" (stub candidate)
STUB_RATIO = 4        # sibling must be this many times larger to call it a stub


def _norm_source(url: str) -> str:
    """Canonicalise an INDEX Source URL so trailing-slash / scheme / www variants collide."""
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def scan(store: Path) -> dict[str, dict]:
    """Return {slug: {pages, source, newest}} for every library dir with an INDEX.md."""
    libs: dict[str, dict] = {}
    if not store.is_dir():
        return libs
    for d in sorted(p for p in store.iterdir() if p.is_dir() and not p.name.startswith(".")):
        pages = [f for f in d.rglob("*.md") if f.name not in RESERVED]
        if not pages:
            continue
        source = ""
        idx = d / "INDEX.md"
        if idx.exists():
            # Capture the FULL source line, not just the first token — a source like
            # "llms.txt (platform.claude.com)" truncated to "llms.txt" would falsely
            # collide every llms.txt-derived slug.
            m = re.search(r"^Source:\s*(.+?)\s*$",
                          idx.read_text(encoding="utf-8", errors="replace"),
                          re.MULTILINE | re.IGNORECASE)
            if m:
                source = m.group(1)
        # "?" is the crawler's sentinel for an unrecorded origin (legacy fetches) — treat
        # it as unknown, never as a real source, so two unknown-origin slugs aren't paired.
        if source.strip() in ("", "?"):
            source = ""
        newest = max((f.stat().st_mtime for f in pages), default=0.0)
        libs[d.name] = {"pages": len(pages), "source": source, "newest": newest}
    return libs


def _pick_keep(members: list[str], libs: dict[str, dict]) -> str:
    """Keep the freshest fetch; break ties toward the shorter (canonical) slug name."""
    return sorted(members, key=lambda s: (-libs[s]["newest"], len(s), s))[0]


def find_groups(libs: dict[str, dict]) -> list[dict]:
    groups: list[dict] = []
    claimed: set[str] = set()

    def emit(members: list[str], reason: str):
        members = [m for m in members if m not in claimed]
        if len(members) < 2:
            return
        keep = _pick_keep(members, libs)
        for m in members:
            claimed.add(m)
        groups.append({
            "reason": reason,
            "keep": keep,
            "archive": [m for m in members if m != keep],
            "members": {m: libs[m] for m in members},
        })

    # 1. X / X-docs name pairs — the "-docs" suffix convention colliding with the bare
    #    alias is the single most reliable duplicate signal (hyperliquid/hyperliquid-docs).
    for slug in list(libs):
        for suffix in ("-docs", "-doc"):
            if slug.endswith(suffix) and slug[: -len(suffix)] in libs:
                emit([slug[: -len(suffix)], slug], "name-pair (-docs suffix)")

    # 2. same-source MIRROR PAIRS only. A single llms.txt is intentionally split into many
    #    slugs (anthropic-api-python/-go/...), so a shared source is NOT a duplicate by
    #    itself. Flag only when EXACTLY TWO slugs share a (non-empty) source AND have the
    #    identical page count — that is a true mirror, not an intentional split. Any source
    #    shared by 3+ slugs is a family and is left alone.
    by_source: dict[str, list[str]] = {}
    for slug, info in libs.items():
        if info["source"] and _norm_source(info["source"]):
            by_source.setdefault(_norm_source(info["source"]), []).append(slug)
    for members in by_source.values():
        if len(members) == 2 and libs[members[0]]["pages"] == libs[members[1]]["pages"]:
            emit(members, "same-source mirror (identical page count)")

    # 3. tiny stub beside a much larger prefix-sibling (anthropic 4pg ⊂ anthropic-api 232pg):
    #    an old partial crawl superseded by the real fetch. Guarded by STUB_MAX + STUB_RATIO
    #    so a small-but-legitimate doc next to a big sibling isn't swept up.
    for slug, info in libs.items():
        if slug in claimed or info["pages"] > STUB_MAX:
            continue
        for other, oinfo in sorted(libs.items(), key=lambda kv: -kv[1]["pages"]):
            if other == slug or other in claimed:
                continue
            if other.startswith(slug + "-") and oinfo["pages"] >= info["pages"] * STUB_RATIO:
                emit([slug, other], "stub-beside-full")
                break
    return groups


def _fmt_date(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"


def main() -> int:
    ap = argparse.ArgumentParser(description="find duplicate/redundant slugs in the llmdocs store")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--store", default=str(STORE), help=f"store dir (default {STORE})")
    args = ap.parse_args()

    libs = scan(Path(args.store))
    groups = find_groups(libs)

    if args.json:
        print(json.dumps({"store": args.store, "groups": groups}, indent=2))
        return 0

    if not groups:
        print(f"No duplicate slugs found in {args.store}  ({len(libs)} libraries scanned).")
        return 0

    print(f"Duplicate/redundant slugs in {args.store}:\n")
    for g in groups:
        print(f"  [{g['reason']}]  keep: {g['keep']}")
        for slug in g["members"]:
            info = g["members"][slug]
            tag = "KEEP   " if slug == g["keep"] else "archive"
            print(f"    {tag} {slug:<28} {info['pages']:>4} pages  "
                  f"fetched {_fmt_date(info['newest'])}  src={info['source'] or '-'}")
        print()
    n_arch = sum(len(g["archive"]) for g in groups)
    print(f"{len(groups)} group(s), {n_arch} slug(s) recommended for archiving "
          f"(move to .archive/ — reversible).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
