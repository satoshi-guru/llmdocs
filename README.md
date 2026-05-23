# llmdocs

Download any documentation site and convert it to clean, LLM-ready markdown.

Solves the problem of AI tools failing to fetch docs at runtime — run it once, get a local folder of well-structured markdown files that any LLM or agent can read without network calls.

```bash
python llmdocs.py --preset discord
python llmdocs.py --url https://docs.example.com --out output/example
```

---

## How it works

```
1. Fetch    HTTP crawl  or  git clone (for JS/SPA sites)
2. Extract  strip nav / sidebars / chrome — keep main content only
3. Sort     order by URL depth, then alphabetically
4. Convert  one .md file per page, YAML frontmatter, INDEX.md
```

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

| Preset | Source | Strategy | Pages |
|--------|--------|----------|-------|
| `discord` | github.com/discord/discord-api-docs | GitHub clone | ~184 |
| `hyperliquid` | hyperliquid-dex.gitbook.io | HTTP crawl | ~120 |
| `openai` | platform.openai.com/docs | HTTP crawl | ~300 |
| `anthropic` | docs.anthropic.com | HTTP crawl | ~200 |

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

## doc-prime — Claude Code Workflow

llmdocs is the fetcher. The **doc-prime workflow** wraps it with two Claude Code skills
that turn raw pages into ultra-compact references builders can consume in seconds.

```
/doc-prime expo supabase-js     ← fetch + compile + index in one command
```

Three steps, always in this order:

```
1. llmdocs.py    fetch docs → docs/<lib>/   (this tool)
2. lib-context   compile → LIB-CONTEXT.md  (sprint-level API summary)
3. doc-indexer   index   → docs/<lib>/COMPACT.md + docs/LOOKUP.md
```

### Why it matters

| What Claude reads | Tokens |
|-------------------|--------|
| Raw docs folder (50 files) | ~40,000 |
| `docs/<lib>/COMPACT.md` | ~800 |
| `docs/LOOKUP.md` (all libs) | ~2,000 |

**COMPACT.md = 98% token reduction. No more hallucinated API syntax.**

### Install Claude Code skills

```bash
bash skills/install.sh
```

Copies three skills to `~/.claude/skills/`:

| Skill | What it does |
|-------|-------------|
| `/doc-prime [lib1 lib2 ...]` | Full workflow: fetch → compile → index |
| `/lib-context` | Compile `LIB-CONTEXT.md` from existing `docs/` |
| `/doc-indexer [lib]` | Build `COMPACT.md` + `LOOKUP.md` for fast grep lookup |

### Per-project setup

After installing skills, add your project's library aliases to `doc-prime/SKILL.md`:

```markdown
| expo          | https://docs.expo.dev                                      |
| supabase-js   | https://supabase.com/docs/reference/javascript/introduction |
| react-native  | https://reactnative.dev/docs/getting-started               |
```

### Typical sprint workflow

```bash
# 1. Before coding — prime context
/doc-prime expo supabase-js

# 2. During sprint — instant lookup
grep "getExpoPushToken" docs/LOOKUP.md

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
