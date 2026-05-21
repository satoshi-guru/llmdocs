# llmdocs

Download any documentation site and convert it to clean, LLM-ready markdown files.

Solves the problem of AI tools failing to fetch docs at runtime — run it once, get a local folder of well-structured markdown that any LLM can read without network calls.

## How it works

Four phases run in sequence:

| Phase | What happens |
|-------|-------------|
| **1. Fetch** | HTTP crawl for static sites, or `git clone` for JS/SPA sites with an open-source docs repo |
| **2. Extract** | Strips nav, sidebars, footers, and JS noise — keeps only main content |
| **3. Sort** | Orders pages by URL depth then alphabetically |
| **4. Convert** | Writes one `.md` file per page with YAML frontmatter + an `INDEX.md` |

Runs are resumable — raw HTML is cached locally. Re-running skips already-fetched pages unless you pass `--no-cache`.

## Install

```bash
pip install beautifulsoup4 html2text lxml requests
```

Python 3.10+ required.

## Usage

```bash
# Use a built-in preset
python llmdocs.py --preset discord
python llmdocs.py --preset anthropic
python llmdocs.py --preset openai

# Scrape any URL
python llmdocs.py --url https://docs.example.com --out output/example

# GitHub clone strategy (for React/SPA sites with open-source docs)
python llmdocs.py --url https://example.com \
  --strategy github \
  --github-repo https://github.com/org/docs-repo \
  --out output/example

# Force re-fetch (ignore cache)
python llmdocs.py --preset discord --no-cache

# List presets
python llmdocs.py --list-presets
```

## Output structure

```
output/
  discord/
    developers/
      interactions/
        application-commands.md
        receiving-and-responding.md
      resources/
        channel.md
        guild.md
      ...
    INDEX.md          ← full page list, grouped by section
    _errors.json      ← any fetch failures (if present)
```

Each `.md` file has YAML frontmatter:

```yaml
---
title: "Application Commands"
url: https://discord.com/developers/docs/interactions/application-commands
---

# Application Commands
...
```

## Built-in presets

| Preset | Source | Strategy |
|--------|--------|----------|
| `discord` | github.com/discord/discord-api-docs | GitHub clone |
| `hyperliquid` | hyperliquid-dex.gitbook.io | HTTP crawl |
| `openai` | platform.openai.com/docs | HTTP crawl |
| `anthropic` | docs.anthropic.com | HTTP crawl |

## Adding a custom preset

Edit the `PRESETS` dict in `llmdocs.py`:

```python
"mysite": {
    "name": "My Site Docs",
    "strategy": "http",                         # or "github"
    "url": "https://docs.mysite.com",
    "out": "output/mysite",
    "content_selectors": ["article", "main"],   # CSS selectors for main content
    "skip_selectors": ["nav", "footer"],        # elements to strip
    "path_prefix": "/docs",                     # only crawl URLs under this path
    "max_depth": 4,
    "max_pages": 200,
    "same_domain_only": True,
    "rate_limit": 0.5,                          # seconds between requests
},
```

## Why GitHub clone for some sites?

Sites like Discord's developer docs are React SPAs — a normal HTTP crawl gets an empty shell. When the docs source is open on GitHub as markdown files, cloning the repo is faster, more reliable, and gets the canonical source directly.

## License

MIT
