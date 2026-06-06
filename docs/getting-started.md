# Getting Started

## Install

```bash
git clone https://github.com/satoshi-guru/llmdocs
cd llmdocs
pip install -r requirements.txt
```

Python 3.10+ required. No config file needed.

## Your first run

```bash
# Use a built-in preset (fastest — no URL needed)
python llmdocs.py --preset discord

# Scrape any docs URL
python llmdocs.py --url https://docs.example.com --out output/example
```

That's it. Results land in `output/discord/` (or whatever `--out` you set).

## What you get

One `.md` file per page, organised to mirror the site's URL structure:

```
output/
  discord/
    INDEX.md                              ← full page list
    developers/
      interactions/
        application-commands.md
        receiving-and-responding.md
      resources/
        channel.md
        guild.md
```

Every file has YAML frontmatter so any LLM or RAG pipeline can consume it directly:

```yaml
---
title: "Application Commands"
url: https://discord.com/developers/docs/interactions/application-commands
---

# Application Commands
...
```

## Re-running

Runs are resumable. Raw HTML is cached in `output/<name>/_raw_html/`. Re-running the same command skips already-fetched pages.

To force a full re-fetch:

```bash
python llmdocs.py --preset discord --no-cache
```

## Next steps

- [Presets](presets.md) — built-in site configs
- [HTTP vs GitHub strategy](strategies.md) — when to use which
- [Adding a custom preset](add-preset.md) — add your own site
