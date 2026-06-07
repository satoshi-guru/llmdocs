#!/usr/bin/env python3
"""
llmdocs — Download, extract, sort, and convert any docs site to LLM-ready markdown.

Four phases:
  1. Fetch    — HTTP crawl or GitHub clone (for SPA/JS-heavy sites)
  2. Extract  — strip nav / JS / chrome, keep main content
  3. Sort     — organise by URL path depth then alphabetically
  4. Convert  — write clean .md files with YAML frontmatter for LLM consumption

Usage:
  python crawler.py --preset discord
  python crawler.py --preset hyperliquid
  python crawler.py --url https://example.com/docs --out docs/example
  python crawler.py --url https://example.com --strategy github --github-repo https://github.com/org/repo
  python crawler.py --list-presets
  python crawler.py --preset discord --no-cache

Dependencies:
  pip install beautifulsoup4 html2text lxml requests
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
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
]

# Version-pinned paths: /2.43.0/, /v6.2/, /1.0/, /v0.1.5/. These are normally
# OLD duplicate doc trees we want to skip (keep only the unversioned/canonical
# tree). The pattern is built in _build_skip_patterns so the ONE canonical
# version can be exempted -- see _CONCRETE_VERSION_RE / canonical_version.
# Binary / non-document asset extensions. Links to these are never followed and
# never written as pages -- otherwise a PDF/PNG/ZIP gets fetched, its raw bytes
# decoded as "text", and saved as a garbage .md (e.g. arbitrum turned ~40 audit
# PDFs into .md). Document formats (.html/.htm/.md/.txt/.php) are intentionally
# NOT in this list. Matched case-insensitively at the end of the URL path.
_ASSET_EXT_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|svg|ico|bmp|tiff?|"
    r"pdf|zip|tar|gz|tgz|bz2|xz|rar|7z|"
    r"woff2?|ttf|eot|otf|"
    r"mp4|mov|avi|webm|mkv|mp3|wav|ogg|flac|"
    r"css|js|mjs|map|"
    r"dmg|exe|bin|wasm|apk|deb|rpm|msi|"
    r"doc|docx|ppt|pptx|xls|xlsx)$",
    re.IGNORECASE,
)


_VERSION_PATH_RE = r"v?\d+\.\d+(\.\d+)?"
_CONCRETE_VERSION_RE = re.compile(rf"^{_VERSION_PATH_RE}$")

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


def _detect_concrete_version(start_url: str) -> str | None:
    """Return the concrete version segment in the start URL (e.g. 'v1.18',
    '0.77'), or None. Distinct from the alias slugs (latest/stable/...)."""
    for seg in urllib.parse.urlparse(start_url).path.split("/"):
        if seg and _CONCRETE_VERSION_RE.match(seg):
            return seg
    return None


def _dominant_linked_version(html: str, base_url: str, threshold: float = 0.5) -> str | None:
    """For an alias start page (e.g. /latest/) whose real content lives under a
    concrete version, return that version (e.g. 'v1.18') if a single versioned
    first-segment dominates the same-domain links. Returns None when there is no
    clear winner, so callers can fall back safely."""
    root = urllib.parse.urlparse(base_url).netloc
    counts: dict[str, int] = {}
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        full = urllib.parse.urljoin(base_url, str(a["href"]).strip())
        p = urllib.parse.urlparse(full)
        if p.netloc != root:
            continue
        first = p.path.lstrip("/").split("/", 1)[0]
        if _CONCRETE_VERSION_RE.match(first):
            counts[first] = counts.get(first, 0) + 1
    if not counts:
        return None
    total = sum(counts.values())
    top, n = max(counts.items(), key=lambda kv: kv[1])
    return top if n / total >= threshold else None


def _build_skip_patterns(start_url: str, canonical_version: str | None = None) -> list[re.Pattern]:
    """Compile skip patterns for a given crawl.

    Skips non-canonical version aliases (stable/latest/main/...) and version-pinned
    paths, EXCEPT the one canonical version (so a site whose only real content lives
    under /v1.18/ -- e.g. spec.matrix.org/latest/ aliasing to /v1.18/ -- is not skipped
    into oblivion)."""
    canonical = _detect_canonical_version_slug(start_url)
    skip_aliases = [a for a in _VERSION_ALIASES if a != (canonical or "stable")]
    patterns = list(DEFAULT_SKIP_URL_PATTERNS)
    if not canonical_version:
        # No version pinned -> the canonical tree is unversioned (e.g. /docs/), so
        # version-pinned paths (/docs/0.77/, /v6.2/) are OLD duplicate trees: skip them.
        # When a version IS pinned the path_prefix already restricts saves to that
        # tree and the bridge budget bounds wandering, so applying a generic
        # version-skip here only drops legit nested pages (e.g. /v1.18/changelog/v1.1/).
        patterns.append(rf"/{_VERSION_PATH_RE}(/|$)")
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
        # reference under /en/api — the coverage the old docs-fetch `anthropic` alias
        # (which pointed at /en/api/) provided. Capped at max_pages so the wider
        # prefix can't run away. Keeps `/docs-fetch anthropic` comprehensive.
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
    # Returns ALL same-domain, non-skipped links — link *discovery* is intentionally
    # NOT restricted by path_prefix. The prefix governs which pages are *saved*
    # (applied in phase1_http), not which links are followed, so that prefix pages
    # reachable only via an out-of-prefix bridge (e.g. /doc/x linked from /products/y)
    # are still discoverable. The crawl loop bounds the out-of-prefix excursion to 1 hop.
    root = urllib.parse.urlparse(config["url"])
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
        if _ASSET_EXT_RE.search(parsed.path):
            continue  # never follow/save binary assets (PDF/PNG/ZIP/font/...)
        if _url_is_skipped(full_no_frag, all_patterns):
            continue
        if full_no_frag not in seen:
            seen.add(full_no_frag)
            out.append(full_no_frag)
    return out


def _norm_url(url: str) -> str:
    """Canonical crawl key: drop fragment only. The trailing slash is preserved —
    for directory-style docs (e.g. readthedocs /en/latest/) it is significant and
    stripping it can 404/redirect. Trailing-slash *variants* are instead collapsed
    at the output layer, keyed by their shared filepath (see _file_key)."""
    return urllib.parse.urlparse(url)._replace(fragment="").geturl()


def _file_key(url: str, out_dir: Path) -> str:
    """Output-file identity for a URL. /doc/x and /doc/x/ map to the same file, so
    this collapses such variants — used to avoid double-fetching and duplicate
    INDEX rows without altering the URL we actually request."""
    return str(_url_to_path(url, out_dir))


def _derive_scope(start_url: str, path_prefix_arg: str | None,
                  max_depth_arg: int | None) -> tuple[str, int]:
    """Return (path_prefix, max_depth) for a raw --url crawl.

    - Directory URLs (/docs/, /reference/) -> first-segment silo, depth 4.
    - File leaves (.../cryptsetup.8.html) are specific documents, not tree hubs:
      scope to the file's PARENT directory and use a shallow depth (1 = page + its
      immediate references). Without this, a leaf on a huge densely-cross-linked
      reference site (man7.org) triggers a whole-domain crawl that times out and
      writes nothing. Root-level files (/x.html) keep an empty prefix (whole site).
    - Segments containing a dot, or an empty first segment -> empty prefix.
    Explicit --path-prefix / --max-depth always win (incl. --max-depth 0)."""
    start_path = urllib.parse.urlparse(start_url).path
    is_file = bool(re.search(r"\.(html?|php|md|txt)$", start_path, re.IGNORECASE))
    if path_prefix_arg is not None:
        path_prefix = path_prefix_arg
    elif is_file:
        parent = start_path.rsplit("/", 1)[0]
        path_prefix = f"{parent}/" if parent else ""
    else:
        first = start_path.lstrip("/").split("/", 1)[0]
        path_prefix = "" if (not first or "." in first) else f"/{first}/"
    if max_depth_arg is not None:
        max_depth = max_depth_arg
    else:
        max_depth = 1 if is_file else 4
    return path_prefix, max_depth


def _path_matches_prefix(url: str, prefix: str) -> bool:
    """A page is *saved* only if its path is under path_prefix (empty prefix = all).

    The prefix is normalized with a trailing slash (e.g. "/docs/"), so the directory
    index itself — the path WITHOUT the trailing slash (e.g. start URL "/docs") — also
    matches. Without this, a crawl started at "/docs" would discard its own landing page."""
    if not prefix:
        return True
    path = urllib.parse.urlparse(url).path
    return path.startswith(prefix) or path == prefix.rstrip("/")


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
) -> tuple[dict | None, list[str], dict | None]:
    """Fetch one URL, extract markdown, return (page_or_None, next_links, error_or_None).
    Thread-safe — no shared state mutated here beyond logging."""
    cache_key = re.sub(r"[^\w]", "_", url)[:120]
    cache_file = raw_dir / f"{cache_key}.html"

    if cache_file.exists():
        html = cache_file.read_text(encoding="utf-8", errors="replace")
        with log_lock:
            print(f"  cache  {url}")
    else:
        # Retry transient throttling/5xx with exponential backoff (honor Retry-After)
        # so rate-limited sites (e.g. MediaWiki under load) don't silently drop pages.
        _RETRY_CODES = {429, 500, 502, 503, 504}
        _MAX_ATTEMPTS = 3
        html = None
        last_status = None
        for _attempt in range(_MAX_ATTEMPTS):
            throttle.wait()
            try:
                r = session.get(url, timeout=20, allow_redirects=True)
            except Exception as exc:
                if _attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(min(2 ** _attempt, 10))
                    continue
                with log_lock:
                    print(f"  ERROR  {url}: {exc}")
                return None, [], {"url": url, "error": str(exc)}
            if r.status_code == 200:
                html = r.text
                break
            last_status = r.status_code
            if r.status_code in _RETRY_CODES and _attempt < _MAX_ATTEMPTS - 1:
                try:
                    delay = float(r.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    delay = 2 ** _attempt
                with log_lock:
                    print(f"  retry-{r.status_code}  {url} (in {min(delay, 30):.0f}s)")
                time.sleep(min(delay, 30))
                continue
            break
        if html is None:
            with log_lock:
                print(f"  skip-{last_status}  {url}")
            return None, [], {"url": url, "status": last_status}
        cache_file.write_text(html, encoding="utf-8")
        with log_lock:
            print(f"  fetch  {url}  ({len(html):,} bytes)")

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

    next_links: list[str] = []
    max_depth = config.get("max_depth", 4)
    if depth < max_depth:
        next_links = _links_from_soup(soup, url, config)

    return page, next_links, None


def phase1_http(config: dict, out_dir: Path) -> tuple[list[dict], list[dict]]:
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

    # --- Version canonicalization ---------------------------------------
    # If the start URL pins a concrete version (/v1.18/, /0.77/) OR aliases one
    # (/latest/, /stable/ whose page links predominantly to a numeric version),
    # restrict the crawl to that version and exempt it from the version-skip.
    # Without this, a site whose only real docs live under /v1.18/ (e.g.
    # spec.matrix.org/latest/ -> /v1.18/) is skipped to a single page, because the
    # generic version-skip drops its own canonical tree.
    canonical_version = _detect_concrete_version(start_url)
    if canonical_version is None and _detect_canonical_version_slug(start_url):
        try:
            throttle.wait()
            r0 = session.get(start_url, timeout=20, allow_redirects=True)
            if r0.status_code == 200:
                canonical_version = _dominant_linked_version(r0.text, start_url)
        except Exception:
            canonical_version = None
    if canonical_version:
        config["path_prefix"] = f"/{canonical_version}/"
        config["_skip_patterns"] = _build_skip_patterns(start_url, canonical_version)
        print(f"          version-pinned crawl -> /{canonical_version}/ (canonical tree)")

    prefix_str = config.get("path_prefix") or "(none)"
    print(f"\n[Phase 1] HTTP crawl — {start_url}")
    print(f"          depth={max_depth}  max_pages={max_pages}  "
          f"rate={rate_limit}s  workers={workers}")
    print(f"          path_prefix: {prefix_str}")
    print(f"          canonical version slug: {canonical_slug}\n")

    # Discovery is broad (same-domain); *saving* is narrow (path_prefix). To reach
    # prefix pages that are only linked from an out-of-prefix bridge page, we allow
    # following out-of-prefix links — but only BRIDGE_HOPS deep, so the crawl can't
    # wander off into marketing/blog subtrees. Each frontier item carries `budget`:
    # the number of further out-of-prefix hops it may spawn (reset to BRIDGE_HOPS on
    # any prefix-matching link). Prefix links are always followed.
    prefix = config.get("path_prefix", "")
    BRIDGE_HOPS = 1

    start_norm = _norm_url(start_url)
    # `claimed` dedupes by OUTPUT FILE (not URL string) so /doc/x and /doc/x/ —
    # which write to the same file — are fetched once and indexed once.
    claimed: set[str] = {_file_key(start_norm, out_dir)}
    current_wave: list[tuple[str, int, int]] = [(start_norm, 0, BRIDGE_HOPS)]
    visited.add(start_norm)

    # Write each page as it is extracted (not buffered to a final phase) so a crawl
    # that is killed or times out KEEPS what it already fetched. A SIGTERM/SIGINT
    # handler turns an interrupt into a graceful stop that still writes the INDEX. (#14)
    minify = None
    if config.get("compact_pages", True):
        import minify as _minify
        minify = _minify.minify
    _stop = {"flag": False}
    def _on_stop(_signum, _frame):
        _stop["flag"] = True
    _prev_int = signal.signal(signal.SIGINT, _on_stop)
    _prev_term = signal.signal(signal.SIGTERM, _on_stop)

    while current_wave and len(visited) < max_pages and not _stop["flag"]:
        wave_prefix: list[tuple[str, int, int]] = []   # saved-tier links — prioritized
        wave_bridge: list[tuple[str, int, int]] = []   # out-of-prefix bridge links

        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_meta = {
                ex.submit(_fetch_and_extract, url, depth, session,
                          raw_dir, out_dir, config, throttle, log_lock): (depth, budget)
                for url, depth, budget in current_wave
            }
            for fut in as_completed(fut_meta):
                src_depth, src_budget = fut_meta[fut]
                page, links, err = fut.result()
                if page is not None and _path_matches_prefix(page["url"], prefix):
                    fk = _file_key(page["url"], out_dir)
                    if fk not in pages:
                        _write_page(page, out_dir, minify, config.get("_provenance"))  # write now: survive interrupt
                    pages[fk] = page
                if err is not None:
                    errors.append(err)
                for raw_link in links:
                    link = _norm_url(raw_link)
                    fk = _file_key(link, out_dir)
                    if link in visited or fk in claimed:
                        continue
                    if _path_matches_prefix(link, prefix):
                        claimed.add(fk)
                        wave_prefix.append((link, src_depth + 1, BRIDGE_HOPS))
                    elif src_budget > 0:
                        # Bridge hops are depth-TRANSPARENT: a one-hop detour through an
                        # out-of-prefix page must not inflate the depth that gates doc
                        # discovery, or a /docs hub first reached via a bridge would hit
                        # max_depth early and drop its children (regressed react-native by
                        # 14). The excursion is already bounded by BRIDGE_HOPS.
                        claimed.add(fk)
                        wave_bridge.append((link, src_depth, src_budget - 1))

        # Prefix (saved) pages first so a max_pages cut never sacrifices a real doc
        # page for a bridge page that won't even be written.
        next_wave: list[tuple[str, int, int]] = []
        for link, link_depth, budget in wave_prefix + wave_bridge:
            if len(visited) + len(next_wave) >= max_pages:
                break
            visited.add(link)
            next_wave.append((link, link_depth, budget))
        current_wave = next_wave

    signal.signal(signal.SIGINT, _prev_int)
    signal.signal(signal.SIGTERM, _prev_term)
    # Build INDEX from whatever was saved (sorted identically to the buffered path).
    sorted_pages = phase3_sort(pages)
    index_entries = [
        {"title": d["title"], "url": d["url"],
         "file": str(d["filepath"].relative_to(out_dir))}
        for _k, d in sorted_pages
    ]
    _write_index(index_entries, out_dir, config)
    note = "  [TRUNCATED — interrupted before the crawl finished]" if _stop["flag"] else ""
    print(f"\n[Phase 1] Done — {len(pages)} pages saved "
          f"(prefix={prefix or '(none)'}), {len(visited)} visited, {len(errors)} errors{note}")
    return index_entries, errors


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
    used_subdir = docs_subdir
    if not source_dir.exists():
        source_dir = clone_dir            # repo has no docs/ subdir -> read from root
        used_subdir = ""

    # Detect the default branch for accurate blob URLs (#30 — was hardcoded 'main').
    branch = "main"
    try:
        r = subprocess.run(["git", "-C", str(clone_dir), "symbolic-ref", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            branch = r.stdout.strip()
    except Exception:
        pass

    # Skip non-doc dirs so the root fallback doesn't ingest CI templates / test
    # fixtures / examples as if they were docs (#29).
    _SKIP_DIRS = {".git", ".github", "testdata", "test", "tests", "__tests__",
                  "examples", "example", "node_modules", "vendor", "fixtures"}

    pages: dict[str, dict] = {}
    skipped = 0

    for ext in extensions:
        for md_file in sorted(source_dir.rglob(f"*{ext}")):
            rel = md_file.relative_to(source_dir)
            if _SKIP_DIRS.intersection(rel.parts[:-1]):
                skipped += 1
                continue
            text = md_file.read_text(encoding="utf-8", errors="replace")

            title_match = re.search(r"^#{1,2}\s+(.+)", text, re.MULTILINE)
            title = (
                title_match.group(1).strip()
                if title_match
                else md_file.stem.replace("-", " ").title()
            )

            rel_str = str(rel).replace(chr(92), "/")
            repo_path = f"{used_subdir}/{rel_str}" if used_subdir else rel_str
            fake_url = f"{repo_url}/blob/{branch}/{repo_path}"
            out_path = out_dir / str(rel)
            if ext == ".mdx":
                out_path = out_path.with_suffix(".md")

            pages[fake_url] = {
                "url": fake_url,   # _write_page reads data["url"]; github stored it only as the dict key
                "title": title,
                "markdown": text,
                "filepath": out_path,
                "depth": len(rel.parts) - 1,
            }

    note = f" ({skipped} non-doc files skipped)" if skipped else ""
    print(f"[Phase 1] Done — {len(pages)} files found{note}")
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

def _engine_version() -> str:
    """Short identifier of the engine that produced a fetch, for provenance:
    a VERSION file if present, else the engine repo's short git sha, else 'unknown'."""
    here = Path(__file__).resolve().parent
    vf = here / "VERSION"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip()[:40] or "unknown"
    try:
        r = subprocess.run(["git", "-C", str(here), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _write_page(data: dict, out_dir: Path, minify=None, provenance: dict | None = None) -> dict:
    """Write one page (frontmatter + optional min-compaction) to its output file and
    return its INDEX entry. Shared by the incremental HTTP crawl (#14) and the github
    strategy. `data["url"]` is the real source URL (the pages dict is keyed by the
    output-file for dedup — never use the key as the url). `provenance` (engine sha +
    fetched_at) is stamped into the frontmatter so every page records what made it."""
    url = data["url"]
    fp: Path = data["filepath"]
    fp.parent.mkdir(parents=True, exist_ok=True)
    md = data["markdown"]
    prov = ""
    if provenance:
        prov = f'fetched_with: {provenance.get("engine", "unknown")}\nfetched_at: {provenance.get("fetched_at", "")}\n'
    if md.startswith("---"):              # source already had frontmatter
        content = md
    else:
        # json.dumps emits a double-quoted scalar that is valid YAML and escapes
        # embedded `"`/newlines, so an attacker-influenced title (page <title> or
        # a GitHub heading) can't forge extra frontmatter keys. url too.
        title_yaml = json.dumps(data["title"])
        heading = data["title"].replace("\n", " ").strip()
        content = (f'---\ntitle: {title_yaml}\nurl: {json.dumps(url)}\n{prov}---\n\n'
                   f'# {heading}\n\n{md}')
    if minify:
        content = minify(content)
    fp.write_text(content, encoding="utf-8")
    return {"title": data["title"], "url": url, "file": str(fp.relative_to(out_dir))}


def phase4_write(sorted_pages: list[tuple[str, dict]], out_dir: Path,
                 compact_pages: bool = True, provenance: dict | None = None) -> list[dict]:
    print(f"\n[Phase 4] Writing {len(sorted_pages)} files"
          f"{' (deterministic min compaction)' if compact_pages else ' (raw)'}...")
    minify = None
    if compact_pages:
        import minify as _minify
        minify = _minify.minify
    index_entries = []
    for _file_key_unused, data in sorted_pages:
        entry = _write_page(data, out_dir, minify, provenance)
        index_entries.append(entry)
        print(f"  write  {entry['file']}")
    return index_entries


def _write_index(entries: list[dict], out_dir: Path, config: dict) -> None:
    sections: dict[str, list[dict]] = {}
    for e in entries:
        parts = [p for p in urllib.parse.urlparse(e["url"]).path.split("/") if p]
        section = parts[1] if len(parts) > 1 else (parts[0] if parts else "root")
        sections.setdefault(section, []).append(e)

    source = config.get("url") or config.get("github_repo", "?")
    prov = config.get("_provenance") or {}
    prov_line = ""
    if prov:
        prov_line = f"Engine: {prov.get('engine', 'unknown')}  \nFetched: {prov.get('fetched_at', '')}  \n"
    lines = [
        f"# {config.get('name', 'Docs')} — LLM Index",
        f"\nSource: {source}  \nPages: {len(entries)}  \n{prov_line}\n---\n",
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

def _archive_existing(out_dir: Path) -> Path | None:
    """Before re-fetching a slug, move its existing copy aside instead of overwriting,
    so we never lose a previous version. Destination:
    <store>/.archive/<slug>@<old-engine>-<YYYYMMDD-HHMMSS>/. Returns the archive path,
    or None if there was nothing to archive. Opt-in via --archive-existing (store
    fetches set it; sandbox fetches do not)."""
    idx = out_dir / "INDEX.md"
    if not (idx.exists() or any(out_dir.glob("*.md"))):
        return None
    eng = "unknown"
    if idx.exists():
        m = re.search(r"Engine:\s*(\S+)", idx.read_text(encoding="utf-8", errors="replace"))
        if m:
            eng = m.group(1)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(out_dir.stat().st_mtime))
    archive_root = out_dir.parent / ".archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    dest = archive_root / f"{out_dir.name}@{eng}-{stamp}"
    i = 1
    while dest.exists():
        dest = archive_root / f"{out_dir.name}@{eng}-{stamp}_{i}"; i += 1
    shutil.move(str(out_dir), str(dest))
    print(f"[archive] previous {out_dir.name}/ -> .archive/{dest.name}/")
    return dest


def run(config: dict) -> int:
    out_dir = Path(config["out"])
    if config.get("archive_existing") and out_dir.exists():
        _archive_existing(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    strategy = config.get("strategy", "http")
    config["_provenance"] = {"engine": _engine_version(),
                             "fetched_at": time.strftime("%Y-%m-%d")}

    print(f"\n{'='*60}")
    print(f"  llmdocs — {config.get('name', config.get('url', '?'))}")
    print(f"  strategy : {strategy}")
    print(f"  output   : {out_dir.resolve()}")
    print(f"{'='*60}")

    if strategy == "github":
        pages, errors = phase1_github(config, out_dir)
        if not pages:
            print("\n[FATAL] No pages extracted.")
            return 1
        sorted_pages = phase3_sort(pages)
        index_entries = phase4_write(sorted_pages, out_dir, config.get("compact_pages", True), config["_provenance"])
        _write_index(index_entries, out_dir, config)
    else:
        # HTTP crawl writes each page + the INDEX itself (incremental, interrupt-safe).
        index_entries, errors = phase1_http(config, out_dir)
        if not index_entries:
            print("\n[FATAL] No pages extracted.")
            print("  Tip: site may be a JS/SPA. Use --strategy github if docs are open source.")
            return 1
    n_written = len(index_entries)

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
    print(f"  Done — {n_written} pages → {out_dir.resolve()}")
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
    parser.add_argument("--archive-existing", action="store_true", dest="archive_existing",
                        help="before writing, move an existing slug copy to .archive/ "
                             "(never overwrite; store fetches should set this)")
    parser.add_argument("--raw", action="store_true",
                        help="Store fetched pages verbatim (skip the default deterministic 'min' compaction)")
    parser.add_argument("--list-presets", action="store_true",
                        help="List available presets and exit")
    parser.add_argument("--compact", choices=["min", "dense"],
                        help="Deterministically compact Markdown (no fetch, no LLM). "
                             "Input: file, directory, or - for stdin.")
    parser.add_argument("--expand", action="store_true",
                        help="Expand a 'dense' file back to Markdown (no fetch).")
    parser.add_argument("--check", action="store_true",
                        help="Verify each committed store page is already min-normalised "
                             "(idempotence gate). Exit 1 if minify(page) != page, 0 if up to date.")
    parser.add_argument("paths", nargs="*",
                        help="Input path(s) for --compact/--expand/--check (or - for stdin).")
    args = parser.parse_args()

    if args.compact or args.expand or args.check:
        import minify as _minify

        RESERVED = {"INDEX.md", "COMPACT.md", "LOOKUP.md"}

        if args.check:
            failed = False
            for target in (args.paths or []):
                p = Path(target)
                pages = ([f for f in sorted(p.glob("*.md")) if f.name not in RESERVED]
                         if p.is_dir() else [p])
                for f in pages:
                    if f.name.endswith(".min.md"):
                        continue  # skip any stray .min.md inputs
                    text = f.read_text(encoding="utf-8")
                    if _minify.minify(text) != text:
                        print(f"DRIFT: {f} is not min-normalised "
                              f"(run --compact min in place)", file=sys.stderr)
                        failed = True
                    else:
                        print(f"[check] up to date: {f}")
            return 1 if failed else 0

        def _transform(text: str) -> str:
            if args.expand:
                return _minify.expand(text)
            return _minify.minify(text) if args.compact == "min" else _minify.densify(text)

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
                    if args.expand:
                        # Expanding doc.dense.md / doc.min.md -> doc.md. f.with_suffix(".md")
                        # would be a NO-OP on a .dense.md/.min.md name and clobber the input.
                        dest = Path(re.sub(r"\.(dense|min)\.md$", ".md", f.name, flags=re.IGNORECASE))
                        dest = f.with_name(dest.name)
                        if dest == f:
                            # No infix to strip -> writing back would overwrite the source. Emit to stdout.
                            sys.stdout.write(out_text)
                            continue
                    elif args.out and len(files) == 1:
                        dest = Path(args.out)
                    else:
                        dest = f.with_suffix(_suffix())
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
        # path_prefix scopes which pages are saved; max_depth bounds how far we crawl.
        # See _derive_scope: directory URLs (/docs/) get a first-segment silo + depth 4;
        # file leaves (.../cryptsetup.8.html) get a parent-dir silo + shallow depth 1.
        path_prefix, derived_max_depth = _derive_scope(
            args.url, args.path_prefix, args.max_depth)

        config = {
            "name": domain,
            "strategy": args.strategy,
            "url": args.url,
            "out": args.out or f"output/{domain}",
            "content_selectors": ["main", "article", "#content", "[class*='content']"],
            "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']"],
            "max_depth": derived_max_depth,
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
        # typed, so /docs-fetch and docs-prime can find it again.
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
    config["archive_existing"] = args.archive_existing
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
