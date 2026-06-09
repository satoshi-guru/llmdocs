#!/usr/bin/env python3
"""Maintain and validate the source-URL list for the global llmdocs store.

Every doc in the store should know *where it came from* — the canonical vendor URL it was
fetched from — so it can be re-fetched and kept current. In practice some INDEX.md files lost
that (`Source: ?`), and a recorded URL can silently go stale when a vendor moves their docs
(the BitUnix mirror's old `openapidoc.bitunix.com/.../introduction.html` started 404ing; the
live docs are at `www.bitunix.com/api-docs/futures/`). This script makes that list explicit,
recoverable, and verifiable.

It does three things:

  1. BUILD the registry — read every `~/.llmdocs/docs/<slug>/INDEX.md` `Source:` line into a
     {slug -> url} map. `?`/empty = unknown.
  2. RECOVER unknowns from the silos — the per-repo `docs/<slug>/` mirrors scattered across
     other repos are a BACKUP: they often recorded a valid URL the global store lost. For each
     unknown-source slug we look for a same-named silo with a real Source and suggest it. (We
     never delete silos — they are the verification/backup tier.)
  3. VALIDATE urls (--check-urls) — HEAD each known URL; flag dead (4xx/5xx) or moved
     (redirected elsewhere) so the list stays correct and newest, not one step behind.

Usage:
  python audit_sources.py                 # registry + unknowns + silo-recovery suggestions
  python audit_sources.py --check-urls    # also HEAD-validate every known URL (network)
  python audit_sources.py --json
  python audit_sources.py --silo-root ~/projects   # where to look for backup silos
"""
from __future__ import annotations
import argparse
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path

STORE = Path(os.environ.get("LLMDOCS_HOME", Path.home() / ".llmdocs")) / "docs"
DEFAULT_SILO_ROOT = Path(os.environ.get("LLMDOCS_SILO_ROOT", str(Path.home())))
RESERVED = {"INDEX.md", "COMPACT.md", "LOOKUP.md"}
_SRC_RE = re.compile(r"^Source:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
# Full browser-like headers — many high-value vendor docs (TikTok, Adobe) bot-block a bare
# request with a fake 404 or a hang, which would wrongly condemn a perfectly live doc. Sending
# a browser UA *and* Accept/Accept-Language gets past the naive walls; the sophisticated ones
# still block, which is why a failed probe is NEVER auto-actioned — it's advisory, human-confirmed.
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _read_source(index_path: Path) -> str:
    if not index_path.exists():
        return ""
    m = _SRC_RE.search(index_path.read_text(encoding="utf-8", errors="replace"))
    url = m.group(1).strip() if m else ""
    return "" if url in ("", "?") else url


def _pagecount(d: Path) -> int:
    return sum(1 for f in d.rglob("*.md") if f.name not in RESERVED)


def build_registry(store: Path) -> dict[str, dict]:
    reg: dict[str, dict] = {}
    if not store.is_dir():
        return reg
    for d in sorted(p for p in store.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if _pagecount(d) == 0 and not (d / "INDEX.md").exists():
            continue
        reg[d.name] = {"source": _read_source(d / "INDEX.md"), "pages": _pagecount(d)}
    return reg


def scan_silos(silo_root: Path, store: Path) -> dict[str, list[dict]]:
    """Find per-repo doc mirrors (backup tier) outside the store and read their Source URLs.
    Keyed by slug so an unknown-source global slug can be matched to a backup that knows it."""
    silos: dict[str, list[dict]] = {}
    if not silo_root.is_dir():
        return silos
    store_res = store.resolve()
    for idx in silo_root.rglob("INDEX.md"):
        d = idx.parent
        # skip the global store itself, VCS/dep noise, and ephemeral worktrees
        parts = set(d.parts)
        if store_res in d.resolve().parents or d.resolve() == store_res:
            continue
        if parts & {".git", "node_modules", ".venv"} or ".llmdocs" in parts:
            continue
        src = _read_source(idx)
        if not src:
            continue
        silos.setdefault(d.name, []).append({"path": str(d), "source": src, "pages": _pagecount(d)})
    return silos


def scan_archive(store: Path) -> dict[str, list[dict]]:
    """Mine the store's own `.archive/` for prior fetches that recorded a source URL.

    Archived copies are named `<slug>@<engine>-<timestamp>` and keep their original INDEX.md.
    They are the store's *own* provenance trail — "when and where we last got valid docs" — so
    a lost source can be reconstructed from real history rather than guessed. Keyed by slug,
    each candidate carries its source, the INDEX `Fetched:` date (if any), and the dir mtime."""
    archives: dict[str, list[dict]] = {}
    adir = store / ".archive"
    if not adir.is_dir():
        return archives
    for d in adir.iterdir():
        if not d.is_dir() or "@" not in d.name:
            continue
        slug = d.name.split("@", 1)[0]
        src = _read_source(d / "INDEX.md")
        if not src:
            continue
        fetched = ""
        idx = d / "INDEX.md"
        if idx.exists():
            fm = re.search(r"^Fetched:\s*(.+?)\s*$", idx.read_text(encoding="utf-8", errors="replace"),
                           re.MULTILINE | re.IGNORECASE)
            fetched = fm.group(1).strip() if fm else ""
        archives.setdefault(slug, []).append(
            {"path": str(d), "source": src, "fetched": fetched, "mtime": d.stat().st_mtime})
    return archives


def recover_source(slug: str, silos: dict, archives: dict) -> dict | None:
    """Reconstruct a lost source URL from REAL provenance only — never a guess.

    Considers every recorded candidate (backup silos + archived prior fetches) and returns the
    most recent one, tagged with where it came from and when. Returns None if no real record
    exists anywhere — in which case the URL must be supplied by a human, not invented."""
    cands: list[dict] = []
    for c in silos.get(slug, []):
        cands.append({"source": c["source"], "origin": f"silo {c['path']}", "when": ""})
    for c in archives.get(slug, []):
        cands.append({"source": c["source"], "origin": f"archive {Path(c['path']).name}",
                      "when": c["fetched"], "_mtime": c["mtime"]})
    if not cands:
        return None
    # Prefer the freshest evidence: archives carry an mtime; silos sort after by default.
    cands.sort(key=lambda c: c.get("_mtime", 0.0), reverse=True)
    return cands[0]


def validate_url(url: str, timeout: int = 25) -> dict:
    """Classify a source URL into one of four states — never just 'dead'.

      live       — 2xx
      moved      — redirected to a different final URL
      gone       — a DEFINITIVE 404/410 (the only state that means 'really dead')
      unverified — timeout, connection error, 403/429 block, or 5xx: we COULDN'T check.

    The split between `gone` and `unverified` is the whole point. Many high-value vendor
    docs are bot-hostile (Adobe helpx returns 200 in a browser but blocks/​times-out a HEAD)
    or briefly down. Dropping such a doc because one probe failed is far worse than keeping a
    maybe-stale one, so `unverified` must NEVER be treated as a reason to remove a doc — only
    to recheck it later. Tries HEAD then GET (some servers refuse HEAD)."""
    last: object = None
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                final = r.geturl()
                moved = final.rstrip("/") != url.rstrip("/")
                return {"state": "moved" if moved else "live", "status": r.status,
                        "moved_to": final if moved else None}
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return {"state": "gone", "status": e.code, "moved_to": None}
            last = e.code           # 403/405/429/5xx → try GET, then give up as unverified
            continue
        except Exception as e:
            last = str(e)
            continue
    return {"state": "unverified", "status": last, "moved_to": None}


def main() -> int:
    ap = argparse.ArgumentParser(description="audit/validate the llmdocs source-URL list")
    ap.add_argument("--check-urls", action="store_true", help="HEAD-validate every known URL (network)")
    ap.add_argument("--silo-root", default=str(DEFAULT_SILO_ROOT), help="where backup silos live")
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    store = Path(args.store)
    reg = build_registry(store)
    silos = scan_silos(Path(args.silo_root), store)
    archives = scan_archive(store)

    unknown = {s: i for s, i in reg.items() if not i["source"]}
    known = {s: i for s, i in reg.items() if i["source"]}

    # Recover unknowns from REAL provenance only (backup silos + archived prior fetches),
    # never a guessed URL. recover_source returns None when no record exists anywhere.
    recovered: dict[str, dict] = {}
    for slug in unknown:
        rec = recover_source(slug, silos, archives)
        if rec:
            recovered[slug] = rec

    # Some INDEX files recorded a descriptive note ("llms.txt (platform.claude.com)") instead
    # of a real URL — those can't be HEAD-validated and must NOT be reported as dead. Split
    # them out as their own data-quality finding (the source should be the actual fetch URL).
    non_url = {s: i["source"] for s, i in known.items()
               if not i["source"].lower().startswith(("http://", "https://"))}
    validations: dict[str, dict] = {}
    if args.check_urls:
        for slug, info in known.items():
            if slug in non_url:
                continue
            validations[slug] = validate_url(info["source"])

    if args.json:
        print(json.dumps({
            "known": known, "unknown": unknown, "non_url": non_url,
            "recovered": recovered, "validations": validations,
        }, indent=2))
        return 0

    print(f"Source-URL registry for {store}  ({len(reg)} libraries)\n")
    print(f"  known source:   {len(known)}")
    print(f"  UNKNOWN source: {len(unknown)}")
    if unknown:
        print("\nUnknown-source docs (can't be re-fetched until a URL is recorded):")
        for slug in sorted(unknown):
            rec = recovered.get(slug)
            if rec:
                when = f" (last seen {rec['when']})" if rec.get("when") else ""
                tag = f"→ recover from {rec['origin']}{when}: {rec['source']}"
            else:
                tag = "→ NO recorded source anywhere; supply manually — DO NOT guess a URL"
            print(f"    {slug:<24} ({unknown[slug]['pages']} pages)  {tag}")

    if non_url:
        print(f"\nNon-URL sources ({len(non_url)}) — recorded a note, not a fetchable URL; "
              f"set the real fetch URL so they can be validated/refreshed:")
        for slug in sorted(non_url):
            print(f"    {slug:<24} source: {non_url[slug]!r}")

    if args.check_urls:
        gone = {s: v for s, v in validations.items() if v["state"] == "gone"}
        moved = {s: v for s, v in validations.items() if v["state"] == "moved"}
        unver = {s: v for s, v in validations.items() if v["state"] == "unverified"}
        live = len(validations) - len(gone) - len(moved) - len(unver)
        print(f"\nURL validation:  {live} live, {len(gone)} apparent-404, {len(moved)} moved, "
              f"{len(unver)} unverified  ({len(non_url)} non-URL sources)")
        if gone:
            print("  Apparent 404 — CONFIRM IN A BROWSER before acting. An automated 404 is NOT proof:"
                  "\n  some sites (TikTok, Cloudflare-fronted docs) serve a fake 404 to non-browser"
                  "\n  probes while returning 200 to a real browser. Only act if a browser also 404s.")
            for slug, v in sorted(gone.items()):
                print(f"    404?   {slug:<24} HTTP {v.get('status')}  {known[slug]['source']}")
        for slug, v in sorted(moved.items()):
            print(f"    MOVED  {slug:<24} {known[slug]['source']}  →  {v['moved_to']}")
        if unver:
            print(f"\n  Unverified (KEEP — probe failed, likely bot-block/slow/transient; recheck later):")
            for slug, v in sorted(unver.items()):
                print(f"    keep   {slug:<24} ({v.get('status')})  {known[slug]['source']}")

    if not unknown and not (args.check_urls and any(not v["ok"] for v in validations.values())):
        print("\nAll sources known" + (" and live." if args.check_urls else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
