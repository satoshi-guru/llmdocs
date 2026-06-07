---
name: docs-distill
description: Index locally-fetched docs into COMPACT.md (per-lib read tier, ~80–120 lines) + LOOKUP.md (global grep tier) for cheap, fast API lookup — a measured 99.8–99.97% token reduction vs raw docs. Auto-chained by /docs-fetch and /docs-prime after a fetch; also run standalone to (re)index libs already in ~/.llmdocs/docs/ that lack a COMPACT.md. Triggers: "index the docs", "build COMPACT/LOOKUP", "make the docs cheap to read", "re-index <lib>".
allowed-tools: Bash Read Write
---

# docs-distill

Index locally fetched docs into ultra-compact reference files for cheap, fast builder lookup.

**Operates on the global store `~/.llmdocs/docs/` (symlinked at `~/.claude/docs/`), not the
current project.** Indices are written back into that store so every repo shares them. The
store is **append-only**: re-indexing a lib refreshes that lib's own lines, but no library's
knowledge is ever removed — new findings are additive.

## What it does

Reads `~/.llmdocs/docs/<lib>/` folders and produces two artifacts:

1. **`~/.llmdocs/docs/<lib>/COMPACT.md`** — up to 120-line dense reference per library (target 80–120 lines):
   function signatures, key patterns, breaking changes, gotchas. Replaces reading 50+ raw pages.

2. **`~/.llmdocs/docs/LOOKUP.md`** — global single-file grep table across all indexed libs:
   one line per API pattern → `library | signature | note`.
   Builders grep this in <1s instead of reading any doc file.

## Usage

```
/docs-distill                    → index ALL libs that have ~/.llmdocs/docs/ but no COMPACT.md
/docs-distill fastapi            → re-index one lib
/docs-distill fastapi drizzle-orm → re-index specific libs
```

## When to run

- After `/docs-fetch` fetches new docs
- Before starting a sprint (to ensure COMPACT.md + LOOKUP.md are fresh)
- When a library upgrades and you re-fetch its docs

## Output token cost (measured — see `bench/REPORT.md`)

Measured by `python bench/bench.py` on real store libraries:

| What agents read | Tokens | Reduction vs full raw |
|-----------------|-------:|----------------------:|
| Raw docs folder (fastapi, 395 pages) | ~3,287,000 | — |
| `COMPACT.md` (the read tier) | ~900–1,300 | **99.8–99.97%** |
| `LOOKUP.md` lines for one lib (grep tier) | ~150–200 | **~99.9%** |

`COMPACT.md` is the benchmarked **read-tier default** — it keeps 100% of the golden
`must_have` signatures (recall gate) while the raw-docs baseline can drop them. `LOOKUP.md`
is the **grep tier** for "does this API exist / what's its signature" in 1–2 tokens.
Numbers regenerate with `python bench/bench.py --libs <lib> ...`.

## Instructions

Parse the arguments. If no arguments, find all `~/.llmdocs/docs/*/` directories that contain more than
2 files (have actual content, not just `_raw_html`).

For each target library:

### Step 1 — Discover content

```bash
ls ~/.llmdocs/docs/<lib>/ | grep -v "_raw_html\|INDEX.md\|COMPACT.md"
wc -l ~/.llmdocs/docs/<lib>/*.md ~/.llmdocs/docs/<lib>/**/*.md 2>/dev/null | sort -rn | head -20
```

Identify the 5-8 most content-rich files (largest `.md` files). Read those.
Skip: translation directories (de/, ja/, zh/, fr/, es/, pt/, ko/, ru/), changelogs, contributing guides, benchmarks.

Priority files to read first:
- `index.md`, `README.md`, `getting-started.md`, `quickstart.md`
- Files with names matching: `routes`, `queries`, `schema`, `config`, `api`, `models`, `client`, `middleware`
- Files under `reference/` or `api-reference/` directories

### Step 2 — Extract patterns

From each file read, extract ONLY:

**Function signatures** — exact syntax with types:
```
FastAPI(title="App", lifespan=handler) → FastAPI app instance
@router.get("/path", response_model=MyModel, status_code=200)
async def handler(id: int, db: Session = Depends(get_db)) → dict
```

**Breaking changes** — anything the docs flag as "deprecated", "removed", "changed in v":
```
⚠ v0.100+: `on_event("startup")` deprecated → use `lifespan` context manager
```

**Common mistakes** — anything the docs say "do not", "avoid", "note that", "important":
```
✗ Don't: response_model with Optional fields without default
✓ Do: use Union[Model, None] = None
```

**Complete runnable examples** — only if < 15 lines and self-contained. No `...` snippets.

### Step 3 — Write COMPACT.md

Write to `~/.llmdocs/docs/<lib>/COMPACT.md`:

```markdown
# <Library> — Compact Reference
# Source: <URL or folder>  |  Indexed: <date>  |  Raw pages: <N>
# Use this instead of reading raw docs. Grep LOOKUP.md for quick API lookup.

## Core API

<function signatures, one per line, with brief inline comment>

## Key Patterns

<3-5 complete runnable code blocks for the most common use cases>

## Breaking Changes / Gotchas

<bullet list — version-flagged where known>

## What NOT to Do

<bullet list of anti-patterns from docs>
```

Size guideline: **80–120 lines, hard cap 120**. COMPACT.md is a navigable *summary* tier — the
cap is a size guideline, not permission to silently drop answer-relevant content. If patterns
don't fit, prefer tighter phrasing over omission. The full content remains reachable via the
`.min.md` pages and `LOOKUP.md` — COMPACT is the fast path, not the only path.
Every line must be a direct quote or paraphrase from the actual docs — no invention.

### Step 4 — Update LOOKUP.md (global grep tier)

Emit ~15–20 of the library's most-grepped API lines — one line per pattern, format:

```
<lib> | <function/decorator/class name>(<key params>) | <one-line description>
```

Examples:
```
fastapi | FastAPI(title, lifespan) | create app instance
fastapi | @router.get(path, response_model, status_code) | GET route decorator
fastapi | Depends(callable) | dependency injection marker
fastapi | HTTPException(status_code, detail) | raise HTTP error
anthropic | client.messages.create(model, max_tokens, messages) | main completion call
anthropic | {"type":"text","text":"..."} | content block format
drizzle | db.select().from(table).where(eq(col,val)) | basic SELECT query
drizzle | db.insert(table).values({...}).onConflictDoUpdate({...}) | upsert pattern
```

Then pipe those lines to the merge script — it drops the lib's old lines, appends the new
block, keeps the file sorted, and never touches other libraries (the store is append-only):

```bash
printf '%s\n' \
  '<lib> | <sig> | <note>' \
  '<lib> | <sig> | <note>' \
  | (cd "$LLMDOCS_DIR" && python -m scripts.lookup_merge <lib>)
```

Do **not** hand-edit `LOOKUP.md` — always go through `scripts.lookup_merge` so the
sort + append-only invariants hold.

### Step 5 — Refresh manifest, then report

After writing COMPACT.md / LOOKUP.md, refresh the store manifest so the index of
everything gathered stays current:

```bash
(cd "$LLMDOCS_DIR" && python -m scripts.manifest)
```

```
=== docs-distill results ===
fastapi     → ~/.llmdocs/docs/fastapi/COMPACT.md  (78 lines, 12 signatures extracted)
anthropic   → ~/.llmdocs/docs/anthropic/COMPACT.md (65 lines, 8 signatures extracted)
...

~/.llmdocs/docs/LOOKUP.md updated — N total entries across M libraries

To use in a sprint:
  - Inject ~/.llmdocs/docs/<lib>/COMPACT.md into builder prompts instead of raw ~/.llmdocs/docs/
  - Run `grep "<lib>" ~/.llmdocs/docs/LOOKUP.md` to verify an import exists before writing it
  - docs-context skill reads COMPACT.md automatically if present
```
