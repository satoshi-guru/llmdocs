#!/usr/bin/env python3
"""
llmdocs — Download, extract, sort, and convert any docs site to LLM-ready markdown.

Four phases:
  1. Fetch    — HTTP crawl or GitHub clone (for SPA/JS-heavy sites)
  2. Extract  — strip nav / JS / chrome, keep main content
  3. Sort     — organise by URL path depth then alphabetically
  4. Convert  — write clean .md files with YAML frontmatter for LLM consumption

Usage:
  python llmdocs.py --preset discord
  python llmdocs.py --preset hyperliquid
  python llmdocs.py --url https://example.com/docs --out docs/example
  python llmdocs.py --url https://example.com --strategy github --github-repo https://github.com/org/repo
  python llmdocs.py --list-presets
  python llmdocs.py --preset discord --no-cache

Dependencies:
  pip install beautifulsoup4 html2text lxml requests
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.parse
from collections import deque
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import html2text as _h2t_mod
    _H2T_OK = True
except ImportError:
    _H2T_OK = False


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict] = {
    # Discord uses a React SPA — clone the open-source docs repo instead
    "discord": {
        "name": "Discord Developer Docs",
        "strategy": "github",
        "github_repo": "https://github.com/discord/discord-api-docs",
        "github_docs_dir": "docs",
        "out": "output/discord",
        "file_extensions": [".md", ".mdx"],
    },
    # Hyperliquid — GitBook (static HTML)
    "hyperliquid": {
        "name": "Hyperliquid Docs",
        "strategy": "http",
        "url": "https://hyperliquid-dex.gitbook.io/hyperliquid-docs",
        "out": "output/hyperliquid",
        "content_selectors": ["article", "main", ".page-body", "[class*='content']"],
        "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']",
                           "[class*='toc']", "[class*='navbar']"],
        "path_prefix": "/hyperliquid-docs",
        "max_depth": 5,
        "max_pages": 300,
        "same_domain_only": True,
        "rate_limit": 0.6,
    },
    # OpenAI platform docs
    "openai": {
        "name": "OpenAI Platform Docs",
        "strategy": "http",
        "url": "https://platform.openai.com/docs",
        "out": "output/openai",
        "content_selectors": ["article", "main", "[class*='docs']", "[class*='content']"],
        "skip_selectors": ["nav", "footer", "header", "aside"],
        "path_prefix": "/docs",
        "max_depth": 4,
        "max_pages": 400,
        "same_domain_only": True,
        "rate_limit": 0.5,
    },
    # Anthropic Claude docs
    "anthropic": {
        "name": "Anthropic Claude Docs",
        "strategy": "http",
        "url": "https://docs.anthropic.com/en/docs",
        "out": "output/anthropic",
        "content_selectors": ["article", "main", "[class*='content']"],
        "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']"],
        "path_prefix": "/en/docs",
        "max_depth": 5,
        "max_pages": 300,
        "same_domain_only": True,
        "rate_limit": 0.5,
    },
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Phase 1a: HTTP crawl + content extraction
# ---------------------------------------------------------------------------

def _url_to_path(url: str, out_dir: Path) -> Path:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/") or "/index"
    safe = re.sub(r"[^\w/.-]", "_", path)
    if not safe.endswith(".md"):
        safe += ".md"
    return out_dir / safe.lstrip("/")


def _links_from_soup(soup: BeautifulSoup, base_url: str, config: dict) -> list[str]:
    root = urllib.parse.urlparse(config["url"])
    prefix = config.get("path_prefix", "")
    seen: set[str] = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full)
        full_no_frag = parsed._replace(fragment="").geturl()
        if config.get("same_domain_only") and parsed.netloc != root.netloc:
            continue
        if prefix and not parsed.path.startswith(prefix):
            continue
        if full_no_frag not in seen:
            seen.add(full_no_frag)
            out.append(full_no_frag)
    return out


def _extract_content(soup: BeautifulSoup, config: dict):  # type: ignore[return]
    for sel in config.get("content_selectors", ["main", "article", "body"]):
        el = soup.select_one(sel)
        if el:
            for skip in config.get("skip_selectors", []):
                for s in el.select(skip):
                    s.decompose()
            return el
    body = soup.find("body")
    if body:
        for skip in config.get("skip_selectors", []):
            for s in body.select(skip):
                s.decompose()
        return body
    return None


def _html_to_md(element) -> str:  # type: ignore[no-untyped-def]
    if _H2T_OK:
        h = _h2t_mod.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_tables = False
        h.body_width = 0
        h.unicode_snob = True
        return h.handle(str(element))
    return element.get_text(separator="\n", strip=True)


def _clean_md(text: str) -> str:
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    lines = [ln.rstrip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def phase1_http(config: dict, out_dir: Path) -> tuple[dict, list[dict]]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    start_url = config["url"]
    max_depth = config.get("max_depth", 4)
    max_pages = config.get("max_pages", 200)
    rate_limit = config.get("rate_limit", 0.5)
    raw_dir = out_dir / "_raw_html"
    raw_dir.mkdir(parents=True, exist_ok=True)

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    pages: dict[str, dict] = {}
    errors: list[dict] = []

    print(f"\n[Phase 1] HTTP crawl — {start_url}")
    print(f"          depth={max_depth}  max_pages={max_pages}  rate={rate_limit}s\n")

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        cache_key = re.sub(r"[^\w]", "_", url)[:120]
        cache_file = raw_dir / f"{cache_key}.html"

        if cache_file.exists():
            html = cache_file.read_text(encoding="utf-8", errors="replace")
            print(f"  cache  {url}")
        else:
            try:
                r = session.get(url, timeout=20, allow_redirects=True)
                if r.status_code != 200:
                    print(f"  skip-{r.status_code}  {url}")
                    errors.append({"url": url, "status": r.status_code})
                    continue
                html = r.text
                cache_file.write_text(html, encoding="utf-8")
                print(f"  fetch  {url}  ({len(html):,} bytes)")
                time.sleep(rate_limit)
            except Exception as exc:
                print(f"  ERROR  {url}: {exc}")
                errors.append({"url": url, "error": str(exc)})
                continue

        soup = BeautifulSoup(html, "lxml")

        # Thin body = JS-rendered SPA, skip
        if len(soup.get_text(strip=True)) < 200:
            print(f"  thin-SPA  {url} — appears JS-rendered, skipping")
            errors.append({"url": url, "error": "SPA/JS-rendered, no static content"})
            continue

        title_el = soup.find("h1") or soup.find("title")
        title = title_el.get_text(strip=True).split("|")[0].strip() if title_el else "Untitled"

        content_el = _extract_content(soup, config)
        if not content_el:
            continue

        md = _clean_md(_html_to_md(content_el))
        if len(md) < 80:
            continue

        pages[url] = {
            "title": title,
            "markdown": md,
            "filepath": _url_to_path(url, out_dir),
            "depth": depth,
        }

        if depth < max_depth:
            for link in _links_from_soup(soup, url, config):
                if link not in visited:
                    queue.append((link, depth + 1))

    print(f"\n[Phase 1] Done — {len(pages)} pages, {len(errors)} errors")
    return pages, errors


# ---------------------------------------------------------------------------
# Phase 1b: GitHub clone (for SPA docs with an open-source markdown repo)
# ---------------------------------------------------------------------------

def phase1_github(config: dict, out_dir: Path) -> tuple[dict, list[dict]]:
    repo_url = config["github_repo"]
    docs_subdir = config.get("github_docs_dir", "docs")
    extensions = config.get("file_extensions", [".md", ".mdx"])

    clone_dir = out_dir / "_github_clone"
    print(f"\n[Phase 1] GitHub clone — {repo_url}")

    if clone_dir.exists():
        print("  Updating existing clone...")
        result = subprocess.run(
            ["git", "-C", str(clone_dir), "pull", "--ff-only"],
            capture_output=True, text=True,
        )
        print(f"  git pull: {result.stdout.strip() or result.stderr.strip()}")
    else:
        print("  Cloning (shallow)...")
        result = subprocess.run(
            ["git", "clone", "--depth=1", repo_url, str(clone_dir)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr.strip()}")
            return {}, [{"url": repo_url, "error": result.stderr.strip()}]
        print("  Done.")

    source_dir = clone_dir / docs_subdir
    if not source_dir.exists():
        source_dir = clone_dir

    pages: dict[str, dict] = {}

    for ext in extensions:
        for md_file in sorted(source_dir.rglob(f"*{ext}")):
            rel = md_file.relative_to(source_dir)
            text = md_file.read_text(encoding="utf-8", errors="replace")

            title_match = re.search(r"^#{1,2}\s+(.+)", text, re.MULTILINE)
            title = (
                title_match.group(1).strip()
                if title_match
                else md_file.stem.replace("-", " ").title()
            )

            fake_url = f"{repo_url}/blob/main/{docs_subdir}/{str(rel).replace(chr(92), '/')}"
            out_path = out_dir / str(rel)
            if ext == ".mdx":
                out_path = out_path.with_suffix(".md")

            pages[fake_url] = {
                "title": title,
                "markdown": text,
                "filepath": out_path,
                "depth": len(rel.parts) - 1,
            }

    print(f"[Phase 1] Done — {len(pages)} files found")
    return pages, []


# ---------------------------------------------------------------------------
# Phase 3: Sort
# ---------------------------------------------------------------------------

def phase3_sort(pages: dict) -> list[tuple[str, dict]]:
    def _key(item: tuple[str, dict]) -> tuple[int, str]:
        depth: int = item[1].get("depth", 0)
        return (depth, item[0])

    return sorted(pages.items(), key=_key)


# ---------------------------------------------------------------------------
# Phase 4: Write LLM-ready markdown files
# ---------------------------------------------------------------------------

def phase4_write(sorted_pages: list[tuple[str, dict]], out_dir: Path) -> list[dict]:
    index_entries = []
    print(f"\n[Phase 4] Writing {len(sorted_pages)} files...")

    for url, data in sorted_pages:
        fp: Path = data["filepath"]
        fp.parent.mkdir(parents=True, exist_ok=True)

        md = data["markdown"]
        # Don't double-add frontmatter if source already has it
        if md.startswith("---"):
            content = md
        else:
            content = (
                f'---\ntitle: "{data["title"]}"\nurl: {url}\n---\n\n'
                f'# {data["title"]}\n\n{md}'
            )

        fp.write_text(content, encoding="utf-8")
        rel = str(fp.relative_to(out_dir))
        index_entries.append({"title": data["title"], "url": url, "file": rel})
        print(f"  write  {rel}")

    return index_entries


def _write_index(entries: list[dict], out_dir: Path, config: dict) -> None:
    sections: dict[str, list[dict]] = {}
    for e in entries:
        parts = [p for p in urllib.parse.urlparse(e["url"]).path.split("/") if p]
        section = parts[1] if len(parts) > 1 else (parts[0] if parts else "root")
        sections.setdefault(section, []).append(e)

    source = config.get("url") or config.get("github_repo", "?")
    lines = [
        f"# {config.get('name', 'Docs')} — LLM Index",
        f"\nSource: {source}  \nPages: {len(entries)}\n\n---\n",
    ]
    for section, sec_entries in sorted(sections.items()):
        lines.append(f"\n## {section.replace('-', ' ').replace('_', ' ').title()}\n")
        for e in sec_entries:
            lines.append(f"- [{e['title']}]({e['file']})")

    (out_dir / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[Index] {out_dir / 'INDEX.md'}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(config: dict) -> int:
    out_dir = Path(config["out"])
    out_dir.mkdir(parents=True, exist_ok=True)
    strategy = config.get("strategy", "http")

    print(f"\n{'='*60}")
    print(f"  llmdocs — {config.get('name', config.get('url', '?'))}")
    print(f"  strategy : {strategy}")
    print(f"  output   : {out_dir.resolve()}")
    print(f"{'='*60}")

    if strategy == "github":
        pages, errors = phase1_github(config, out_dir)
    else:
        pages, errors = phase1_http(config, out_dir)

    if not pages:
        print("\n[FATAL] No pages extracted.")
        if strategy == "http":
            print("  Tip: site may be a JS/SPA. Use --strategy github if docs are open source.")
        return 1

    print(f"\n[Phase 3] Sorting {len(pages)} pages...")
    sorted_pages = phase3_sort(pages)

    index_entries = phase4_write(sorted_pages, out_dir)
    _write_index(index_entries, out_dir, config)

    if errors:
        err_file = out_dir / "_errors.json"
        err_file.write_text(json.dumps(errors, indent=2))
        print(f"[Errors] {len(errors)} logged → {err_file}")

    print(f"\n{'='*60}")
    print(f"  Done — {len(pages)} pages → {out_dir.resolve()}")
    print(f"{'='*60}\n")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="llmdocs — download any docs site and convert it to LLM-ready markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--preset", choices=list(PRESETS.keys()), help="Use a named preset config")
    parser.add_argument("--url", help="Root URL to scrape (HTTP strategy)")
    parser.add_argument("--out", help="Output directory (overrides preset default)")
    parser.add_argument("--strategy", choices=["http", "github"], default="http",
                        help="Fetch strategy when using --url (default: http)")
    parser.add_argument("--github-repo", help="GitHub repo URL (strategy=github)")
    parser.add_argument("--github-docs-dir", default="docs",
                        help="Subdirectory in repo containing docs (default: docs)")
    parser.add_argument("--max-depth", type=int, help="HTTP crawl depth override")
    parser.add_argument("--max-pages", type=int, help="HTTP crawl page limit override")
    parser.add_argument("--no-cache", action="store_true",
                        help="Clear cached HTML/clone before running")
    parser.add_argument("--list-presets", action="store_true",
                        help="List available presets and exit")
    args = parser.parse_args()

    if args.list_presets:
        print("\nAvailable presets:\n")
        for name, cfg in PRESETS.items():
            src = cfg.get("url") or cfg.get("github_repo", "?")
            print(f"  {name:<14} {src}")
            print(f"  {'':14} → {cfg['out']}\n")
        return 0

    if args.preset:
        config = PRESETS[args.preset].copy()
    elif args.url:
        domain = urllib.parse.urlparse(args.url).netloc
        config = {
            "name": domain,
            "strategy": args.strategy,
            "url": args.url,
            "out": args.out or f"output/{domain}",
            "content_selectors": ["main", "article", "#content", "[class*='content']"],
            "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']"],
            "max_depth": args.max_depth or 4,
            "max_pages": args.max_pages or 200,
            "same_domain_only": True,
            "rate_limit": 0.5,
        }
        if args.strategy == "github":
            if not args.github_repo:
                parser.error("--github-repo is required when --strategy github")
            config["github_repo"] = args.github_repo
            config["github_docs_dir"] = args.github_docs_dir
    else:
        parser.error("Provide --preset or --url")

    if args.out:
        config["out"] = args.out
    if args.max_depth:
        config["max_depth"] = args.max_depth
    if args.max_pages:
        config["max_pages"] = args.max_pages

    if args.no_cache:
        for sub in ("_raw_html", "_github_clone"):
            d = Path(config["out"]) / sub
            if d.exists():
                shutil.rmtree(d)
                print(f"[cache] cleared {d}")

    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
