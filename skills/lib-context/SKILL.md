---
name: lib-context
description: Builds a LIB-CONTEXT.md for a sprint by reading locally fetched library docs (docs/<library>/) and extracting exact API patterns, version-specific syntax, and common mistakes. Prevents builder agents from hallucinating library API syntax. Run before any builder wave.
---

# Library Context Builder

Reads locally available docs (fetched by `/llmdoc`) and compiles exact, version-pinned API patterns into a single context file that builders consume. No network access — all docs come from `docs/` in the current project.

---

## Step 0: Check for COMPACT.md index files (fast path)

Before reading any raw docs, check if `/doc-indexer` has already processed them:

```bash
ls docs/*/COMPACT.md 2>/dev/null
cat docs/LOOKUP.md 2>/dev/null | head -5
```

**If `docs/<lib>/COMPACT.md` exists → read ONLY that file for this library. Skip Step 2 for it.**
COMPACT.md is ~80 lines and replaces reading 50+ raw pages. Token cost: ~800 vs ~40,000.

If no COMPACT.md exists for a library → proceed to Step 2 (read raw docs).
After writing LIB-CONTEXT.md, suggest: "Run `/doc-indexer <lib>` to create COMPACT.md for next time."

---

## Step 1: Identify Required Libraries

Read the sprint PLAN.md to determine which libraries builders will use. Map each to its local doc path:

```bash
ls docs/                  # show available doc directories
ls docs/<library>/        # check specific library
```

Common library → doc path mappings:

| Library | Local Path | Typical Consumers |
|---------|-----------|-------------------|
| FastAPI | `docs/fastapi/` | all Python API routes |
| OpenAI Agents SDK | `docs/openai-agents/` | agent sessions (src/agent/, src/game/agents.py) |
| Anthropic SDK | `docs/anthropic/` | Observer agent, Claude API calls |
| Drizzle ORM | `docs/drizzle-orm/` | gamingstudio TypeScript DB layer |
| Fastify | `docs/fastify/` | gamingstudio API server |
| Zod | `docs/zod/` | gamingstudio input validation |
| pnpm | `docs/pnpm/` | all packages — workspace config |
| Prisma | `docs/prisma/` | db layer, API layer |
| tRPC | `docs/trpc/` | API, web, mobile |
| Auth.js / NextAuth | `docs/nextauth/` | auth, web |
| NativeWind | `docs/nativewind/` | mobile, UI components |
| Expo / Expo Router | `docs/expo/` | mobile |
| Next.js | `docs/nextjs/` | web |
| Vitest | `docs/vitest/` | test configs |
| Tailwind | `docs/tailwind/` | web styling |

For any library not in the list: check `docs/<library-slug>/` where slug is the npm package name or hostname.

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

## Step 3: Check Project CLAUDE.md for Project-Specific Conventions

Before writing the output, read the project's `CLAUDE.md` and extract:
- Custom procedure names or middleware wrappers (e.g., `vaultProcedure`, `protectedProcedure`)
- Project-specific error constant names (e.g., `AppErrors`, `ProjectErrors`)
- Hard security invariants builders must respect
- Naming conventions that differ from library defaults

These go into a **Project Conventions** section of LIB-CONTEXT.md so builders know the project's layer on top of the raw library patterns.

---

## Step 4: Write LIB-CONTEXT.md

Write to `{SPRINT_DIR}/LIB-CONTEXT.md`:

```markdown
# Library Context: <SPRINT>
Generated from locally fetched docs. Builders: use these exact patterns.

## <Library Name> (v<version>)
Source: docs/<library>/

### Correct Patterns
[Copy exact syntax from docs]

### Common Mistakes (from docs)
[What the docs explicitly say NOT to do]

### Version-Specific: What Changed from v<N-1>
[Breaking changes relevant to this sprint]

---

## Project Conventions (from CLAUDE.md)
[Project-specific wrappers, error constants, invariants that override or extend library defaults]
```

---

## Embedded Fallbacks

Use these when a library's docs haven't been fetched yet AND no COMPACT.md exists.
Builders MUST use the project's pinned versions — check `pyproject.toml` or `package.json`.

---

### FastAPI (>=0.135)

**Route definition:**
```python
from fastapi import APIRouter, HTTPException, Body, Query, Depends
router = APIRouter()

@router.get("/path", response_model=MyModel)
async def my_handler(id: int, db = Depends(get_db)) -> dict:
    ...

@router.post("/path", status_code=201)
async def create(body: dict = Body(...)) -> dict:
    field = body.get("field")
    if not field:
        raise HTTPException(status_code=400, detail="field required")
    return {"ok": True}
```

**Lifespan (>=0.93, replaces deprecated `@app.on_event`):**
```python
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown
app = FastAPI(lifespan=lifespan)
```

**⚠ Breaking:** `@app.on_event("startup")` deprecated since 0.93 — use lifespan.
**⚠ Game rule:** New game routes go in `game_isekai_routes.py`, NOT `game_routes.py`.

---

### OpenAI Agents SDK (openai-agents >=0.10)

**Agent definition:**
```python
from agents import Agent, Runner, function_tool

@function_tool
def my_tool(param: str) -> str:
    """Tool description shown to model."""
    return result

agent = Agent(
    name="MyAgent",
    instructions="You are...",
    tools=[my_tool],
    model="gpt-4o-mini",
)

result = await Runner.run(agent, input="user message")
print(result.final_output)
```

**⚠ Breaking from early versions:** `Runner.run()` is async. `function_tool` decorator — docstring is the tool description. `result.final_output` not `result.output`.

---

### Anthropic SDK (>=0.50)

**Messages API:**
```python
import anthropic
client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

message = client.messages.create(
    model="claude-haiku-4-5-20251001",   # cheapest; use sonnet for quality
    max_tokens=1024,
    messages=[{"role": "user", "content": "prompt here"}]
)
print(message.content[0].text)
```

**With system prompt:**
```python
message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": user_input}]
)
```

**Latest models (2026-05):** `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`
**⚠ Never hardcode old model IDs** — always check GAME_STATELOG.md or CLAUDE.md for current model list.

---

### Drizzle ORM (>=0.30, Postgres via drizzle-orm/postgres-js)

**Select:**
```typescript
import { db } from '@gamingstudio/database'
import { eq, desc, sql } from 'drizzle-orm'
import { myTable } from '@gamingstudio/database'

const rows = await db.select().from(myTable).where(eq(myTable.id, id))
const top = await db.select().from(myTable).orderBy(desc(myTable.score)).limit(10)
```

**Insert + upsert:**
```typescript
await db.insert(myTable).values({ col: val })
await db.insert(myTable)
  .values({ season: 1, playerId: id, xp: 0 })
  .onConflictDoUpdate({
    target: [myTable.season, myTable.playerId],
    set: { xp: sql`${myTable.xp} + ${xp}`, updatedAt: new Date() },
  })
```

**Raw SQL (for complex queries):**
```typescript
const result = await db.execute(sql`
  SELECT player_id, SUM(xp_earned) as total
  FROM ${myTable}
  WHERE season = ${CURRENT_SEASON}
  GROUP BY player_id
`)
const rows = result.rows as Record<string, unknown>[]
```

**⚠ `result.rows` is typed as `unknown[]` from raw execute** — cast to `Record<string, unknown>[]`.

---

### Fastify (^4.24)

**Route handler:**
```typescript
import Fastify from 'fastify'
const app = Fastify({ logger: true })

app.get('/path', async (request, reply) => {
  const { id } = request.params as { id: string }
  return { data: result }   // auto-serialized as JSON
})

app.post('/path', async (request, reply) => {
  const body = request.body as { field: string }
  reply.status(201).send({ ok: true })
})

await app.listen({ port: 3000 })
```

**JWT plugin:**
```typescript
await app.register(require('@fastify/jwt'), { secret: process.env.JWT_SECRET })
app.addHook('onRequest', async (request, reply) => {
  await request.jwtVerify()
})
```

---

### tRPC v11

**Router definition:**
```typescript
import { initTRPC, TRPCError } from '@trpc/server'
import type { Context } from './context'

const t = initTRPC.context<Context>().create()

export const router = t.router
export const publicProcedure = t.procedure
export const protectedProcedure = t.procedure.use(authMiddleware)
```

**Procedure syntax (v11 — NOT v10):**
```typescript
// Query
myProcedure: protectedProcedure
  .input(z.object({ id: z.string() }))
  .query(async ({ ctx, input }) => {
    return data
  }),

// Mutation
createEntry: protectedProcedure
  .input(MyInputSchema)
  .mutation(async ({ ctx, input }) => {
    return db.model.create({ data: input })
  }),
```

**What changed from v10:** `createRouter()` → `t.router()`. Middleware is `.use()` not `.middleware()`. Context destructuring: `({ ctx, input })` not `(opts)`.

---

### Prisma v5+

**Query patterns:**
```typescript
// findUniqueOrThrow (throws if not found — no null check needed)
const record = await prisma.model.findUniqueOrThrow({ where: { id } })

// findFirst
const entry = await prisma.model.findFirst({
  where: { userId, type },
  include: { user: true },
})

// Transaction
await prisma.$transaction([
  prisma.model.create({ data: a }),
  prisma.model.update({ where: { id }, data: b }),
])
```

**What changed from v4:** `findUnique` returns `null` (not throws). Use `findUniqueOrThrow` when null is an error. `prisma.model.count()` returns `number` (not BigInt).

---

### pnpm v11

**Internal workspace deps — always `workspace:*`:**
```json
{
  "dependencies": {
    "@org/package": "workspace:*"
  }
}
```

**`allowBuilds` in `pnpm-workspace.yaml` (NOT in `package.json` `pnpm` field — ignored in v11):**
```yaml
allowBuilds:
  "@prisma/client": true
  prisma: true
  esbuild: true
```

**What changed from v10:** `onlyBuiltDependencies` → `allowBuilds`. The `pnpm` field in `package.json` is silently ignored in v11 — all settings go in `pnpm-workspace.yaml`.

---

### Auth.js v5 / NextAuth v5

**Session access in server components (v5 — NOT v4):**
```typescript
// CORRECT — v5
import { auth } from '@/lib/auth'
const session = await auth()
if (!session?.user?.id) redirect('/login')

// WRONG — v4 pattern, broken in v5
import { getServerSession } from 'next-auth'
const session = await getServerSession(authOptions)
```

**What changed from v4:** `getServerSession(authOptions)` → `auth()`. Config is in `auth.config.ts`, not `[...nextauth]/route.ts`.

---

### NativeWind v4

**className on React Native components (v4 — NOT v3):**
```typescript
// nativewind-env.d.ts must exist:
// /// <reference types="nativewind/types" />

import { View, Text } from 'react-native'

// CORRECT — direct className, no styled() wrapper
<View className="flex-1 bg-white p-4">
  <Text className="text-lg font-semibold">Hello</Text>
</View>

// WRONG — v3 pattern, not used in v4
const StyledView = styled(View)
```

**What changed from v3:** No more `styled()` wrapper. Direct `className` on all RN components. `withNativeWind` wraps metro config, not babel. `darkMode: 'class'` in tailwind config.

---

### Expo Router (SDK 52+)

**File structure maps to routes:**
```
app/
  (group)/           ← layout group, not in URL
    _layout.tsx      ← layout for group
    screen.tsx       ← /screen
  (tabs)/
    _layout.tsx      ← tab layout
    index.tsx        ← / (first tab)
```

**Navigation:**
```typescript
import { router } from 'expo-router'

router.push('/profile')
router.replace('/(auth)/login')

import { Link } from 'expo-router'
<Link href="/profile">Go to profile</Link>

// WRONG — never use react-navigation directly
navigation.navigate('Profile')
```

---

## Missing Docs Notice

If a library's docs are not in `docs/<library>/`, add to LIB-CONTEXT.md:

```
⚠ docs/<library>/ not found. Using embedded fallback patterns.
Run `/llmdoc <library>` to fetch current docs and improve accuracy.
```

After writing LIB-CONTEXT.md, report:
```
LIB-CONTEXT.md written to {SPRINT_DIR}/LIB-CONTEXT.md
Libraries covered (from docs/): {list}
Missing (used embedded fallback): {list or "none"}
Fetch to improve: /llmdoc {library} for each missing
```
