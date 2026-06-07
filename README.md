# llmdocs

**Fetch → convert → compact → serve cheap.** Turn any documentation site into clean,
LLM-ready markdown, then compress it into a reference an agent can read in ~1k tokens
instead of millions — so coding agents stop hallucinating APIs and stop burning context
on raw docs.

The compression is **measured, not asserted**: on FastAPI's docs (395 pages ≈ 3.29M tokens)
the compacted reference is **910 tokens — a 99.97% reduction — while keeping 100% of the key
API signatures** (100% on an LLM-judged usage test). See [`bench/REPORT.md`](bench/REPORT.md).

```bash
python crawler.py --preset discord                  # fetch + convert (no LLM needed)
python crawler.py --url https://docs.example.com --out output/example
```

**Two layers:** `crawler.py` is a universal core — pure crawl + HTML→markdown, no LLM, no
API key. The optional Claude Code skills + agent add the LLM compaction tiers (`COMPACT.md`
read tier + `LOOKUP.md` grep tier) on top. Use just the core, or the whole cycle.

---

## The economics — measured, and it works today

Three ways to give a coding agent a library's docs, measured on this store:

| To answer one doc question | Tokens |
|---|---:|
| Let an agent read the docs (the common way) | ~75,000 (measured avg) |
| Read `COMPACT.md` (the read tier) | ~2,000 |
| One `LOOKUP.md` line (a signature) | **~30** — *≈3,500× cheaper than the agent* |

You pay the agent-sized read **once** — to build the tiers — then every read after is
~30–2,000 tokens, in every repo, forever (break-even is the second read). And the agent
then writes **correct, version-pinned** code from it: no guessing stale-training-data APIs,
no fanning out search agents, no run → error → investigate → fix loop.

**No server, no account, no API key, no quota.** The tiers are plain files in
`~/.llmdocs/docs/` — so the "lookup" is literally a `grep`, and **only the matching line
enters the agent's context**:

```console
$ grep -i "getExpoPushToken" ~/.llmdocs/docs/LOOKUP.md
expo-notifications | getExpoPushTokenAsync(options?) -> ExpoPushToken | needs projectId; await it
```

That one line (~30 tokens) is the entire answer the model reads — not the file, not the page,
not the docs site. In Claude Code the agent runs that `grep` with its **Bash tool** and the
~30-token result is all that lands in context; in any other setup, you (or your shell) grep the
same file. Need usage, not just the signature? Read one tier up — `~/.llmdocs/docs/<lib>/COMPACT.md`
(~1–2k tokens) — instead of the whole docs site (millions).

**The ladder, cheapest first:** `grep LOOKUP.md` (~30) → read `COMPACT.md` (~1–2k) → read one
raw page → read the whole site. The same files serve a plain shell, any agent framework, or a
future MCP `docs-server` — the MCP server is just a tidier doorway to these files, never a
prerequisite.

> "~0 tokens" is shorthand for *near*-zero: a lookup line is ~30 tokens (the text still enters
> context), not literally free — but that's a ~99.9% cut vs reading the raw docs.

---

## How it works

**Three verbs over one local doc store** — and the split is also a *no-LLM / LLM* boundary,
which is why the same store serves a plain Python/MCP client and a Claude Code session equally:

| Verb | What it does | Needs an LLM? | Command |
|------|--------------|:-------------:|---------|
| **FETCH**   | crawl a docs site → markdown in the store | no | `/docs-fetch` (engine: `crawler.py`) |
| **DISTILL** | raw pages → the cheap tiers (`LOOKUP.md` grep, `COMPACT.md` read) | yes | `/docs-distill` |
| **READ**    | answer from the store, cheapest tier first | no, to serve | `/docs-context` · grep · *(MCP `docs-server`, planned)* |

`/docs-prime` runs all three for a sprint in one command. Because **READ** is plain file reads,
a planned stdio **MCP server** (`lookup`/`read`/`page`/`list`) can expose the store to *any*
agent framework — no Claude required on either side. The fetch pipeline in detail:

```
1. Fetch    HTTP crawl  or  git clone (for JS/SPA sites)
2. Extract  strip nav / sidebars / chrome — keep main content only
3. Convert  one .md file per page, YAML frontmatter, INDEX.md
4. Compact  deterministic `min` (no LLM) applied at write time — code preserved
            verbatim. Compaction is an early step, not an afterthought. (--raw to skip.)
```

Compaction comes in tiers, cheapest last to add: **`min`** (above, automatic, lossless-ish,
LLM-free) → **`dense`** (`--compact dense`, aggressive machine-language — strips prose formatting but leaves code, inline `` `code` `` and code blocks verbatim) → **`COMPACT.md`**
(the optional LLM *semantic* distillation, ~99%). The first two need no API key.

Runs are resumable — raw HTML is cached locally. Re-running skips already-fetched pages unless you pass `--no-cache`.

---

## Install

```bash
git clone https://github.com/satoshi-guru/llmdocs
cd llmdocs
pip install -r requirements.txt
```

Python 3.10+, no config file needed.

---

## Usage

```bash
# Built-in preset
python crawler.py --preset discord

# Any URL
python crawler.py --url https://docs.mysite.com --out output/mysite

# GitHub strategy (for React/SPA sites with open-source docs)
python crawler.py \
  --url https://example.com \
  --strategy github \
  --github-repo https://github.com/org/docs-repo \
  --out output/example

# Force re-fetch (clear cache)
python crawler.py --preset discord --no-cache

# List presets
python crawler.py --list-presets
```

---

## Built-in presets

| Preset | Source | Strategy |
|--------|--------|----------|
| `discord` | github.com/discord/discord-api-docs | GitHub clone (React SPA) |
| `hyperliquid` | hyperliquid.gitbook.io/hyperliquid-docs | HTTP crawl (GitBook) |
| `openai` | platform.openai.com/docs | HTTP crawl |
| `anthropic` | docs.anthropic.com | HTTP crawl |

Run `python crawler.py --list-presets` for the live list and where each lands in the store.

---

## Output

Preset runs (no `--out`) land in `~/.llmdocs/docs/<slug>/` — the global append-only store.
Use `--out <path>` for local output. See [Global doc store](#global-doc-store).

```
~/.llmdocs/docs/
  discord/
    INDEX.md                    ← full page list, grouped by section
    developers/
      interactions/
        application-commands.md
        receiving-and-responding.md
      resources/
        channel.md
    _errors.json                ← fetch failures (if any)
```

Each file:

```yaml
---
title: "Application Commands"
url: https://discord.com/developers/docs/interactions/application-commands
---

# Application Commands

...clean markdown content...
```

---

## Documentation

- [Getting started](docs/getting-started.md)
- [Consuming the output (the tier ladder)](docs/consuming.md)
- [HTTP vs GitHub strategy](docs/strategies.md)
- [Built-in presets](docs/presets.md)
- [Adding a custom preset](docs/add-preset.md)

---

## Global doc store

Every fetch lands in **one shared, append-only store** so docs are available to *every*
repo — never siloed per project.

```
~/.llmdocs/
  docs/                         ← the store (symlinked at ~/.claude/docs/)
    <lib>/
      INDEX.md  COMPACT.md  *.md
    LOOKUP.md                   ← global grep table across all libs
    INDEX.md                    ← store dashboard (python -m scripts.store_index)
  MANIFEST.md                   ← index of everything gathered (python -m scripts.manifest)
```

Principles:

- **Global, not per-project.** `/docs-fetch expo` from any repo writes to `~/.llmdocs/docs/expo/`.
  Resolution is global-only — projects no longer keep their own `./docs/`.
- **Append-only.** New fetches *add* to the store; nothing is ever replaced. Versions don't
  matter — the point is to know *everything* about what we use, so findings accumulate.
- **Relocatable.** Set `$LLMDOCS_HOME` to move the store anywhere (default `~/.llmdocs`).
- **Tracked.** `python -m scripts.manifest` regenerates `MANIFEST.md` (the skills do this
  automatically after each fetch/index).

```bash
python -m scripts.manifest        # rebuild the manifest of all gathered docs
cat ~/.llmdocs/MANIFEST.md         # see every library + page count
```

### Store dashboard

`python -m scripts.store_index` (re)generates a one-row-per-library dashboard — tiers present
(Raw/INDEX/COMPACT/LOOKUP), pages, raw vs COMPACT tokens, and the **measured reduction %** — into
`~/.llmdocs/docs/INDEX.md`. It's **generated, so don't hand-edit it**; CI enforces freshness with
`python -m scripts.store_index --check`. The `store/INDEX.md` committed in this repo is a small
**example** built from `store/example/` — your live dashboard reflects your own store.

### Store doctor

`python scripts/store_doctor.py` audits the store for data-quality defects: binary
**asset `.md`** files (PDF/PNG/ZIP/... the crawler decoded as text) and **INDEX
drift** (link-rows vs files on disk). Read-only by default; `--prune-assets`
deletes asset files (guarded), `--check` is a CI gate. INDEX drift is reported,
not auto-fixed — re-fetch the slug with the current engine to regenerate a
truthful INDEX.

### Provenance & versioning

Every fetch records what produced it: the `INDEX.md` header carries `Engine: <sha>`
+ `Fetched: <date>`, and each page's frontmatter carries `fetched_with` /
`fetched_at` (engine id = a `VERSION` file if present, else the engine repo's short
git sha). Use `--archive-existing` to **never overwrite** a slug: before writing, an
existing copy is moved to `<store>/.archive/<slug>@<old-engine>-<timestamp>/`, so
older versions are kept for cross-version comparison. The canonical path
`~/.llmdocs/docs/<slug>/` always holds the current copy (skills read it unchanged);
store-targeted fetches (via `/docs-fetch`) should pass `--archive-existing`.

> Skills run from your project dir, so they locate the engine via **`$LLMDOCS_DIR`** (your clone),
> set by `skills/install.sh`. The store path is **`$LLMDOCS_HOME`** (default `~/.llmdocs`); the
> crawler User-Agent is **`$LLMDOCS_UA`**.

---

## docs-prime — Claude Code Workflow

llmdocs is the fetcher. The **docs-prime workflow** wraps it with Claude Code skills
that turn raw pages into ultra-compact references builders can consume in seconds.

```
/docs-prime expo supabase-js     ← fetch + index + compile in one command
```

Always in this order — **index before compile**, because `docs-context` *consumes* `COMPACT.md`:

```
1. crawler.py    fetch docs → ~/.llmdocs/docs/<lib>/                    (this tool, no LLM)
2. docs-distill   index   → ~/.llmdocs/docs/<lib>/COMPACT.md + LOOKUP.md (the cheap tiers)
3. docs-context   compile → LIB-CONTEXT.md  (sprint summary, reads COMPACT.md)
4. store_index   refresh → ~/.llmdocs/docs/INDEX.md  (the dashboard)
```

All fetched docs land in **one global store** (`~/.llmdocs/docs/`), shared by every
repo — see [Global doc store](#global-doc-store) below.

### Why it matters

A real library's docs are hundreds to thousands of times larger than what an agent needs
to write correct code. `COMPACT.md` distills each library to a ~1k-token reference. These
numbers are **measured by `bench/bench.py`** — token cost, a **recall gate** (every key
signature must survive), and an **LLM-judge** (is each question answerable from the artifact
alone?). Full table + methodology in [`bench/REPORT.md`](bench/REPORT.md):

| Library | Raw docs (~tok) | `COMPACT.md` (tok) | Reduction | Recall | LLM-judge |
|---------|----------------:|-------------------:|----------:|:------:|:---------:|
| FastAPI  | 3,287,065 | 910   | **99.97%** | 100% | 100% |
| Pydantic |   726,298 | 1,264 | **99.83%** | 100% | 100% |

**Honest framing:** the % is vs reading the *entire* raw corpus. The sharper point the
benchmark proves is that COMPACT isn't just smaller — it's **better targeted**: an **~80× larger**
raw-docs skim (≈100k tokens of Pydantic's raw pages) still **dropped 56%** of the key signatures
(and scored 0% on the judge), while the 1.3k-token COMPACT kept **100%**. The grep tier (`LOOKUP.md`) goes further —
~99.9% reduction, answering "does this API exist / what's its signature" in 1–2 tokens.

**Broader sample** across the store (token-only — `chars/4`; recall/judge measured for the
rigorous pair above, run `bench/bench.py` to add it for any lib). Raw-token counts
**exclude binary/asset files** (PDF/PNG/ZIP the crawler decoded as text) and non-text
blobs — only real doc pages are counted, so the ratio reflects genuine content:

| Library | Raw docs (~tok) | `COMPACT.md` (tok) | Reduction |
|---------|----------------:|-------------------:|----------:|
| SQLite       | 1,844,383 | 1,149 | **99.94%** (1605×) |
| TypeScript   |   445,810 | 1,290 | **99.71%** (346×) |
| httpx        |    28,798 | 1,020 | 96.46% (28×) |

The httpx row shows the floor: `COMPACT.md` bottoms out around ~1k tokens, so the win shrinks
for already-small docs — but for substantial libraries it's a consistent **99.9%+** reduction
with no hallucinated API syntax.

### Deterministic compaction (no LLM): `--compact`

`COMPACT.md` above is an LLM *summary*. For a fast, free, **complete** shrink with no model in
the loop, `minify.py` provides two deterministic levels — **code samples are preserved
byte-for-byte** (the bug the original ad-hoc compiler had):

```bash
python crawler.py --compact min   <file|dir|->   # still-valid markdown, smaller
python crawler.py --compact dense <file|dir|->   # machine language, smaller still
python crawler.py --expand        <file.dense.md> # dense -> readable markdown (best-effort)
```

| Level | Output | Valid markdown? | Round-trip | When |
|-------|--------|-----------------|-----------|------|
| `min` | `*.min.md` | yes | n/a (lossless-ish) | **auto-applied** to every fetched page (opt out with `--raw`) |
| `dense` | `*.dense.md` | no (custom) | `--expand`, best-effort | when you want the smallest complete form |

`min` runs automatically in the fetch pipeline, so mechanical compaction is an early step, not a
manual afterthought. Directory input compacts every `*.md` except `INDEX.md`/`COMPACT.md`/`LOOKUP.md`;
`-` reads stdin → stdout. None of this ever overwrites the LLM-generated `COMPACT.md` — the two
tiers coexist (mechanical = complete; semantic = lossy but tiny).

### Install Claude Code skills

```bash
bash skills/install.sh
```

Sets up the global store (`~/.llmdocs/docs/` + a `~/.claude/docs` symlink) and copies
four skills to `~/.claude/skills/`, plus one agent to `~/.claude/agents/`:

| Skill | What it does |
|-------|-------------|
| `/docs-fetch [lib \| url]` | Fetch docs into the global store |
| `/docs-prime [lib1 lib2 ...]` | Full workflow: fetch → index → compile |
| `/docs-context` | Compile `LIB-CONTEXT.md` from the store |
| `/docs-distill [lib]` | Build `COMPACT.md` + `LOOKUP.md` for fast grep lookup |

The agent — **`docs-context`** — is a pre-wave research agent: before a build, it reads the
store and compiles a sprint `LIB-CONTEXT.md` of exact API patterns so builder agents don't
hallucinate library syntax. See [Consuming the output](docs/consuming.md) for how the tiers
feed agents.

> **One-time permission grant.** Claude Code sandboxes `Write`/`Edit` to the current
> project, so a session in repo X can't write to the store by default. Add the store to
> `~/.claude/settings.json` once (the installer prints this):
> ```json
> "permissions": { "additionalDirectories": ["~/.llmdocs", "~/.claude/docs"] }
> ```
> (use absolute paths). `Bash` writes already work via the global `Bash(*)` allow.

### Per-project setup

After installing skills, add your project's library aliases to `skills/docs-fetch/SKILL.md`
(the alias tables) and group them in `skills/docs-fetch/PRESETS.md`:

```markdown
| expo          | https://docs.expo.dev                                      |
| supabase-js   | https://supabase.com/docs/reference/javascript/introduction |
| react-native  | https://reactnative.dev/docs/getting-started               |
```

### Typical sprint workflow

```bash
# 1. Before coding — prime context
/docs-prime expo supabase-js

# 2. During sprint — instant lookup (1–2 tokens, no file read)
grep "getExpoPushToken" ~/.llmdocs/docs/LOOKUP.md

# 3. If library upgraded — refresh
/docs-prime expo --no-cache
/docs-distill expo
```

### Important: fetch timeout

Doc fetches are network-bound and can take 2–5 minutes. In Claude Code:
- Use `timeout: 300000` on the Bash tool call (5 min)
- Do **not** run as background job — inline gives visible progress
- Crawlers follow domain links — fetching one URL may capture the full docs site

---

## License

MIT
