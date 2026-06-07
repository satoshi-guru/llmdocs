---
name: lib-context
description: Builds a LIB-CONTEXT.md for a sprint by reading locally fetched library docs (~/.llmdocs/docs/<library>/) and extracting exact API patterns, version-specific syntax, and common mistakes. Prevents builder agents from hallucinating library API syntax. Run before any builder wave.
allowed-tools: Bash Read Write
---

# Library Context Builder

Reads locally available docs (fetched by `/llmdoc`) and compiles exact API patterns into a single context file that builders consume. No network access — all docs come from the **global store** `~/.llmdocs/docs/` (symlinked at `~/.claude/docs/`), shared across every repo. Resolution is **global-only**: a library lives in the store or it doesn't; projects don't keep their own `./docs/` copies. Versions don't matter — the store accumulates everything we know about a library, and new fetches add to it.

---

## Step 0: Check for COMPACT.md index files (fast path)

Before reading any raw docs, check if `/doc-indexer` has already processed them:

```bash
ls ~/.llmdocs/docs/*/COMPACT.md 2>/dev/null
test -s ~/.llmdocs/docs/LOOKUP.md \
  && echo "LOOKUP.md present ($(wc -l < ~/.llmdocs/docs/LOOKUP.md) lines)" \
  || echo "LOOKUP.md absent or empty"
```

**If `~/.llmdocs/docs/<lib>/COMPACT.md` exists → read ONLY that file for this library. Skip Step 2 for it.**
COMPACT.md is ~80–120 lines and replaces reading hundreds of raw pages — a measured
99.8–99.97% token reduction (see `bench/REPORT.md`).

If no COMPACT.md exists for a library → proceed to Step 2 (read raw docs).
After writing LIB-CONTEXT.md, suggest: "Run `/doc-indexer <lib>` to create COMPACT.md for next time."

---

## Step 1: Identify Required Libraries

Determine which libraries to cover: if a `PLAN.md` exists in the working directory, read it to
see what the builders will use; otherwise use the libraries the user named (or, with no
arguments, every lib present in `~/.llmdocs/docs/`). Map each to its local doc path:

```bash
ls ~/.llmdocs/docs/                  # show available doc directories
ls ~/.llmdocs/docs/<library>/        # check specific library
```

Common library → doc path mappings:

| Library | Local Path | Typical Consumers |
|---------|-----------|-------------------|
| FastAPI | `~/.llmdocs/docs/fastapi/` | all Python API routes |
| OpenAI Agents SDK | `~/.llmdocs/docs/openai-agents/` | agent sessions |
| Anthropic SDK | `~/.llmdocs/docs/anthropic/` | Claude API calls |
| Drizzle ORM | `~/.llmdocs/docs/drizzle-orm/` | TypeScript DB layer |
| Fastify | `~/.llmdocs/docs/fastify/` | API server |
| Zod | `~/.llmdocs/docs/zod/` | input validation |
| pnpm | `~/.llmdocs/docs/pnpm/` | all packages — workspace config |
| Prisma | `~/.llmdocs/docs/prisma/` | db layer, API layer |
| tRPC | `~/.llmdocs/docs/trpc/` | API, web, mobile |
| Auth.js / NextAuth | `~/.llmdocs/docs/nextauth/` | auth, web |
| NativeWind | `~/.llmdocs/docs/nativewind/` | mobile, UI components |
| Expo / Expo Router | `~/.llmdocs/docs/expo/` | mobile |
| Next.js | `~/.llmdocs/docs/nextjs/` | web |
| Vitest | `~/.llmdocs/docs/vitest/` | test configs |
| Tailwind | `~/.llmdocs/docs/tailwind/` | web styling |

For any library not in the list: check `~/.llmdocs/docs/<library-slug>/` where slug is the npm package name or hostname.

---

## Step 2: Read and Extract

For each available doc directory, read only files relevant to the sprint. Priority order:

| Library | Read first | Skip |
|---------|-----------|------|
| pnpm | workspace_yaml, settings | translations (es/, fr/, zh/, etc.) |
| prisma | schema, queries, relations | deployment, studio, data platform |
| trpc | router, procedures, context, middleware | adapters not in use |
| nextauth / authjs | configuration, session, middleware | providers not in use |
| nativewind | getting-started, styling, configuration | v2/v3 migration guides |
| expo / expo-router | routing, layouts, navigation | api routes if not used |
| tailwind | core concepts, utilities used | plugins not in use |
| zod | primitives, transforms, validation | rarely-used schema types |
| vitest | configuration, test api | browser mode if not used |

**Extract only:**
- Function signatures with exact parameter types (copy verbatim)
- Breaking changes from the prior major version
- Explicit doc warnings ("do not use X", "this was removed in vN")
- Complete, runnable code examples (not snippets with `...`)

Do NOT paraphrase. Copy exact syntax. Paraphrasing introduces hallucination.

---

## Step 3: Check Project CLAUDE.md for Project-Specific Conventions (conditional)

**Only if `CLAUDE.md` exists in the current working directory** (`test -f CLAUDE.md`), read it
and extract:
- Custom procedure names or middleware wrappers (e.g., `vaultProcedure`, `protectedProcedure`)
- Project-specific error constant names (e.g., `AppErrors`, `ProjectErrors`)
- Hard security invariants builders must respect
- Naming conventions that differ from library defaults

These go into a **Project Conventions** section of LIB-CONTEXT.md so builders know
the project's layer on top of the raw library patterns.

**If no `CLAUDE.md` exists** — skip this step entirely. Omit the "Project Conventions" section
from LIB-CONTEXT.md output. This is normal for external users and fresh checkouts.

---

## Step 4: Write LIB-CONTEXT.md

Write to `{SPRINT_DIR}/LIB-CONTEXT.md` (use the sprint dir if one was given; otherwise default
to `./LIB-CONTEXT.md` in the current working directory):

```markdown
# Library Context: <SPRINT>
Generated from locally fetched docs. Builders: use these exact patterns.

## <Library Name> (v<version>)
Source: ~/.llmdocs/docs/<library>/

### Correct Patterns
[Copy exact syntax from docs]

### Common Mistakes (from docs)
[What the docs explicitly say NOT to do]

### Version-Specific: What Changed from v<N-1>
[Breaking changes relevant to this sprint]

---

## Project Conventions (from CLAUDE.md)
[Omit this section entirely if the project has no CLAUDE.md]
[Project-specific wrappers, error constants, invariants that override or extend library defaults]
```

---

## No embedded fallbacks (consumer-only)

This skill does **not** carry hardcoded API snippets. It is a *consumer* of the doc
store: read `COMPACT.md` (Step 0) when present, otherwise the raw docs (Step 2). If a
library is missing from `~/.llmdocs/docs/`, **fetch it first** with `/llmdoc <library>`
and `/doc-indexer <library>` — never guess the API from memory.

---

## Missing Docs Notice

If a library's docs are not in `~/.llmdocs/docs/<library>/`, add to LIB-CONTEXT.md:

```
⚠ ~/.llmdocs/docs/<library>/ not found — no patterns emitted for this library.
Run `/llmdoc <library>` (then `/doc-indexer <library>`) to fetch current docs, and re-run.
```

After writing LIB-CONTEXT.md, report:
```
LIB-CONTEXT.md written to {SPRINT_DIR or ./}LIB-CONTEXT.md
Libraries covered (from ~/.llmdocs/docs/): {list}
Missing (not in store — no patterns emitted): {list or "none"}
Fetch to fix: /llmdoc {library} for each missing
```
