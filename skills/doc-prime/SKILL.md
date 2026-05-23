---
name: doc-prime
description: Full doc-prime workflow — fetch library docs, compile LIB-CONTEXT.md, index for fast lookup. Run before any implementation sprint. Wraps llmdoc → lib-context → doc-indexer in one command.
argument-hint: "[lib1] [lib2] ... — library names/URLs to fetch. Omit to re-run lib-context + doc-indexer on existing docs only."
allowed-tools: Bash Read Write
---

# doc-prime — Library Doc Workflow

Primes Claude's context with accurate, version-pinned library docs before implementation.
Three steps, always in order: **fetch → compile → index**.

Arguments: $ARGUMENTS

---

## Step 1 — Fetch docs (llmdoc)

For each argument, map known aliases to URLs. Unknown tokens → treat as raw URL.

**Known aliases for this project:**

| Alias | URL |
|-------|-----|
| expo | https://docs.expo.dev |
| expo-notifications | https://docs.expo.dev/versions/latest/sdk/notifications/ |
| expo-router | https://docs.expo.dev/router/introduction/ |
| expo-device | https://docs.expo.dev/versions/latest/sdk/device/ |
| supabase-js | https://supabase.com/docs/reference/javascript/introduction |
| supabase | https://supabase.com/docs/reference/javascript/introduction |
| react-native | https://reactnative.dev/docs/getting-started |

For any alias not listed, check the llmdoc skill aliases, then use as raw URL.

Run each fetch **sequentially** (network-bound). Use a **5-minute timeout** — these fetches
easily exceed the default 120s. Do NOT run as background jobs.

```bash
/home/rootvault/Dokumente/llmdocs/.venv/bin/python \
  /home/rootvault/Dokumente/llmdocs/llmdocs.py \
  --url <URL> \
  --out docs/<slug>/ 2>&1 | tail -5
# timeout: 300000
```

Note: crawlers follow links across the domain — fetching one Expo URL captures the full
docs.expo.dev site. Check `docs/` before re-fetching to avoid duplicate work:

```bash
ls docs/
```

After each fetch: report slug → pages written → path. If a slug already exists and
seems recent (check `ls -la docs/<slug>/`), skip re-fetching and tell the user.

If no arguments given, skip to Step 2.

---

## Step 2 — Compile context (lib-context)

After fetching, invoke the lib-context skill to compile LIB-CONTEXT.md:

```bash
# Check for COMPACT.md fast-path first
ls docs/*/COMPACT.md 2>/dev/null
```

Then follow the lib-context skill instructions fully to produce `LIB-CONTEXT.md`.

---

## Step 3 — Index (doc-indexer)

Run doc-indexer on all newly fetched slugs to create COMPACT.md files for each:

```bash
# doc-indexer reads docs/ and writes docs/<slug>/COMPACT.md
# Follow the doc-indexer skill instructions
```

---

## Final report

```
doc-prime complete
─────────────────────────────────────
Fetched:   expo-notifications (198p)  docs/expo-notifications/
           supabase-js (42p)          docs/supabase-js/
Compiled:  LIB-CONTEXT.md
Indexed:   docs/expo-notifications/COMPACT.md
           docs/supabase-js/COMPACT.md
─────────────────────────────────────
Ready. Use @LIB-CONTEXT.md in prompts for accurate API patterns.
```
