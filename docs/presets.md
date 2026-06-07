# Built-in Presets

Run `python llmdocs.py --list-presets` to see all presets with their current output paths.

All presets write to `~/.llmdocs/docs/<preset>/` by default (the global store). Override
with `--out <path>` for a single run.

---

## discord

| Field | Value |
|-------|-------|
| Strategy | GitHub clone |
| Source | github.com/discord/discord-api-docs |
| Coverage | ~184 pages — interactions, components, resources, gateway, OAuth2, monetization |

Discord's developer docs are a React SPA. This preset clones the official source repo and reads the markdown directly — faster and more complete than any crawl.

```bash
python llmdocs.py --preset discord
```

---

## hyperliquid

| Field | Value |
|-------|-------|
| Strategy | HTTP crawl |
| Source | hyperliquid-dex.gitbook.io/hyperliquid-docs |
| Coverage | API reference, order types, websocket, SDK |

GitBook renders server-side HTML so HTTP crawl works. If the URL has changed (GitBook migrations are common), update the `url` field in the preset or pass `--url` directly.

```bash
python llmdocs.py --preset hyperliquid
```

---


## openai

| Field | Value |
|-------|-------|
| Strategy | HTTP crawl |
| Source | platform.openai.com/docs |
| Coverage | API reference, models, assistants, fine-tuning, embeddings |

```bash
python llmdocs.py --preset openai
```

---

## anthropic

| Field | Value |
|-------|-------|
| Strategy | HTTP crawl |
| Source | docs.anthropic.com/en/docs |
| Coverage | Claude API, tool use, prompt caching, vision, models |

```bash
python llmdocs.py --preset anthropic
```

---

## Overriding preset output path

```bash
python llmdocs.py --preset discord --out ~/my-project/docs/discord
```

The `--out` flag overrides only the output directory. All other preset settings (strategy, selectors, depth) stay the same.
