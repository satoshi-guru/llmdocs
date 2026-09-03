#!/usr/bin/env python3
"""Offline doc query over the global store — what Context7's resolve-library-id + query-docs do, from grep.

Why: docs that were worth fetching once are answered from `~/.llmdocs` (cheap, offline, deterministic);
web/MCP doc services are fallbacks. This program is the single entry point an agent (or a human) uses
instead of reading files by hand: resolve a library name to a store slug, get the best snippets for a
topic inside a token budget, open one page, list what exists, and get the exact fetch command when the
store lacks a library. Ladder per query: lib LOOKUP.md → global LOOKUP.md → COMPACT.md sections → raw
page paragraphs, ranked by term overlap (tf × idf over the lib's pages), never the whole doc.

Usage:
  query.py resolve <name> [--limit 5] [--json]          → slug candidates: slug, pages, indexed, source, fetched
  query.py query <lib> "<topic>" [--tokens 1500] [--limit 8] [--json]
                                                        → ranked snippets with tier + path, cut at the budget
  query.py page <lib> <path-fragment> [--tokens 4000]    → one page (frontmatter stripped), truncated at the budget
  query.py list [--filter TEXT] [--json]                 → libraries in the store with pages/indexed
  query.py missing <name>                                → the fetch command for a library that is not stored
  query.py --selftest
Env: LLMDOCS_HOME (store root, default ~/.llmdocs). Exit 0 hit, 1 no hit, 3 library not in store (fetch
command printed), 64 usage. Token estimate = chars/4 (same as manifest.py).
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

STORE_ROOT = Path(os.environ.get("LLMDOCS_HOME", Path.home() / ".llmdocs"))
SKIP = {"COMPACT.md", "INDEX.md", "LOOKUP.md"}
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "how", "do", "i", "is", "on", "by", "at",
        "from", "as", "it", "this", "that", "be", "are", "was", "can", "use", "using", "get", "set"}
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def store() -> Path:
    return Path(os.environ.get("LLMDOCS_HOME", STORE_ROOT)) / "docs"


def tok(text: str) -> int:
    return max(1, len(text) // 4)


def terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if t not in STOP and len(t) > 1]


def lib_dir(lib: str) -> Path:
    return store() / lib


def content_pages(lib: str) -> list[Path]:
    d = lib_dir(lib)
    return sorted(p for p in d.rglob("*.md") if p.name not in SKIP
                  and not any(part in ("_raw_html", "__pycache__") or part.startswith(".") for part in p.relative_to(d).parts))


def index_header(lib: str) -> dict:
    """Source / Pages / Fetched lines from INDEX.md, if present."""
    f = lib_dir(lib) / "INDEX.md"
    out = {"source": "", "fetched": "", "pages_declared": ""}
    if f.is_file():
        for ln in f.read_text(errors="replace").splitlines()[:12]:
            m = re.match(r"(Source|Fetched|Pages):\s*(.+?)\s*$", ln)
            if m:
                out[{"Source": "source", "Fetched": "fetched", "Pages": "pages_declared"}[m.group(1)]] = m.group(2)
    return out


def libs() -> list[str]:
    s = store()
    return sorted(p.name for p in s.iterdir() if p.is_dir() and not p.name.startswith(".")) if s.is_dir() else []


def lib_row(lib: str) -> dict:
    d = lib_dir(lib)
    hdr = index_header(lib)
    return {"slug": lib, "pages": len(content_pages(lib)), "indexed": (d / "COMPACT.md").is_file(),
            "lookup": (d / "LOOKUP.md").is_file(), "source": hdr["source"], "fetched": hdr["fetched"]}


# ---- resolve ---------------------------------------------------------------------------------
def norm(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"^@[\w-]+/", "", name)          # @scope/pkg → pkg
    name = re.sub(r"^(python-|py-|node-|js-)", "", name)
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def resolve(name: str, limit: int = 5) -> list[dict]:
    q = norm(name)
    scored: list[tuple[float, str]] = []
    for lib in libs():
        n = norm(lib)
        if n == q:
            score = 1.0
        elif q in n or n in q:
            score = 0.85 - abs(len(n) - len(q)) / 100
        else:
            score = difflib.SequenceMatcher(None, q, n).ratio() * 0.8
        if score >= 0.45:
            scored.append((score, lib))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"score": round(s, 2), **lib_row(lib)} for s, lib in scored[:limit]]


def fetch_hint(name: str) -> str:
    return (f"not in store: {name!r}. Fetch it for every repo with `/llmdoc {name}` (alias table in "
            f"~/.claude/skills/llmdoc/SKILL.md) or\n  {Path(__file__).parent.parent}/.venv/bin/python "
            f"{Path(__file__).parent.parent}/crawler.py --url <docs-url> --archive-existing --out ~/.llmdocs/docs/{norm(name)}/\n"
            f"then `python {Path(__file__).parent}/query.py resolve {name}`.")


# ---- query -----------------------------------------------------------------------------------
def split_sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) pairs of a markdown text; the preamble gets heading ''."""
    out, head, buf = [], "", []
    for ln in text.splitlines():
        if ln.startswith("#"):
            if buf:
                out.append((head, "\n".join(buf).strip()))
            head, buf = ln.lstrip("# ").strip(), []
        else:
            buf.append(ln)
    if buf:
        out.append((head, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if b]


def paragraphs(text: str, max_chars: int = 700) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out = []
    for p in paras:
        while len(p) > max_chars:
            out.append(p[:max_chars])
            p = p[max_chars:]
        out.append(p)
    return out


def score_snippet(snippet: str, qterms: list[str], idf: dict[str, float]) -> float:
    st = Counter(terms(snippet))
    if not st:
        return 0.0
    hits = [t for t in qterms if t in st]
    if not hits:
        return 0.0
    tf = sum(math.log1p(st[t]) * idf.get(t, 1.0) for t in hits)
    coverage = len(set(hits)) / len(set(qterms))
    return tf * (0.5 + coverage) / math.sqrt(1 + len(snippet) / 400)


def query(lib: str, topic: str, tokens: int = 1500, limit: int = 8) -> list[dict]:
    d = lib_dir(lib)
    qterms = terms(topic)
    if not qterms:
        return []
    pages = content_pages(lib)
    # idf over pages (+ COMPACT sections as one doc)
    df: Counter = Counter()
    page_text: dict[Path, str] = {}
    for p in pages:
        t = FRONTMATTER.sub("", p.read_text(errors="replace"))
        page_text[p] = t
        for term in set(terms(t)):
            df[term] += 1
    n_docs = max(1, len(pages))
    idf = {t: math.log(1 + n_docs / (1 + df[t])) for t in qterms}
    cands: list[dict] = []
    rx = re.compile("|".join(re.escape(t) for t in qterms), re.IGNORECASE)
    for tier, path in (("LOOKUP.md", d / "LOOKUP.md"), ("global LOOKUP.md", store() / "LOOKUP.md")):
        if path.is_file():
            for ln in path.read_text(errors="replace").splitlines():
                if tier.startswith("global") and not ln.startswith(f"{lib} |"):
                    continue
                if rx.search(ln):
                    cands.append({"tier": tier, "path": str(path.relative_to(store())), "text": ln.strip(),
                                  "score": score_snippet(ln, qterms, idf) * 1.3})
    compact = d / "COMPACT.md"
    if compact.is_file():
        for head, body in split_sections(compact.read_text(errors="replace")):
            for para in paragraphs(body):
                s = score_snippet(head + "\n" + para, qterms, idf)
                if s > 0:
                    cands.append({"tier": "COMPACT.md", "path": f"{lib}/COMPACT.md#{head}", "text": para, "score": s * 1.15})
    for p, t in page_text.items():
        title = ""
        m = re.search(r'^title:\s*"?(.*?)"?\s*$', p.read_text(errors="replace")[:400], re.MULTILINE)
        if m:
            title = m.group(1)
        for head, body in split_sections(t) or [("", t)]:
            for para in paragraphs(body):
                s = score_snippet(f"{title}\n{head}\n{para}", qterms, idf)
                if s > 0:
                    cands.append({"tier": "page", "path": f"{p.relative_to(store())}#{head}" if head else str(p.relative_to(store())),
                                  "text": para, "score": s})
    cands.sort(key=lambda c: -c["score"])
    out, used, seen = [], 0, set()
    for c in cands:
        key = c["text"][:120]
        if key in seen:
            continue
        cost = tok(c["text"]) + 8
        if used + cost > tokens or len(out) >= limit:
            break
        seen.add(key)
        used += cost
        c["tokens"] = cost
        out.append(c)
    return out


def page(lib: str, fragment: str, tokens: int = 4000) -> tuple[str | None, str]:
    frag = fragment.lower()
    hits = [p for p in content_pages(lib) if frag in str(p.relative_to(lib_dir(lib))).lower()]
    if not hits:
        return None, ""
    p = min(hits, key=lambda x: len(str(x)))
    text = FRONTMATTER.sub("", p.read_text(errors="replace")).lstrip("\n")
    return str(p.relative_to(store())), text[: tokens * 4]


# ---- cli -------------------------------------------------------------------------------------
def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LLMDOCS_HOME"] = tmp
        d = Path(tmp) / "docs" / "postiz-test"
        (d / "public-api").mkdir(parents=True)
        (d / "INDEX.md").write_text("# docs — LLM Index\n\nSource: https://docs.example.com  \nPages: 2  \nFetched: 2026-09-03  \n")
        (d / "COMPACT.md").write_text("# Compact\n\n## Auth\n\nAuthorization header takes the API key or pos_ OAuth token.\n\n## Posts\n\nPOST /public/v1/posts creates or schedules a post; rate limit 90 per hour.\n")
        (d / "LOOKUP.md").write_text("postiz-test | posts/create | POST /public/v1/posts | create or schedule a post\n")
        (d / "public-api" / "oauth.md").write_text('---\ntitle: "OAuth2 Authentication"\nurl: "https://docs.example.com/oauth"\n---\n\n# OAuth2\n\nUse the device flow to obtain a pos_ token for acting on behalf of users.\n\n## Refresh\n\nTokens expire; refresh with the refresh_token grant.\n')
        (d / "public-api" / "uploads.md").write_text("---\ntitle: \"Uploads\"\n---\n\n# Uploads\n\nUpload media first and reference it by public URL; 413 means base64 inlined.\n")
        r = resolve("Postiz")
        assert r and r[0]["slug"] == "postiz-test" and r[0]["pages"] == 2 and r[0]["indexed"], r
        assert resolve("@scope/postiz-test")[0]["score"] == 1.0
        assert resolve("nonexistent-zzz") == []
        q = query("postiz-test", "create a scheduled post rate limit", tokens=600)
        assert q and q[0]["tier"] in ("LOOKUP.md", "COMPACT.md") and "posts" in q[0]["text"].lower(), q
        q2 = query("postiz-test", "refresh token grant", tokens=300)
        assert q2 and q2[0]["tier"] == "page" and "refresh" in q2[0]["text"].lower(), q2
        assert sum(c["tokens"] for c in query("postiz-test", "post oauth upload", tokens=60)) <= 60
        path, text = page("postiz-test", "oauth")
        assert path and path.endswith("oauth.md") and text.startswith("# OAuth2"), (path, text[:20])
        assert page("postiz-test", "zzz")[0] is None
        assert "llmdoc" in fetch_hint("foo")
    print("selftest ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("cmd", nargs="?", choices=["resolve", "query", "page", "list", "missing"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--tokens", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--filter", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.print_help()
        return 64
    if a.cmd == "list":
        rows = [lib_row(lib) for lib in libs() if a.filter.lower() in lib.lower()]
        if a.json:
            print(json.dumps(rows, indent=1))
        else:
            for r in rows:
                print(f"{r['slug']:<40} {r['pages']:>6} pages  {'indexed' if r['indexed'] else '       '}  {r['fetched']:<10} {r['source'][:60]}")
        return 0 if rows else 1
    if a.cmd == "missing":
        if not a.args:
            ap.error("missing <name>")
        print(fetch_hint(a.args[0]))
        return 3
    if a.cmd == "resolve":
        if not a.args:
            ap.error("resolve <name>")
        rows = resolve(" ".join(a.args), a.limit or 5)
        if a.json:
            print(json.dumps(rows, indent=1))
        elif rows:
            for r in rows:
                print(f"{r['score']:.2f}  {r['slug']:<40} {r['pages']:>6} pages  {'indexed' if r['indexed'] else 'raw only'}  {r['fetched']:<10} {r['source'][:60]}")
        else:
            print(fetch_hint(" ".join(a.args)))
            return 3
        return 0
    if a.cmd == "query":
        if len(a.args) < 2:
            ap.error('query <lib> "<topic>"')
        lib, topic = a.args[0], " ".join(a.args[1:])
        if not lib_dir(lib).is_dir():
            cands = resolve(lib, 3)
            if cands and cands[0]["score"] >= 0.85:
                lib = cands[0]["slug"]
            else:
                print(fetch_hint(lib))
                return 3
        hits = query(lib, topic, a.tokens or 1500, a.limit or 8)
        if a.json:
            print(json.dumps(hits, ensure_ascii=False, indent=1))
        else:
            for h in hits:
                print(f"[{h['tier']} · {h['path']} · {h['tokens']} tok]\n{h['text']}\n")
            if not hits:
                print(f"no snippet in {lib} for {topic!r}; try other terms or `page {lib} <fragment>`")
        return 0 if hits else 1
    if a.cmd == "page":
        if len(a.args) < 2:
            ap.error("page <lib> <fragment>")
        path, text = page(a.args[0], a.args[1], a.tokens or 4000)
        if not path:
            print(f"no page in {a.args[0]} matching {a.args[1]!r}")
            return 1
        print(f"[{path}]\n{text}")
        return 0
    return 64


if __name__ == "__main__":
    sys.exit(main())
