#!/usr/bin/env python3
"""Measure what a doc lookup costs vs reading the whole doc — the llmdocs thesis, on demand.

For any library in the store and any query, reports the token cost of each tier of the ladder
(grep LOOKUP -> read COMPACT -> read the whole doc) and how many times cheaper the lookup is.
Token estimate = chars/4 (same as scripts/manifest.py).

Usage:
  python scripts/lookup_cost.py anthropic-api count_tokens
  python scripts/lookup_cost.py <lib> "<query>" --max-lines 3

Reusable as a module:
  from lookup_cost import tok, whole_doc_tokens, compact_tokens, grep_lookup
"""
from __future__ import annotations
import argparse, os, re, sys
from pathlib import Path

STORE = Path(os.environ.get("LLMDOCS_HOME", Path.home() / ".llmdocs")) / "docs"
SKIP = {"COMPACT.md", "INDEX.md", "LOOKUP.md"}


def tok(text: str) -> int:
    return max(1, len(text) // 4)


def lib_dir(lib: str) -> Path:
    return STORE / lib


def content_pages(lib: str) -> list[Path]:
    d = lib_dir(lib)
    return [p for p in d.rglob("*.md")
            if p.name not in SKIP
            and not any(part in ("_raw_html", "__pycache__") or part.startswith(".")
                        for part in p.relative_to(d).parts)]


def whole_doc_tokens(lib: str) -> tuple[int, int]:
    pages = content_pages(lib)
    return sum(tok(p.read_text(errors="replace")) for p in pages), len(pages)


def compact_tokens(lib: str) -> int | None:
    f = lib_dir(lib) / "COMPACT.md"
    return tok(f.read_text(errors="replace")) if f.exists() else None


def grep_lookup(lib: str, query: str, max_lines: int = 3):
    """(sample lines, total matches, tokens of sample, tier).

    Tier order: lib-local LOOKUP.md -> global LOOKUP.md (filtered to this lib) -> raw pages.
    """
    rx = re.compile(re.escape(query), re.I)
    lib_lookup = lib_dir(lib) / "LOOKUP.md"
    global_lookup = STORE / "LOOKUP.md"
    matches: list[str] = []
    tier = "raw grep"
    if lib_lookup.exists():
        matches = [ln for ln in lib_lookup.read_text(errors="replace").splitlines() if rx.search(ln)]
        if matches:
            tier = "LOOKUP.md"
    if not matches and global_lookup.exists():
        cand = [ln for ln in global_lookup.read_text(errors="replace").splitlines()
                if rx.search(ln) and lib in ln]
        if cand:
            matches, tier = cand, "global LOOKUP.md"
    if not matches:
        tier = "raw grep"
        for p in content_pages(lib):
            for ln in p.read_text(errors="replace").splitlines():
                if rx.search(ln):
                    matches.append(ln.strip())
    sample = matches[:max_lines]
    sample_tok = tok("\n".join(sample)) if sample else 1
    return sample, len(matches), sample_tok, tier


def main() -> int:
    ap = argparse.ArgumentParser(description="Cost of a lookup vs reading the whole doc.")
    ap.add_argument("lib")
    ap.add_argument("query")
    ap.add_argument("--max-lines", type=int, default=3)
    args = ap.parse_args()

    if not lib_dir(args.lib).is_dir():
        print(f"No such lib in store: {args.lib}", file=sys.stderr)
        return 1

    whole, pages = whole_doc_tokens(args.lib)
    comp = compact_tokens(args.lib)
    sample, n_match, look, tier = grep_lookup(args.lib, args.query, args.max_lines)

    print(f"lib: {args.lib}   query: {args.query!r}   ({pages} pages)\n")
    print(f"  {'read whole doc':<22} ~{whole:>12,} tok")
    print(f"  {'read COMPACT.md':<22} " + (f"~{comp:>12,} tok" if comp is not None
                                           else f"{'(not indexed)':>16}"))
    print(f"  {f'grep lookup ({tier})':<22} ~{look:>12,} tok   ({n_match} matches)\n")
    for ln in sample:
        print(f"    {ln[:100]}")
    print(f"\n  -> grep ~{whole // look:,}x cheaper than whole-doc read"
          + (f"; ~{comp // look:,}x cheaper than COMPACT" if comp else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
