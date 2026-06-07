# llmdocs — project guide

Fetch any library's docs → LLM-ready markdown in a **global append-only store**
(`~/.llmdocs/docs/`), so a coding agent reads the *real, current* API for ~20–30 tokens
instead of guessing from training data or reading the whole site.

## The reflex: grep the store before guessing
Before answering any library/API question or writing code against a lib:
```bash
grep -i "<symbol>" ~/.llmdocs/docs/LOOKUP.md          # ~20-30 tok, the answer is the matching line
grep -i "<symbol>" ~/.llmdocs/docs/<lib>/LOOKUP.md     # one lib
cat ~/.llmdocs/MANIFEST.md                             # what's in the store
```
Measured: a grep lookup ≈ **29 tok**; reading `anthropic-api` whole ≈ **2.76M tok** (~95,000× cheaper,
and the only thing that fits a context window). If a lib isn't in the store, `/llmdoc <url>`.

## Scripts (scripts/, stdlib-only, reusable)
| script | what it does |
|--------|--------------|
| `check_outdated.py` | flag stale docs: snapshot date vs latest registry release (PyPI/npm/GH), no crawl |
| `fetch_llms_md.py`  | fetch SPA docs via `llms.txt` + per-page `.md` twin (platform/code.claude.com) |
| `build_lookup.py`   | deterministic (no-LLM) LOOKUP grep tier for structured docs |
| `lookup_cost.py`    | prove grep-lookup vs whole-doc read cost for any lib/query |
| `manifest.py` · `reindex.py` · `store_doctor.py` · `store_index.py` · `lookup_merge.py` | store upkeep |

## Key facts / gotchas
- **Crawlers:** `llmdocs.py` = OLD (built the current store); `crawler.py` = NEW/current. Audit history greps `llmdocs.py`.
- **Claude/Anthropic docs are Next.js SPAs** (platform.claude.com, code.claude.com, docs.anthropic.com →
  redirect loop). A plain crawl saves `"Loading…"` shells. Fetch the per-page `.md` twin via `llms.txt`
  (`fetch_llms_md.py`). The `anthropic` engine preset is broken (redirect loop) until repointed — see issues.
- **COMPACT.md = LLM-distilled (expensive); LOOKUP.md can be built deterministically** (`build_lookup.py`) — prefer it for structured/API docs.
- **One repo, not two.** Develop in the open in the public repo; privacy = keep secrets OUT of git
  entirely (never a parallel private repo). Private content (`dormant-features`, project identities)
  lives in untracked LOCAL notes only.
- **Never work on main** — every task gets its own branch. bg sessions: Edit/Write blocked by the
  worktree guard → write via shell heredoc.

## Session continuity
- `SESSION_STATE.md` — current sprint: done / open / next.
- Local (untracked, NOT in this repo): `~/Dokumente/llmdocs-improvements-backlog.md` (loop fodder),
  `~/Dokumente/llmdocs-SHOWCASE-NOTES.md` (Anthropic-attention audit — private).
