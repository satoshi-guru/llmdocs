# HTTP vs GitHub Strategy

llmdocs has two fetch strategies. Choosing the right one matters.

## HTTP crawl (default)

Fetches pages by following links, the same way a browser would. Works on any site that serves HTML directly.

```bash
python crawler.py --url https://docs.example.com
```

**Works well for:**
- Static site generators (Hugo, Docusaurus, Jekyll, Mintlify)
- GitBook-hosted docs
- Any site that renders full HTML server-side

**Does NOT work for:**
- React/Vue/Angular SPAs where content is injected by JavaScript
- Sites that require authentication to view docs

**How to tell if HTTP is working:** run with `--max-pages 3` first. If you get 0 pages or very thin content (< 200 chars per page), the site is JS-rendered.

```bash
python crawler.py --url https://docs.example.com --max-pages 3 --out /tmp/test
```

---

## GitHub clone

Clones the docs source repo directly and reads the raw markdown files. Bypasses the website entirely.

```bash
python crawler.py \
  --url https://example.com \
  --strategy github \
  --github-repo https://github.com/org/docs-repo \
  --github-docs-dir docs \
  --out output/example
```

> **Why `--url` is required:** `--url` is the CLI's entry point for all non-preset runs.
> When using `--strategy github`, the `--url` value is not fetched — `phase1_github()`
> reads directly from the cloned repo. However `--url` determines the output slug
> (the directory name under `~/.llmdocs/docs/`). Pass the canonical library website URL
> or add `--out ~/.llmdocs/docs/<slug>/` explicitly to control the slug.

**Works well for:**
- React/SPA sites where the underlying docs are open source (Discord, Stripe, GitHub)
- Faster and more reliable than crawling
- Gets canonical source before any rendering transforms

**Does NOT work for:**
- Proprietary docs with no public source repo
- Sites where docs are generated (not written as markdown)

---

## Decision guide

```
Site uses React/SPA? ──Yes──→ Is the source repo public? ──Yes──→ GitHub strategy
         │                                                   └──No──→ Try HTTP (may fail)
         └──No──→ HTTP strategy (default)
```

**Quick test:** open the site, disable JavaScript in DevTools, refresh. If the page goes blank or shows a loading spinner — use GitHub strategy.

---

## Supported file extensions (GitHub strategy)

By default reads `.md` and `.mdx`. Override with a custom preset if your repo uses `.rst`, `.txt`, or other formats — you'll need to extend the parser for non-markdown formats.
