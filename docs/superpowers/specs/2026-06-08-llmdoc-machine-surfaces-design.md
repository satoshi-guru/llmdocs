# llmdoc machine-surface acquisition — design

- **Date:** 2026-06-08
- **Issue:** [satoshi-guru/llmdocs#12](https://github.com/satoshi-guru/llmdocs/issues/12)
- **Branch:** `worktree-feat+md-mcp-acquisition`

## Problem

`crawler.py` has two acquisition strategies: `http` (HTML scrape) and `github` (repo
`.md`/`.mdx`). Modern doc sites publish **machine-readable surfaces** that are cleaner and
cheaper than scraping HTML, and llmdoc uses none of them:

| Surface | Example | Status today |
|---------|---------|--------------|
| `/llms.txt` + per-page `.md` twins | code.claude.com, docs.asterdex.com | prototype only — `scripts/fetch_llms_md.py`, hardcoded to Anthropic, not in crawler |
| `/llms.txt` indexing **HTML pages** | printingpress.dev | not handled |
| Direct `.md` suffix (`page.md?displayAgentInstructions=false`) | any GitBook/Mintlify page | not handled |
| MCP endpoint (`~gitbook/mcp`) | docs.asterdex.com | not handled |

## Key finding (real-world recon, 2026-06-08)

`llms.txt` is **not** a single format. It is fundamentally a **page-enumeration source**,
decoupled from how each page is fetched. Two flavors observed in the wild:

| Flavor | Example | Links point to | Correct fetch |
|--------|---------|----------------|---------------|
| Index of `.md` twins | docs.asterdex.com, code.claude.com | `…/page.md` | fetch raw markdown |
| Index of HTML pages | printingpress.dev (234-CLI catalog) | `…/library/<cat>/<cli>` | HTML-scrape each page (no `.md` twin — they 404) |

A naive "fetch the `.md` twin" implementation (the asterdex/claude shape) would 404 on every
printingpress page. The general design therefore treats `llms.txt` as the **authoritative URL
list** and adapts the fetch per page.

## Goal

Teach llmdoc to detect and use these surfaces automatically, with explicit `--strategy` /
preset still overriding.

## Architecture

### Auto-detect dispatcher (when no `--strategy` and no `--preset`)

Probe a base URL in order; first match wins:

```
1. GET <base>/llms.txt   → 200 AND parses to ≥1 markdown links  → strategy: llms-txt
2. MCP endpoint present   → (Phase 2) if --live/--both: register; if mirror & no llms.txt: mcp
3. GET <sample>.md twin   → returns text/markdown                → strategy: md   (rare)
4. fallback                                                       → strategy: http
```

Existing `--strategy http|github` and presets are unchanged and take precedence over
auto-detect.

### `llms-txt` strategy (Phase 1 — the core deliverable)

Generalized from `scripts/fetch_llms_md.py` (de-hardcode the Anthropic-only routing).

1. `GET <base>/llms.txt`; parse markdown links `[text](url)`; dedupe; keep same registrable
   domain only.
2. For each URL, **adaptive fetch**:
   - URL ends in `.md` → `GET` raw (append `?displayAgentInstructions=false`); require
     `content-type: text/markdown` (or markdown-looking body), else fall through.
   - else probe `<url>.md?displayAgentInstructions=false` → if markdown, use it.
   - else HTML-scrape the page via the existing `_fetch_and_extract`.
3. Write store output (per-page `.md` + frontmatter + `INDEX.md`) reusing `phase4_write`.

### Agent-instruction param

Always append `?displayAgentInstructions=false` to `.md` twin/raw fetches. GitBook uses it to
strip the injected "you are an agent…" preamble; non-GitBook sites ignore the unknown query
param, so it is safe to always send.

## Phasing (YAGNI — scoped to what the chosen targets need)

The first concrete targets are **printingpress.dev catalog** (llms-txt, HTML-page flavor) and
**`mvanhorn/cli-printing-press`** (existing `github` strategy). Neither needs MCP. So:

### Phase 1 — this sprint
- `llms-txt` strategy (adaptive per-page fetch) in `crawler.py`.
- Auto-detect dispatcher (probe order above, MCP step inert for now).
- `--strategy llms-txt` explicit override.
- Fix SKILL.md: it still invokes the old `llmdocs.py`; point it at `crawler.py`.
- Deliver: clean store mirrors of printingpress.dev + cli-printing-press.

### Phase 2 — deferred to issue #12
- Live MCP registration: `--mirror|--live|--both` mode flag; register a site's remote MCP
  endpoint into Claude MCP config. (Scope user-vs-project-vs-print-snippet TBD when built —
  recommended default: print the snippet, no surprise config writes.)
- `mcp` acquisition strategy: best-effort `getPage` BFS enumeration. Honest note: dominated by
  `llms.txt` for every GitBook site; only matters for an MCP-only-no-llms.txt site, which may
  not exist in practice. Ship as a stub that errors with guidance until a real target appears.

## Components

| Unit | Responsibility | Source |
|------|----------------|--------|
| `detect_surface(base_url) -> (strategy, meta)` | Probe llms.txt/.md, return choice + discovered URLs | new |
| `strategy: llms-txt` | enumerate via llms.txt → adaptive per-page fetch → write store | generalize `fetch_llms_md.py` |
| adaptive `fetch_page(url)` | `.md` raw → `.md` twin probe → HTML-scrape fallback | new, wraps `_fetch_and_extract` |
| `phase4_write` (reused) | per-page `.md` + frontmatter + INDEX | existing |

## Data flow (Phase 1, printingpress)

```
https://printingpress.dev/ → detect_surface → /llms.txt 200
  → parse 234 links (HTML pages) → per page: .md twin 404 → HTML-scrape
  → write printingpress-dev/*.md + INDEX → doc-indexer → manifest
```

## Testing

- Unit: `llms.txt` parser (markdown-link extraction, dedupe, host filter) on fixtures for both
  flavors (asterdex `.md`-twin sample + printingpress HTML-page sample).
- Unit: `fetch_page` decision logic (`.md` raw vs twin vs HTML) with mocked responses — no
  network in tests.
- Integration (manual, network): run on printingpress.dev + cli-printing-press, eyeball store
  output count and INDEX.

## Out of scope
- `--full` single-file `llms-full.txt` fast path (per-page is better for store/lookup).
- Caching MCP session tokens across runs.
- Any change to the `github` or `http` strategies beyond reuse.
