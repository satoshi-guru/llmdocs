# llmdocs

**Fetch → convert → compact → serve cheap.** Turn any documentation site into clean,
LLM-ready markdown, then compress it into a reference an agent can read in ~1k tokens
instead of millions — so coding agents stop hallucinating APIs and stop burning context
on raw docs.

The compression is **measured, not asserted**: on FastAPI's docs (395 pages ≈ 3.29M tokens)
the compacted reference is **910 tokens — a 99.97% reduction — while keeping 100% of the key
API signatures** (100% on an LLM-judged usage test). See [`bench/REPORT.md`](bench/REPORT.md).

```bash
python llmdocs.py --preset discord                  # fetch + convert (no LLM needed)
python llmdocs.py --url https://docs.example.com --out output/example
```

**Two layers:** `llmdocs.py` is a universal core — pure crawl + HTML→markdown, no LLM, no
API key. The optional Claude Code skills + agent add the LLM compaction tiers (`COMPACT.md`
read tier + `LOOKUP.md` grep tier) on top. Use just the core, or the whole cycle.

---

## How it works

```
1. Fetch    HTTP crawl  or  git clone (for JS/SPA sites)
2. Extract  strip nav / sidebars / chrome — keep main content only
3. Convert  one .md file per page, YAML frontmatter, INDEX.md
4. Compact  deterministic `min` (no LLM) applied at write time — code preserved
            verbatim. Compaction is an early step, not an afterthought. (--raw to skip.)
```

Compaction comes in tiers, cheapest last to add: **`min`** (above, automatic, lossless-ish,
LLM-free) → **`dense`** (`--compact dense`, aggressive machine-language) → **`COMPACT.md`**
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
python llmdocs.py --preset discord

# Any URL
python llmdocs.py --url https://docs.mysite.com --out output/mysite

# GitHub strategy (for React/SPA sites with open-source docs)
python llmdocs.py \
  --url https://example.com \
  --strategy github \
  --github-repo https://github.com/org/docs-repo \
  --out output/example

# Force re-fetch (clear cache)
python llmdocs.py --preset discord --no-cache

# List presets
python llmdocs.py --list-presets
```

---

## Built-in presets

| Preset | Source | Strategy |
|--------|--------|----------|
| `discord` | github.com/discord/discord-api-docs | GitHub clone (React SPA) |
| `hyperliquid` | hyperliquid.gitbook.io/hyperliquid-docs | HTTP crawl (GitBook) |
| `example-site` | docs.example-site.com | HTTP crawl |
| `openai` | platform.openai.com/docs | HTTP crawl |
| `anthropic` | docs.anthropic.com | HTTP crawl |

Run `python llmdocs.py --list-presets` for the live list and where each lands in the store.

---

## Output

```
output/
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

- **Global, not per-project.** `/llmdoc expo` from any repo writes to `~/.llmdocs/docs/expo/`.
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

> Skills run from your project dir, so they locate the engine via **`$LLMDOCS_DIR`** (your clone),
> set by `skills/install.sh`. The store path is **`$LLMDOCS_HOME`** (default `~/.llmdocs`); the
> crawler User-Agent is **`$LLMDOCS_UA`**.

---

## doc-prime — Claude Code Workflow

llmdocs is the fetcher. The **doc-prime workflow** wraps it with Claude Code skills
that turn raw pages into ultra-compact references builders can consume in seconds.

```
/doc-prime expo supabase-js     ← fetch + compile + index in one command
```

Always in this order — **index before compile**, because `lib-context` *consumes* `COMPACT.md`:

```
1. llmdocs.py    fetch docs → ~/.llmdocs/docs/<lib>/                    (this tool, no LLM)
2. doc-indexer   index   → ~/.llmdocs/docs/<lib>/COMPACT.md + LOOKUP.md (the cheap tiers)
3. lib-context   compile → LIB-CONTEXT.md  (sprint summary, reads COMPACT.md)
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
benchmark proves is that COMPACT isn't just smaller — it's **better targeted**: a same-budget
*skim* of the raw docs dropped **56%** of Pydantic's key signatures (and scored 0% on the
judge), while the 1.3k-token COMPACT kept **100%**. The grep tier (`LOOKUP.md`) goes further —
~99.9% reduction, answering "does this API exist / what's its signature" in 1–2 tokens.

**Broader sample** across the store (token-only — `chars/4`; recall/judge measured for the
rigorous pair above, run `bench/bench.py` to add it for any lib):

| Library | Raw docs (~tok) | `COMPACT.md` (tok) | Reduction |
|---------|----------------:|-------------------:|----------:|
| SQLite       | 1,844,815 | 1,149 | **99.94%** (1605×) |
| TypeScript   | 1,461,059 | 1,290 | **99.91%** (1132×) |
| httpx        |    28,798 | 1,020 | 96.46% (28×) |

The httpx row shows the floor: `COMPACT.md` bottoms out around ~1k tokens, so the win shrinks
for already-small docs — but for substantial libraries it's a consistent **99.9%+** reduction
with no hallucinated API syntax.

### Deterministic compaction (no LLM): `--compact`

`COMPACT.md` above is an LLM *summary*. For a fast, free, **complete** shrink with no model in
the loop, `compact.py` provides two deterministic levels — **code samples are preserved
byte-for-byte** (the bug the original ad-hoc compiler had):

```bash
python llmdocs.py --compact min   <file|dir|->   # still-valid markdown, smaller
python llmdocs.py --compact dense <file|dir|->   # machine language, smaller still
python llmdocs.py --expand        <file.dense.md> # dense -> readable markdown (best-effort)
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
four skills to `~/.claude/skills/`:

| Skill | What it does |
|-------|-------------|
| `/llmdoc [lib \| url]` | Fetch docs into the global store |
| `/doc-prime [lib1 lib2 ...]` | Full workflow: fetch → compile → index |
| `/lib-context` | Compile `LIB-CONTEXT.md` from the store |
| `/doc-indexer [lib]` | Build `COMPACT.md` + `LOOKUP.md` for fast grep lookup |

> **One-time permission grant.** Claude Code sandboxes `Write`/`Edit` to the current
> project, so a session in repo X can't write to the store by default. Add the store to
> `~/.claude/settings.json` once (the installer prints this):
> ```json
> "permissions": { "additionalDirectories": ["~/.llmdocs", "~/.claude/docs"] }
> ```
> (use absolute paths). `Bash` writes already work via the global `Bash(*)` allow.

### Per-project setup

After installing skills, add your project's library aliases to `skills/llmdoc/SKILL.md`
(the alias tables) and group them in `skills/llmdoc/PRESETS.md`:

```markdown
| expo          | https://docs.expo.dev                                      |
| supabase-js   | https://supabase.com/docs/reference/javascript/introduction |
| react-native  | https://reactnative.dev/docs/getting-started               |
```

### Typical sprint workflow

```bash
# 1. Before coding — prime context
/doc-prime expo supabase-js

# 2. During sprint — instant lookup (1–2 tokens, no file read)
grep "getExpoPushToken" ~/.llmdocs/docs/LOOKUP.md

# 3. If library upgraded — refresh
/doc-prime expo --no-cache
/doc-indexer expo
```

### Important: fetch timeout

Doc fetches are network-bound and can take 2–5 minutes. In Claude Code:
- Use `timeout: 300000` on the Bash tool call (5 min)
- Do **not** run as background job — inline gives visible progress
- Crawlers follow domain links — fetching one URL may capture the full docs site

---

## License

MIT
