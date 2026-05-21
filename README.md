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

## License

MIT
