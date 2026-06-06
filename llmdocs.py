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
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import html2text as _h2t_mod
    _H2T_OK = True
except ImportError:
    _H2T_OK = False


# ---------------------------------------------------------------------------
# Global append-only doc store
# ---------------------------------------------------------------------------
# Every fetch lands in one shared store so docs are available to EVERY repo,
# not siloed per project. Versions never matter and nothing is ever replaced:
# new fetches ADD to the store. Override the base dir with $LLMDOCS_HOME.
LLMDOCS_HOME = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs"))
LLMDOCS_STORE = LLMDOCS_HOME / "docs"


def _slug(name: str) -> str:
    """Filesystem-safe slug from a domain/name for the store folder."""
    s = re.sub(r"^https?://", "", name or "").strip("/")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-").lower()
    return s or "docs"


# ---------------------------------------------------------------------------
# URL skip patterns — prevent locale + version-mirror duplicate explosions
# ---------------------------------------------------------------------------
# Many doc sites expose the same content under multiple paths (locale variants,
# historical version pins). Without these filters, an uncapped same-domain
# crawl on e.g. git-scm.com fans out across thousands of near-duplicates:
#   /docs/git-credential                ← canonical (kept)
#   /docs/git-credential/fr             ← locale mirror (skipped)
#   /docs/git-credential/zh_HANS-CN     ← locale mirror (skipped)
#   /docs/git-credential/2.43.0         ← version mirror (skipped)
# A site can override these by setting `skip_url_patterns: []` in its preset.

# Locale + version-pinned patterns are always safe to skip.
DEFAULT_SKIP_URL_PATTERNS = [
    # Non-English locale segments anywhere in path.
    # Whitelists /en/ (canonical for readthedocs and many other doc sites).
    # Matches: /fr/, /de/, /pt_BR/, /zh_HANS-CN/, /de_DE/, etc.
    r"/(?!en[/?#]|en$)[a-z]{2}(_[A-Z]{2,4}(-[A-Z]{2,4})?)?(/|$)",
    # Version-pinned paths: /2.43.0/, /v6.2/, /1.0/, /v0.1.5/
    r"/v?\d+\.\d+(\.\d+)?(/|$)",
]

# Version aliases that often mirror each other. We pick ONE as canonical
# (detected from the start URL) and skip the rest. Defaults to /stable/ if
# none appears in the start URL.
_VERSION_ALIASES = ["stable", "latest", "main", "master", "dev", "develop", "next"]


def _detect_canonical_version_slug(start_url: str) -> str | None:
    """Return the version alias present in start URL, or None."""
    path = urllib.parse.urlparse(start_url).path
    for slug in _VERSION_ALIASES:
        if f"/{slug}/" in path or path.rstrip("/").endswith(f"/{slug}"):
            return slug
    return None


def _build_skip_patterns(start_url: str) -> list[re.Pattern]:
    """Compile skip patterns for a given crawl, excluding the canonical slug."""
    canonical = _detect_canonical_version_slug(start_url)
    skip_aliases = [a for a in _VERSION_ALIASES if a != (canonical or "stable")]
    patterns = list(DEFAULT_SKIP_URL_PATTERNS)
    if skip_aliases:
        patterns.append(rf"/({'|'.join(skip_aliases)})(/|$)")
    return [re.compile(p) for p in patterns]


def _url_is_skipped(url: str, patterns: list[re.Pattern]) -> bool:
    """Return True if URL path matches any skip pattern."""
    path = urllib.parse.urlparse(url).path
    return any(p.search(path) for p in patterns)


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
        "url": "https://hyperliquid.gitbook.io/hyperliquid-docs",
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
    # Hypedexer — HL data API (fills, analytics, vaults — no 2k cap, cursor pagination)
    "example-site": {
        "name": "Hypedexer API Docs",
        "strategy": "http",
        "url": "https://docs.example-site.com",
        "out": "output/example-site",
        "content_selectors": ["article", "main", ".page-body", "[class*='content']"],
        "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']",
                           "[class*='toc']", "[class*='navbar']"],
        "max_depth": 5,
        "max_pages": 150,
        "same_domain_only": True,
        "rate_limit": 0.5,
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
        # Prefix is "/en" (not "/en/docs") so the crawl also reaches the API
        # reference under /en/api — the coverage the old llmdoc `anthropic` alias
        # (which pointed at /en/api/) provided. Capped at max_pages so the wider
        # prefix can't run away. Keeps `/llmdoc anthropic` comprehensive.
        "path_prefix": "/en",
        "max_depth": 5,
        "max_pages": 300,
        "same_domain_only": True,
        "rate_limit": 0.5,
    },
}

DEFAULT_HEADERS = {
    # Override via $LLMDOCS_UA — some sites (e.g. Meta developer docs) 400 on
    # browser-like UAs but serve 200 to plain/bot UAs. Default stays browser-like.
    "User-Agent": os.environ.get(
        "LLMDOCS_UA",
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ),
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
    skip_patterns = config.get("_skip_patterns") or _build_skip_patterns(config["url"])
    extra_skip = [re.compile(p) for p in config.get("extra_skip_patterns", [])]
    all_patterns = skip_patterns + extra_skip
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
        if _url_is_skipped(full_no_frag, all_patterns):
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


class _FetchThrottle:
    """Shared rate-limit gate across worker threads.
    Guarantees minimum `interval` seconds between any two HTTP fetches."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                sleep_for = self._next_at - now
            else:
                sleep_for = 0.0
            self._next_at = max(now, self._next_at) + self.interval
        if sleep_for > 0:
            time.sleep(sleep_for)


def _fetch_and_extract(
    url: str,
    depth: int,
    session: requests.Session,
    raw_dir: Path,
    out_dir: Path,
    config: dict,
    throttle: _FetchThrottle,
    log_lock: threading.Lock,
) -> tuple[dict | None, list[tuple[str, int]], dict | None]:
    """Fetch one URL, extract markdown, return (page_or_None, next_links, error_or_None).
    Thread-safe — no shared state mutated here beyond logging."""
    cache_key = re.sub(r"[^\w]", "_", url)[:120]
    cache_file = raw_dir / f"{cache_key}.html"

    if cache_file.exists():
        html = cache_file.read_text(encoding="utf-8", errors="replace")
        with log_lock:
            print(f"  cache  {url}")
    else:
        throttle.wait()
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            if r.status_code != 200:
                with log_lock:
                    print(f"  skip-{r.status_code}  {url}")
                return None, [], {"url": url, "status": r.status_code}
            html = r.text
            cache_file.write_text(html, encoding="utf-8")
            with log_lock:
                print(f"  fetch  {url}  ({len(html):,} bytes)")
        except Exception as exc:
            with log_lock:
                print(f"  ERROR  {url}: {exc}")
            return None, [], {"url": url, "error": str(exc)}

    soup = BeautifulSoup(html, "lxml")

    if len(soup.get_text(strip=True)) < 200:
        with log_lock:
            print(f"  thin-SPA  {url} — appears JS-rendered, skipping")
        return None, [], {"url": url, "error": "SPA/JS-rendered, no static content"}

    title_el = soup.find("h1") or soup.find("title")
    title = title_el.get_text(strip=True).split("|")[0].strip() if title_el else "Untitled"

    content_el = _extract_content(soup, config)
    if not content_el:
        return None, [], None

    md = _clean_md(_html_to_md(content_el))
    if len(md) < 80:
        return None, [], None

    page = {
        "url": url,
        "title": title,
        "markdown": md,
        "filepath": _url_to_path(url, out_dir),
        "depth": depth,
    }

    next_links: list[tuple[str, int]] = []
    max_depth = config.get("max_depth", 4)
    if depth < max_depth:
        for link in _links_from_soup(soup, url, config):
            next_links.append((link, depth + 1))

    return page, next_links, None


def phase1_http(config: dict, out_dir: Path) -> tuple[dict, list[dict]]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    start_url = config["url"]
    max_depth = config.get("max_depth", 4)
    max_pages = config.get("max_pages", 200)
    rate_limit = config.get("rate_limit", 0.5)
    workers = max(1, int(config.get("workers", 1)))
    raw_dir = out_dir / "_raw_html"
    raw_dir.mkdir(parents=True, exist_ok=True)

    config["_skip_patterns"] = _build_skip_patterns(start_url)
    canonical_slug = _detect_canonical_version_slug(start_url) or "stable (default)"

    visited: set[str] = set()
    pages: dict[str, dict] = {}
    errors: list[dict] = []
    throttle = _FetchThrottle(rate_limit)
    log_lock = threading.Lock()

    prefix_str = config.get("path_prefix") or "(none)"
    print(f"\n[Phase 1] HTTP crawl — {start_url}")
    print(f"          depth={max_depth}  max_pages={max_pages}  "
          f"rate={rate_limit}s  workers={workers}")
    print(f"          path_prefix: {prefix_str}")
    print(f"          canonical version slug: {canonical_slug}\n")

    current_wave: list[tuple[str, int]] = [(start_url, 0)]
    visited.add(start_url)

    while current_wave and len(visited) < max_pages:
        next_wave_seen: set[str] = set()
        next_wave: list[tuple[str, int]] = []

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(_fetch_and_extract, url, depth, session,
                          raw_dir, out_dir, config, throttle, log_lock)
                for url, depth in current_wave
            ]
            for fut in as_completed(futures):
                page, links, err = fut.result()
                if page is not None:
                    pages[page["url"]] = page
                if err is not None:
                    errors.append(err)
                for link, link_depth in links:
                    if link in visited or link in next_wave_seen:
                        continue
                    if len(visited) + len(next_wave) >= max_pages:
                        break
                    next_wave_seen.add(link)
                    next_wave.append((link, link_depth))

        for link, _ in next_wave:
            visited.add(link)
        current_wave = next_wave

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

def phase4_write(sorted_pages: list[tuple[str, dict]], out_dir: Path,
                 compact_pages: bool = True) -> list[dict]:
    index_entries = []
    print(f"\n[Phase 4] Writing {len(sorted_pages)} files"
          f"{' (deterministic min compaction)' if compact_pages else ' (raw)'}...")

    # Deterministic, no-LLM compaction applied at write time — so compaction is an
    # early pipeline step, not a deferred last one. `min` is lossless-ish (still
    # valid Markdown) and fence-safe (code preserved). Opt out with --raw.
    minify = None
    if compact_pages:
        import compact as _compact
        minify = _compact.minify

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

        if minify:
            content = minify(content)
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

    index_entries = phase4_write(sorted_pages, out_dir, config.get("compact_pages", True))
    _write_index(index_entries, out_dir, config)

    if errors:
        err_file = out_dir / "_errors.json"
        err_file.write_text(json.dumps(errors, indent=2))
        print(f"[Errors] {len(errors)} logged → {err_file}")

    if not config.get("keep_html", False):
        for sub in ("_raw_html", "_github_clone"):
            d = out_dir / sub
            if d.exists():
                shutil.rmtree(d)
                print(f"[cleanup] removed {d.name}/ (use --keep-html to retain)")

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
    parser.add_argument("--path-prefix", default=None,
                        help="Restrict crawl to URLs under this path (auto-derived from start URL's first segment; pass '' to disable)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Concurrent fetches per BFS wave (default 1; try 4 for batch refresh)")
    parser.add_argument("--rate-limit", type=float, default=None, dest="rate_limit",
                        help="Seconds between fetches across all workers (default 0.5; polite floor ~0.1)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Clear cached HTML/clone before running")
    parser.add_argument("--keep-html", action="store_true",
                        help="Keep _raw_html/ cache after successful run (default: deleted to save disk)")
    parser.add_argument("--raw", action="store_true",
                        help="Store fetched pages verbatim (skip the default deterministic 'min' compaction)")
    parser.add_argument("--list-presets", action="store_true",
                        help="List available presets and exit")
    parser.add_argument("--compact", choices=["min", "dense"],
                        help="Deterministically compact Markdown (no fetch, no LLM). "
                             "Input: file, directory, or - for stdin.")
    parser.add_argument("--expand", action="store_true",
                        help="Expand a 'dense' file back to Markdown (no fetch).")
    parser.add_argument("paths", nargs="*",
                        help="Input path(s) for --compact/--expand (or - for stdin).")
    args = parser.parse_args()

    if args.compact or args.expand:
        import compact as _compact

        RESERVED = {"INDEX.md", "COMPACT.md", "LOOKUP.md"}

        def _transform(text: str) -> str:
            if args.expand:
                return _compact.expand(text)
            return _compact.minify(text) if args.compact == "min" else _compact.densify(text)

        def _suffix() -> str:
            return ".md" if args.expand else f".{args.compact}.md"

        for target in (args.paths or ["-"]):
            if target == "-":
                sys.stdout.write(_transform(sys.stdin.read()))
                continue
            p = Path(target)
            files = ([f for f in sorted(p.glob("*.md")) if f.name not in RESERVED]
                     if p.is_dir() else [p])
            for f in files:
                out_text = _transform(f.read_text(encoding="utf-8"))
                if args.out == "-":
                    sys.stdout.write(out_text)
                else:
                    dest = Path(args.out) if (args.out and len(files) == 1) else f.with_suffix(_suffix())
                    dest.write_text(out_text, encoding="utf-8")
                    print(f"[compact] {f} -> {dest}")
        return 0

    if args.list_presets:
        print("\nAvailable presets:\n")
        for name, cfg in PRESETS.items():
            src = cfg.get("url") or cfg.get("github_repo", "?")
            # Show where docs ACTUALLY land (the global store), not the raw
            # "output/<key>" default that the redirect above rewrites at runtime.
            resolved = LLMDOCS_STORE / _slug(Path(cfg["out"]).name)
            print(f"  {name:<14} {src}")
            print(f"  {'':14} → {resolved}\n")
        return 0

    if args.preset:
        config = PRESETS[args.preset].copy()
    elif args.url:
        parsed_start = urllib.parse.urlparse(args.url)
        domain = parsed_start.netloc
        # Auto-derive path_prefix from the first path segment so the crawler
        # stays inside /docs/, /reference/, /ruff/, etc. and doesn't bleed
        # into /blog/, /customers/, /partners/ on shared-domain sites.
        # User can override with --path-prefix or "" to disable.
        if args.path_prefix is not None:
            path_prefix = args.path_prefix
        else:
            # File-like start URLs (e.g. /docs.html) have no canonical sub-tree
            # so we don't auto-restrict. Directory-like URLs get prefix = first segment.
            start_path = parsed_start.path
            is_file = bool(re.search(r"\.(html?|php|md|txt)$", start_path, re.IGNORECASE))
            first_segment = start_path.lstrip("/").split("/", 1)[0]
            if is_file or not first_segment or "." in first_segment:
                path_prefix = ""
            else:
                path_prefix = f"/{first_segment}/"

        config = {
            "name": domain,
            "strategy": args.strategy,
            "url": args.url,
            "out": args.out or f"output/{domain}",
            "content_selectors": ["main", "article", "#content", "[class*='content']"],
            "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']"],
            "max_depth": args.max_depth or 4,
            "max_pages": args.max_pages or 5000,
            "same_domain_only": True,
            "path_prefix": path_prefix,
            "rate_limit": args.rate_limit if args.rate_limit is not None else 0.5,
            "workers": args.workers,
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
    elif str(config.get("out", "")).startswith("output/"):
        # No explicit --out: land in the global append-only store rather than a
        # per-project ./output dir, so the docs are available to every repo.
        # Slug from the clean key already in `out` (e.g. "output/discord" ->
        # "discord"), NOT the human-readable `name` (which would give the ugly,
        # unpredictable "discord-developer-docs"). _slug() still sanitises/lowers
        # the basename, so the --url path (out = "output/<domain>") keeps its
        # prior behaviour. This makes the store slug equal to the token the user
        # typed, so /llmdoc and doc-prime can find it again.
        config["out"] = str(LLMDOCS_STORE / _slug(Path(config["out"]).name))
    if args.max_depth:
        config["max_depth"] = args.max_depth
    if args.max_pages:
        config["max_pages"] = args.max_pages
    if args.rate_limit is not None:
        config["rate_limit"] = args.rate_limit
    if args.workers and args.workers != 1:
        config["workers"] = args.workers

    if args.no_cache:
        for sub in ("_raw_html", "_github_clone"):
            d = Path(config["out"]) / sub
            if d.exists():
                shutil.rmtree(d)
                print(f"[cache] cleared {d}")

    config["keep_html"] = args.keep_html
    config["compact_pages"] = not args.raw
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
