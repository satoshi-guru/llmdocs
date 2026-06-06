---
name: llmdoc
description: Fetch the docs for a specific library, framework, or URL and save them as LLM-ready markdown in the GLOBAL store (~/.llmdocs/docs/<slug>/), shared by every repo. Use whenever the user wants to grab, pull, mirror, save, or refresh docs for a named library/API — e.g. "grab the supabase-js docs", "fetch the discord developer docs", "pull httpx before I refactor". Always use BEFORE writing config or code against an unfamiliar or recently-changed library API, and immediately when a first install/build/run attempt fails — don't guess or retry with workarounds first. Routes engine presets (Discord SPA, Hyperliquid, etc.) via --preset. This is the quick single-library/single-URL fetch; for full pre-sprint prep across several libraries use /doc-prime.
argument-hint: "[alias | <url>] — see presets table below"
allowed-tools: Bash Read WebFetch WebSearch
---

Fetch documentation and save it to the **global append-only doc store** at
`~/.llmdocs/docs/<slug>/` (symlinked at `~/.claude/docs/`). Docs land there once and
are available to **every** repo — never siloed per project. Versions never matter:
new fetches **add** to the store, they never replace what's already there.

Arguments: $ARGUMENTS

**Note:** Reading docs already in the store is a plain file read (use the `Read` tool directly on `~/.llmdocs/docs/<lib>/`), not a fetch. Use this skill only when you need to pull new or refreshed docs from the network.

## Common presets

### Frontend / React Native
| Alias | Fetches |
|-------|---------|
| expo | https://docs.expo.dev |
| expo-router | https://docs.expo.dev/router/introduction/ |
| expo-notifications | https://docs.expo.dev/versions/latest/sdk/notifications/ |
| expo-device | https://docs.expo.dev/versions/latest/sdk/device/ |
| react-native | https://reactnative.dev/docs/getting-started |
| react-navigation | https://reactnavigation.org/docs/getting-started |
| reanimated | https://docs.swmansion.com/react-native-reanimated/ |
| nativewind | https://www.nativewind.dev/docs |
| supabase | https://supabase.com/docs/reference/javascript/introduction |
| supabase-js | https://supabase.com/docs/reference/javascript/introduction |
| tailwind | https://tailwindcss.com/docs |
| typescript | https://www.typescriptlang.org/docs/ |
| zod | https://zod.dev |
| nextauth | https://authjs.dev/getting-started |
| trpc | https://trpc.io/docs |
| turbo | https://turbo.build/repo/docs |
| pnpm | https://pnpm.io/pnpm-workspace_yaml + https://pnpm.io/settings |
| vitest | https://vitest.dev/guide |
| prisma | https://www.prisma.io/docs |

### Python backend
| Alias | Fetches |
|-------|---------|
| python | https://docs.python.org/3/ |
| asyncio | https://docs.python.org/3/library/asyncio.html |
| fastapi | https://fastapi.tiangolo.com/reference/ |
| pydantic | https://pydantic.dev/docs/validation/latest/get-started/ |
| aiohttp | https://docs.aiohttp.org/en/stable/ |
| httpx | https://www.python-httpx.org/ |
| uvicorn | https://www.uvicorn.org/ |
| websockets | https://websockets.readthedocs.io/en/stable/ |
| pytest | https://docs.pytest.org/en/stable/ |
| ruff | https://docs.astral.sh/ruff/ |
| scikit-learn | https://scikit-learn.org/stable/ |
| sentence-transformers | https://sbert.net/ |
| pygithub | https://pygithub.readthedocs.io/en/stable/ |

### Discord
| Alias | Fetches |
|-------|---------|
| discordpy | https://discordpy.readthedocs.io/en/stable/ |
| discord / discord-api | **engine preset** → `--preset discord` (React SPA → GitHub strategy; a plain `--url` fetches 0 pages) |

### AI / LLM / Agents
| Alias | Fetches |
|-------|---------|
| anthropic | **engine preset** → `--preset anthropic` (crawls `/en` — guides + API reference) |
| openai-agents | https://openai.github.io/openai-agents-python/ |
| openai | **engine preset** → `--preset openai` (crawls `/docs` — guides + API reference) |
| mcp | https://modelcontextprotocol.io/docs/ |

### Crypto / Trading
| Alias | Fetches |
|-------|---------|
| hyperliquid | **engine preset** → `--preset hyperliquid` (tuned GitBook selectors + path prefix) |
| example-site | **engine preset** → `--preset example-site` (third-party Hyperliquid analytics — fills, trades, vault data) |
| ethers | https://docs.ethers.org/v6/ |
| viem | https://viem.sh/docs/getting-started |

### Infrastructure / Data
| Alias | Fetches |
|-------|---------|
| sqlite | https://www.sqlite.org/docs.html |
| notion | https://developers.notion.com/reference/intro |
| git | https://git-scm.com/docs |
| systemd | https://www.freedesktop.org/software/systemd/man/latest/ |
| bash | https://www.gnu.org/software/bash/manual/bash.html |
| nginx | https://nginx.org/en/docs/ |

For any alias not listed above, treat it as a raw URL.

## Project preset groups

For one-command per-project refresh, use `preset:<group>`. Groups live in `PRESETS.md` under **Project Preset Groups** — they expand to a list of aliases.

Combine groups with `+` for cross-stack tasks: `/llmdoc preset:web-frontend+python-api`. Libs are deduped before fetching.

Examples:
- `/llmdoc preset:web-frontend` — full frontend doc refresh (react-native + tailwind + typescript + zod)
- `/llmdoc preset:python-api` — full Python API stack (fastapi + pydantic + httpx + pytest)
- `/llmdoc preset:web-frontend+python-api` — fusion for a full-stack sprint
- `/llmdoc expo supabase` — ad-hoc, no preset group

## Task

1. **Parse $ARGUMENTS** — resolve each token in THIS ORDER (first match wins). The order
   matters because some sites can only be fetched correctly via an engine preset:
   1. **Engine preset name** — one of the names from
      `… llmdocs.py --list-presets` (currently `discord`, `hyperliquid`, `example-site`,
      `openai`, `anthropic`; always run `--list-presets` for the live list). Fetch with
      `--preset <name>`. The preset carries the per-site **strategy** and tuned crawl config:
      e.g. `discord` uses the GitHub strategy because the Discord docs are a React SPA — a
      plain `--url` crawl returns 0 usable pages. Engine presets are the curated, authoritative
      definition for these sites, so they win over an alias of the same name.
   2. **`preset:<group>`** (or `preset:<g1>+<g2>+...`) → expand to the group's alias list (see
      PRESETS.md "Project Preset Groups"). Dedupe across groups, then resolve each resulting
      token by this same 1→4 order (so a group member that names an engine preset still routes
      via `--preset`).
   3. **Known alias** from the tables above → fetch with `--url <mapped-url>` (default HTTP).
   4. **Anything else** → treat the token as a raw URL → `--url <token>`.
2. Build the command per token using the flag chosen above — `--preset` for case 1, `--url`
   for cases 3–4.
3. Run the fetcher for each target.

   **Case 1 (engine preset):**
   ```bash
   python "$LLMDOCS_DIR/llmdocs.py" --preset <name>
   ```
   (`$LLMDOCS_DIR` = your llmdocs clone — `install.sh` records it; defaults assume the engine
   is on your `PATH`/clone. Run from anywhere.)
   No `--out` needed: the engine redirects preset output to `~/.llmdocs/docs/<name>/` with a
   clean slug automatically. Pass `--out ~/.llmdocs/docs/<slug>/` only to force a custom slug.

   **Cases 3–4 (alias / raw URL):**
   ```bash
   python "$LLMDOCS_DIR/llmdocs.py" \
     --url <URL> \
     --workers 4 --rate-limit 0.25 \
     --out ~/.llmdocs/docs/<slug>/
   ```

(If you omit `--out` on the `--url` path, the fetcher already defaults to
`~/.llmdocs/docs/<slug>/` — overridable with `$LLMDOCS_HOME`. Passing it explicitly keeps the
slug clean.)

The fetcher defaults: `--max-pages 5000`, `--workers 1`, `--rate-limit 0.5`, auto-deletes `_raw_html/` cache after success. For **batch refresh (preset groups, multiple libs)** always pass `--workers 4 --rate-limit 0.25` — gives ~3.5x speedup with same effective per-host rate (1 req/sec across workers). For single ad-hoc fetches, defaults are fine.

Skip patterns built-in: non-English locales (`/fr/`, `/zh_HANS-CN/`), version-pinned paths (`/2.43.0/`), and version aliases (`/latest/`, `/main/`, `/master/`, `/dev/`). Pass `--keep-html` only when debugging.

Where `<slug>` is the alias name or a kebab-case version of the URL's hostname/path.
Output goes to the global store `~/.llmdocs/docs/<slug>/` — the same path regardless of
which repo you run from. **Never** write docs into the current project's `./docs/`.

4. Run targets sequentially (each fetch is network-bound).
5. After each fetch: report target, pages written, output path, any errors.
6. **After ALL fetches succeed, auto-chain `/doc-indexer`** for every freshly-fetched lib. This builds the `COMPACT.md` token-cheap layer (~900–1,300 tokens vs millions of raw — a measured 99.8–99.97% reduction, see `bench/REPORT.md`) that downstream sessions read by default. Never skip this step — the indexed layer is the point of the workflow.
7. **Refresh the store manifest** so what we've gathered stays tracked:
   ```bash
   (cd "$LLMDOCS_DIR" && python -m scripts.manifest)
   ```
8. Final summary table: alias → pages → path → COMPACT.md status.
9. Tell the user: "Docs available globally at ~/.llmdocs/docs/<slug>/ (also @~/.claude/docs/<slug>/) — use COMPACT.md for cheap lookups, raw .md files for deep dives. Available to every repo. Manifest: ~/.llmdocs/MANIFEST.md"
