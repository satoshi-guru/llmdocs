---
name: doc-prime
description: Full pre-sprint doc workflow in one command — fetch library docs → compile LIB-CONTEXT.md → index COMPACT.md (wraps /llmdoc → /lib-context → /doc-indexer). Use when the user is about to start coding — a sprint, refactor, or feature ("before we touch any code") — and wants the docs for the libraries they'll use prepped and ready first. Triggers: "prime the docs for X and Y", "prep doc context", "get docs ready before the refactor", "run the full doc workflow", "starting the X sprint tomorrow, prime all the docs I'll need: A, B, C". Usually names 2+ libraries or a named stack (expo+supabase, fastapi+pydantic, python+hyperliquid). Don't use for a quick one-off single-library grab (use /llmdoc), or to only re-compile (/lib-context) or re-index (/doc-indexer) docs already in the store.
argument-hint: "[lib1] [lib2] ... — library names/URLs to fetch. Omit to re-run lib-context + doc-indexer on existing docs only."
allowed-tools: Bash Read Write
---

# doc-prime — Library Doc Workflow

Primes Claude's context with accurate, version-pinned library docs before implementation.
Always in order: **fetch → index → compile → refresh dashboard**. Indexing comes before
compiling because `lib-context` is a *consumer* of `COMPACT.md`, not a parallel generator.

Arguments: $ARGUMENTS

---

## Step 1 — Fetch docs (llmdoc)

**Follow the `llmdoc` skill instructions** for `$ARGUMENTS` — do **not** call `llmdocs.py`
directly here. `/llmdoc` is the single owner of token resolution (engine preset → `preset:`
group → alias → raw URL) and picks `--preset` vs `--url` correctly. This matters: routing a
React-SPA preset like `discord` through a plain `--url` fetches 0 pages, so doc-prime must not
re-implement the fetch — it would drift from llmdoc and miss the strategy routing. (Steps 2–3
below already defer to the lib-context / doc-indexer skills the same way; Step 1 is just
consistent with them.)

`/llmdoc` writes to the global store `~/.llmdocs/docs/<slug>/`, runs fetches sequentially with
the right timeout, and refreshes the manifest — you don't manage any of that here.

Before fetching, check what's already in the store to avoid duplicate work (crawlers follow
links across a domain, so one Expo URL already captures the full docs.expo.dev site):

```bash
ls ~/.llmdocs/docs/
```

If a slug already exists and seems recent (`ls -la ~/.llmdocs/docs/<slug>/`), skip re-fetching
it and tell the user.

**Important contract with Step 3:** `/llmdoc` already auto-chains `/doc-indexer` after a
successful fetch, so for libs you fetch here the `COMPACT.md` index is already built — Step 3
then only needs to run for libs that were *already* in the store but still lack a `COMPACT.md`.

If no arguments given, skip to Step 2.

---

## Step 2 — Index (doc-indexer)

Index **before** compiling — the indexer produces the `COMPACT.md` + `LOOKUP.md` tiers that
`lib-context` (Step 3) consumes. Libs fetched in Step 1 are **already indexed** (`/llmdoc`
auto-chains `/doc-indexer` after a successful fetch), so only index slugs that still lack a
`COMPACT.md` (e.g. libs already in the store from an older fetch):

Set `FETCHED_SLUGS` to the space-separated list of slugs successfully fetched in Step 1
(e.g. `FETCHED_SLUGS="expo supabase-js"`). If Step 1 was skipped (no arguments), set `FETCHED_SLUGS=""`.

```bash
# Which store libs (from prior sessions) are missing a COMPACT.md?
# Exclude libs fetched in Step 1 — /llmdoc already ran doc-indexer for those.
# FETCHED_SLUGS should be set to the space-separated list of slugs from Step 1.
for d in ~/.llmdocs/docs/*/; do
  slug=$(basename "$d")
  # Skip if this slug was fetched in the current run (already indexed by /llmdoc)
  case " $FETCHED_SLUGS " in *" $slug "*) continue ;; esac
  [ -f "$d/COMPACT.md" ] || echo "needs index: $slug"
done
```

For any that need it, **follow the `doc-indexer` skill instructions** (it reads
`~/.llmdocs/docs/<slug>/`, writes `COMPACT.md`, and merges that lib's lines into the global
`LOOKUP.md`). If everything is already indexed, skip to Step 3.

---

## Step 3 — Compile context (lib-context)

Now compile `LIB-CONTEXT.md`. `lib-context` is a **consumer of COMPACT.md** — it reads the
compact tier produced in Step 2 (fast path), falling back to raw docs only when a lib has no
`COMPACT.md`:

```bash
# COMPACT.md fast-path should exist for the libs in this run
for slug in $FETCHED_SLUGS; do
  f="$HOME/.llmdocs/docs/$slug/COMPACT.md"
  test -f "$f" && echo "OK: $f" || echo "MISSING: $f — doc-indexer may have failed"
done
```

Then follow the lib-context skill instructions fully to produce `LIB-CONTEXT.md`.

---

## Step 4 — Refresh the store dashboard

After indexing + compiling, regenerate the self-documenting store dashboard so the new libs
(tiers, pages, token reduction) show up:

```bash
(cd "$LLMDOCS_DIR" && python -m scripts.store_index)
```

---

## Final report

```
doc-prime complete
─────────────────────────────────────
Fetched:   expo-notifications (198p)  ~/.llmdocs/docs/expo-notifications/
           supabase-js (42p)          ~/.llmdocs/docs/supabase-js/
Indexed:   ~/.llmdocs/docs/expo-notifications/COMPACT.md (+ LOOKUP.md lines)
           ~/.llmdocs/docs/supabase-js/COMPACT.md
Compiled:  LIB-CONTEXT.md
Dashboard: store/INDEX.md refreshed
─────────────────────────────────────
Ready. Use @LIB-CONTEXT.md in prompts for accurate API patterns.
```
