#!/usr/bin/env python3
"""Deterministically build the LOOKUP.md grep tier (no LLM) for structured docs.

For docs where each page is one API/endpoint/concept (e.g. the Anthropic API reference),
a cheap one-line-per-page signature beats an expensive LLM distill. Per page it extracts:
  name  = path tail (e.g. messages/create)   sig = HTTP endpoint if present
  note  = leading `>` description or first prose line (truncated)
Writes <slug>/LOOKUP.md, and merges selected slugs into the global ~/.llmdocs/docs/LOOKUP.md
(skip the redundant per-language API slugs from the global table to avoid 9x duplicate hits).

Usage:
  python scripts/build_lookup.py <slug> [<slug> ...] [--global]
"""
from __future__ import annotations
import argparse, os, re, sys
from pathlib import Path

STORE = Path(os.environ.get("LLMDOCS_HOME", Path.home() / ".llmdocs")) / "docs"
SKIP = {"COMPACT.md", "INDEX.md", "LOOKUP.md"}
EP = re.compile(r"\*\*(post|get|delete|put|patch)\*\*\s*`?([^`\n]+)`?", re.I)


def pages(slug):
    d = STORE / slug
    return sorted(p for p in d.rglob("*.md")
                  if p.name not in SKIP
                  and not any(x in ("_raw_html", "__pycache__") or x.startswith(".")
                              for x in p.relative_to(d).parts))


def line_for(slug, p):
    d = STORE / slug
    rel = p.relative_to(d).with_suffix("")              # en/api/messages/create
    name = "/".join(rel.parts[2:]) or rel.parts[-1]      # messages/create
    text = p.read_text(errors="replace")
    body = text.split("---\n", 2)[-1] if text.startswith("---") else text
    ep = EP.search(body)
    sig = f"{ep.group(1).upper()} {ep.group(2).strip()}" if ep else ""
    note = ""
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith(">"):
            note = s.lstrip("> ").strip(); break
    if not note:
        for ln in body.splitlines():
            s = ln.strip()
            if s and not s.startswith(("#", "*", "<", "|", "```", "---")):
                note = s; break
    note = re.sub(r"\s+", " ", note)[:110]
    rhs = " — ".join(x for x in (sig, note) if x) or name
    return f"{slug} | {name} | {rhs}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--global", dest="glob", action="store_true",
                    help="also merge these slugs' lines into the global LOOKUP.md")
    args = ap.parse_args()
    global_lookup = STORE / "LOOKUP.md"
    existing = global_lookup.read_text(errors="replace") if global_lookup.exists() else ""
    add = []
    for slug in args.slugs:
        if not (STORE / slug).is_dir():
            print(f"  skip {slug}: not in store", file=sys.stderr); continue
        lines = [line_for(slug, p) for p in pages(slug)]
        (STORE / slug / "LOOKUP.md").write_text("\n".join(lines) + "\n")
        print(f"  {slug:<26} {len(lines):>4} lookup lines")
        if args.glob:
            add += [l for l in lines if l not in existing]
    if args.glob and add:
        with global_lookup.open("a") as f:
            f.write("\n".join(add) + "\n")
        print(f"  + {len(add)} lines merged into global LOOKUP.md")


if __name__ == "__main__":
    raise SystemExit(main())
