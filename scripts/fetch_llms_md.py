#!/usr/bin/env python3
"""Fetch SPA docs via their `llms.txt` index + per-page `.md` twins.

Sites like platform.claude.com / code.claude.com are Next.js SPAs: a normal HTML crawl
returns "Loading..." shells. But each page has a raw-markdown twin (the `.md` URLs listed
in the site's `llms.txt`). This fetches those directly and writes normal store output
(frontmatter per page + INDEX.md per slug), routing pages into navigable per-section /
per-language slugs so a lookup returns one hit, not nine.

Reference implementation for the crawler `llms-txt` strategy (llmdocs-internal#56).

Usage:
  python scripts/fetch_llms_md.py                 # full Claude/Anthropic structured fetch
  python scripts/fetch_llms_md.py --only claude-agent-sdk     # one slug (test)
  python scripts/fetch_llms_md.py --limit 5       # cap pages per slug (test)
"""
from __future__ import annotations
import argparse, re, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

STORE = Path.home() / ".llmdocs" / "docs"
UA = {"User-Agent": "llmdocs-llms-md-fetch"}
LANGS = {"python", "typescript", "cli", "go", "java", "php", "ruby", "csharp", "terraform"}


def get(url, timeout=20):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1.5)


def route_anthropic(path):
    # path like /docs/en/api/python/messages/post.md
    segs = path.split("/docs/en/", 1)[-1].split("/")
    if not segs or not segs[0]:
        return None
    s0 = segs[0]
    if s0 == "api":
        if len(segs) > 1 and segs[1] in LANGS:
            return f"anthropic-api-{segs[1]}"
        return "anthropic-api"
    if s0 == "agents-and-tools":
        return "anthropic-agents-tools"
    if s0 in ("build-with-claude", "intro", "get-started", "test-and-evaluate"):
        return "anthropic-build"
    if s0 == "manage-claude":
        return "anthropic-manage"
    if s0 == "managed-agents":
        return "anthropic-managed-agents"
    return None


def route_agent_sdk(path):
    return "claude-agent-sdk" if "/agent-sdk/" in path else None


SOURCES = [
    ("https://platform.claude.com/llms.txt", route_anthropic),
    ("https://code.claude.com/docs/llms.txt", route_agent_sdk),
]


def is_junk(body):
    head = body[:400].lstrip()
    return (len(body) < 400 or head.lower().startswith("loading...")
            or head.startswith("<!doctype html") or head.startswith("<html"))


def archive_existing(slug):
    d = STORE / slug
    if d.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dest = STORE / ".archive" / f"{slug}@mdtwin-{ts}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        d.rename(dest)
        return str(dest)
    return None


def fetch_slug(slug, urls, host, rate, limit):
    if limit:
        urls = urls[:limit]
    arch = archive_existing(slug)
    d = STORE / slug
    written, skipped, index = 0, 0, []
    for i, url in enumerate(sorted(set(urls)), 1):
        body = get(url)
        if body is None or is_junk(body):
            skipped += 1
            continue
        rel = url.split("/docs/", 1)[-1]            # en/api/.../page.md
        fp = d / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        m = re.search(r"^#\s+(.+)$", body, re.M)
        title = m.group(1).strip() if m else rel.rsplit("/", 1)[-1][:-3]
        page_url = url[:-3] if url.endswith(".md") else url
        fp.write_text(f"---\ntitle: \"{title}\"\nurl: {page_url}\n"
                      f"fetched_with: llms-md\nfetched_at: {datetime.now(timezone.utc):%Y-%m-%d}\n---\n\n{body}")
        index.append((title, rel))
        written += 1
        if rate:
            time.sleep(rate)
        if i % 25 == 0:
            print(f"    {slug}: {i}/{len(urls)} ...", flush=True)
    # INDEX.md
    if written:
        lines = [f"# {host} — LLM Index", "", f"Source: llms.txt ({host})  ",
                 f"Pages: {written}  ", "", "---", ""]
        for title, rel in sorted(index, key=lambda x: x[1]):
            lines.append(f"- [{title}]({rel})")
        (d / "INDEX.md").write_text("\n".join(lines) + "\n")
    print(f"  {slug:<26} {written:>4} pages  ({skipped} skipped)" + (f"  [archived old → {Path(arch).name}]" if arch else ""), flush=True)
    return written, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="fetch just this slug")
    ap.add_argument("--limit", type=int, default=0, help="cap pages per slug (testing)")
    ap.add_argument("--rate", type=float, default=0.2, help="seconds between requests")
    args = ap.parse_args()

    grand_w = grand_s = 0
    for llms_url, router in SOURCES:
        host = re.search(r"https?://([^/]+)", llms_url).group(1)
        print(f"\n[index] {llms_url}", flush=True)
        idx = get(llms_url)
        if not idx:
            print(f"  !! could not fetch {llms_url}", flush=True)
            continue
        md_urls = re.findall(r"https?://[^\s)\"']+\.md", idx)
        buckets = {}
        for u in md_urls:
            path = re.sub(r"https?://[^/]+", "", u)
            slug = router(path)
            if slug:
                buckets.setdefault(slug, []).append(u)
        print(f"  {len(md_urls)} .md urls → {len(buckets)} slugs: {', '.join(sorted(buckets))}", flush=True)
        for slug in sorted(buckets):
            if args.only and slug != args.only:
                continue
            w, s = fetch_slug(slug, buckets[slug], host, args.rate, args.limit)
            grand_w += w
            grand_s += s
    print(f"\nTOTAL: {grand_w} pages written, {grand_s} skipped", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
