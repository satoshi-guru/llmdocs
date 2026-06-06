# Adding a Custom Preset

Presets are entries in the `PRESETS` dict at the top of `llmdocs.py`. Adding one takes about 10 lines.

## HTTP preset

```python
"mysite": {
    "name": "My Site Docs",
    "strategy": "http",
    "url": "https://docs.mysite.com",
    "out": "output/mysite",

    # CSS selectors tried in order — first match wins
    "content_selectors": ["article", "main", "#content", "[class*='content']"],

    # Elements stripped from matched content before conversion
    "skip_selectors": ["nav", "footer", "header", "aside", "[class*='sidebar']"],

    # Only crawl URLs that start with this path (prevents crawling the whole site)
    "path_prefix": "/docs",

    "max_depth": 4,       # link-follow depth from root URL
    "max_pages": 200,     # hard cap on fetched pages
    "same_domain_only": True,
    "rate_limit": 0.5,    # seconds between requests — be polite
},
```

> **Output path:** When this preset runs without `--out`, the `"out": "output/mysite"` value
> is redirected to `~/.llmdocs/docs/mysite/` (the global store) automatically. Pass `--out /tmp/mysite`
> to keep test output local.

## GitHub preset

```python
"mylib": {
    "name": "MyLib Docs",
    "strategy": "github",
    "github_repo": "https://github.com/org/mylib",
    "github_docs_dir": "docs",   # subdirectory inside the repo
    "out": "output/mylib",
    "file_extensions": [".md", ".mdx"],
},
```

## Finding the right content selector

1. Open the docs site in a browser
2. Right-click the main content area → Inspect
3. Look for a container element that wraps just the article — `<main>`, `<article>`, or a `<div>` with a class like `content`, `docs-body`, `page-content`
4. Add it as the first entry in `content_selectors`

If you're unsure, try `"main"` first — it's the correct semantic element on most modern docs sites.

## Debugging a new preset

```bash
# Test with 5 pages only, output to /tmp
python llmdocs.py --preset mysite --max-pages 5 --out /tmp/test_mysite

# Check what was extracted
ls /tmp/test_mysite/
cat /tmp/test_mysite/INDEX.md
```

If pages come out empty or with just navigation text, adjust `content_selectors` and `skip_selectors`.
