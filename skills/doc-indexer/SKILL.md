# doc-indexer

Index locally fetched docs into ultra-compact reference files for cheap, fast builder lookup.

## What it does

Reads `docs/<lib>/` folders and produces two artifacts:

1. **`docs/<lib>/COMPACT.md`** — ~80-line dense reference per library:
   function signatures, key patterns, breaking changes, gotchas. Replaces reading 50+ raw pages.

2. **`docs/LOOKUP.md`** — global single-file grep table across all indexed libs:
   one line per API pattern → `library | signature | note`.
   Builders grep this in <1s instead of reading any doc file.

## Usage

```
/doc-indexer                    → index ALL libs that have docs/ but no COMPACT.md
/doc-indexer fastapi            → re-index one lib
/doc-indexer fastapi drizzle-orm → re-index specific libs
```

## When to run

- After `/llmdoc` fetches new docs
- Before starting a sprint (to ensure COMPACT.md + LOOKUP.md are fresh)
- When a library upgrades and you re-fetch its docs

## Output token cost

| What agents read | Tokens |
|-----------------|--------|
| Raw docs folder (e.g. 45 files) | ~40,000 |
| `docs/<lib>/COMPACT.md` | ~800 |
| `docs/LOOKUP.md` (all libs) | ~2,000 |

**Using COMPACT.md instead of raw docs = ~98% token reduction per builder.**

## Instructions

Parse the arguments. If no arguments, find all `docs/*/` directories that contain more than
2 files (have actual content, not just `_raw_html`).

For each target library:

### Step 1 — Discover content

```bash
ls docs/<lib>/ | grep -v "_raw_html\|INDEX.md\|COMPACT.md"
wc -l docs/<lib>/*.md docs/<lib>/**/*.md 2>/dev/null | sort -rn | head -20
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

Write to `docs/<lib>/COMPACT.md`:

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

Hard limit: **120 lines**. Cut lower-priority items if over limit.
Every line must be a direct quote or paraphrase from the actual docs — no invention.

### Step 4 — Update LOOKUP.md

Append (or create) `docs/LOOKUP.md`. Format — one line per API pattern:

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

When updating: remove old entries for the lib (grep -v "^<lib> |") then append new ones.
Keep LOOKUP.md sorted by library name.

### Step 5 — Report

```
=== doc-indexer results ===
fastapi     → docs/fastapi/COMPACT.md  (78 lines, 12 signatures extracted)
anthropic   → docs/anthropic/COMPACT.md (65 lines, 8 signatures extracted)
...

docs/LOOKUP.md updated — N total entries across M libraries

To use in a sprint:
  - Inject docs/<lib>/COMPACT.md into builder prompts instead of raw docs/
  - Run `grep "<lib>" docs/LOOKUP.md` to verify an import exists before writing it
  - lib-context skill reads COMPACT.md automatically if present
```
