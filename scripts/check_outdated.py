#!/usr/bin/env python3
"""Flag stored docs that are likely outdated vs. their upstream.

For every library in the store ($LLMDOCS_HOME/docs, default ~/.llmdocs/docs) this
compares **when we last fetched it** (newest content-page mtime) against **the latest
upstream release date** pulled from the package registry (PyPI / npm / GitHub releases).

If upstream shipped a release *after* our snapshot, the doc is probably behind. This is
a cheap first-pass signal (one small API call per lib, no crawl) -- it does NOT prove the
doc *pages* changed (a patch release may touch zero docs). The precise confirmation is a
per-page content-hash / ETag check (see llmdocs-internal#55).

Libraries with no registry mapping (man pages, spec sites, proprietary API docs) can't be
version-checked this way and are reported as `no-registry`.

Usage:
  python scripts/check_outdated.py                 # full table, smallest docs first
  python scripts/check_outdated.py --behind-only    # only the ones upstream has moved past
  python scripts/check_outdated.py --sort age       # sort by snapshot age instead of size
  LLMDOCS_HOME=/some/where python scripts/check_outdated.py

Stdlib only; degrades gracefully on network/lookup errors (marked `?`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("LLMDOCS_HOME", Path.home() / ".llmdocs"))
STORE = HOME / "docs"
SKIP = {"COMPACT.md", "INDEX.md", "LOOKUP.md"}
TIMEOUT = 12

# slug -> (ecosystem, package id). Ecosystems: pypi | npm | github (owner/repo).
# Everything not listed has no machine-checkable release feed (man pages, spec sites,
# proprietary API docs) and is reported as `no-registry`.
REGISTRY = {
    # --- PyPI ---
    "anthropic": ("pypi", "anthropic"),
    "openai-agents": ("pypi", "openai-agents"),
    "mcp": ("pypi", "mcp"),
    "fastapi": ("pypi", "fastapi"),
    "fastapi-security": ("pypi", "fastapi"),
    "pydantic": ("pypi", "pydantic"),
    "uvicorn": ("pypi", "uvicorn"),
    "httpx": ("pypi", "httpx"),
    "websockets": ("pypi", "websockets"),
    "aiohttp": ("pypi", "aiohttp"),
    "eth-account": ("pypi", "eth-account"),
    "pyjwt": ("pypi", "PyJWT"),
    "pygithub": ("pypi", "PyGithub"),
    "cryptography": ("pypi", "cryptography"),
    "scikit-learn": ("pypi", "scikit-learn"),
    "sentence-transformers": ("pypi", "sentence-transformers"),
    "pytest": ("pypi", "pytest"),
    "ruff": ("pypi", "ruff"),
    "bandit": ("pypi", "bandit"),
    "defusedxml": ("pypi", "defusedxml"),
    "detect-secrets": ("pypi", "detect-secrets"),
    "paramiko": ("pypi", "paramiko"),
    "pip-audit": ("pypi", "pip-audit"),
    "semgrep": ("pypi", "semgrep"),
    "discordpy": ("pypi", "discord.py"),
    "matrix-nio": ("pypi", "matrix-nio"),
    "meshtastic-python": ("pypi", "meshtastic"),
    "siwe-py": ("pypi", "siwe"),
    "starlette": ("pypi", "starlette"),
    "claude-agent-sdk": ("pypi", "claude-agent-sdk"),
    # --- npm ---
    "expo": ("npm", "expo"),
    "expo-notifications": ("npm", "expo-notifications"),
    "expo-router": ("npm", "expo-router"),
    "nativewind": ("npm", "nativewind"),
    "supabase-js": ("npm", "@supabase/supabase-js"),
    "supabase": ("npm", "supabase"),
    "react-native": ("npm", "react-native"),
    "react-navigation": ("npm", "@react-navigation/native"),
    "reanimated": ("npm", "react-native-reanimated"),
    "drizzle-orm": ("npm", "drizzle-orm"),
    "ethers": ("npm", "ethers"),
    "viem": ("npm", "viem"),
    "viem-siwe": ("npm", "viem"),
    "zod": ("npm", "zod"),
    "prisma": ("npm", "prisma"),
    "trpc": ("npm", "@trpc/server"),
    "fastify": ("npm", "fastify"),
    "nextauth": ("npm", "next-auth"),
    "pnpm": ("npm", "pnpm"),
    "typescript": ("npm", "typescript"),
    "neon": ("npm", "@neondatabase/serverless"),
    # --- GitHub releases (owner/repo) ---
    "gitleaks": ("github", "gitleaks/gitleaks"),
    "trufflehog": ("github", "trufflesecurity/trufflehog"),
    "nuclei": ("github", "projectdiscovery/nuclei"),
    "httpx-pd": ("github", "projectdiscovery/httpx"),
    "ffuf": ("github", "ffuf/ffuf"),
    "syft": ("github", "anchore/syft"),
    "osv-scanner": ("github", "google/osv-scanner"),
    "sqlmap": ("github", "sqlmapproject/sqlmap"),
    "testssl": ("github", "drwetter/testssl.sh"),
    "aide": ("github", "aide/aide"),
    "fail2ban": ("github", "fail2ban/fail2ban"),
}


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "llmdocs-check-outdated"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except Exception:
        return None


def latest_release(eco, pkg):
    """Return (version, release_date YYYY-MM-DD) or (None, None) on failure."""
    if eco == "pypi":
        d = _get_json(f"https://pypi.org/pypi/{pkg}/json")
        if not d:
            return None, None
        ver = d["info"]["version"]
        urls = d.get("urls") or []
        when = urls[0]["upload_time"][:10] if urls else None
        if not when:
            files = d.get("releases", {}).get(ver) or []
            when = files[0]["upload_time"][:10] if files else None
        return ver, when
    if eco == "npm":
        d = _get_json(f"https://registry.npmjs.org/{pkg.replace('/', '%2F')}")
        if not d:
            return None, None
        ver = d.get("dist-tags", {}).get("latest")
        when = (d.get("time", {}).get(ver, "")[:10] or None) if ver else None
        return ver, when
    if eco == "github":
        d = _get_json(f"https://api.github.com/repos/{pkg}/releases/latest")
        if d and d.get("tag_name"):
            return d["tag_name"], (d.get("published_at") or "")[:10] or None
        tags = _get_json(f"https://api.github.com/repos/{pkg}/tags")
        if tags:
            return tags[0]["name"], None
        return None, None
    return None, None


def snapshot(lib):
    """(content-page count, newest-page date YYYY-MM-DD)."""
    pages = [
        p for p in lib.rglob("*.md")
        if p.name not in SKIP
        and not any(part in ("_raw_html", "__pycache__") or part.startswith(".")
                    for part in p.relative_to(lib).parts)
    ]
    if not pages:
        return 0, None
    newest = max(p.stat().st_mtime for p in pages)
    return len(pages), datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser(description="Flag stored docs likely outdated vs upstream.")
    ap.add_argument("--behind-only", action="store_true", help="only docs upstream has moved past")
    ap.add_argument("--sort", choices=["size", "age"], default="size",
                    help="size = smallest docs first (default); age = oldest snapshot first")
    args = ap.parse_args()

    if not STORE.is_dir():
        print(f"No store at {STORE}", file=sys.stderr)
        return 1

    rows = []
    for lib in sorted(p for p in STORE.iterdir() if p.is_dir() and not p.name.startswith(".")):
        pages, snap = snapshot(lib)
        eco_pkg = REGISTRY.get(lib.name)
        if not eco_pkg:
            rows.append((pages, lib.name, snap, "no-registry", None, None, "no-registry"))
            continue
        eco, pkg = eco_pkg
        ver, rel = latest_release(eco, pkg)
        if ver is None:
            status = "?"
        elif rel is None:
            status = "? (no date)"
        elif snap and rel > snap:
            status = "BEHIND"
        else:
            status = "ok"
        rows.append((pages, lib.name, snap, f"{eco}:{pkg}", ver, rel, status))

    if args.behind_only:
        rows = [r for r in rows if r[6] == "BEHIND"]
    rows.sort(key=lambda r: (r[2] or "9999") if args.sort == "age" else r[0])

    print(f"{'pages':>5}  {'doc':<24} {'snapshot':<11} {'latest':<14} {'released':<11} status")
    print("-" * 84)
    behind = 0
    for pages, name, snap, reg, ver, rel, status in rows:
        if status == "BEHIND":
            behind += 1
        print(f"{pages:>5}  {name:<24} {snap or '-':<11} {(ver or '-'):<14} {(rel or '-'):<11} {status}")
    checkable = sum(1 for r in rows if r[6] in ("BEHIND", "ok"))
    print("-" * 84)
    print(f"{len(rows)} docs / {checkable} version-checkable / {behind} BEHIND upstream / "
          f"{sum(1 for r in rows if r[6]=='no-registry')} no-registry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
