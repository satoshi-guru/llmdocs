# benchmarks/

Tools for comparing llmdocs engine versions and auditing crawl quality, used to
validate that the current engine (#3 / this repo) is the best baseline.

## Methodology — smallest doc first

Never bulk-test. Pick the **smallest** doc that could exercise the behavior in
question; only escalate to a larger doc if the small one doesn't give a clear
signal. Always run the engines being compared on the **same URL simultaneously**
so live site drift affects them equally (comparing a fresh crawl to a stored copy
is invalid — sites change).

## Scripts

### `inventory.py`
Size-sorted audit of the global store (`$LLMDOCS_HOME/docs`): files on disk,
INDEX `Pages:` header, DUP flag when they disagree, fetch date, Source URL.
Smallest-first — the order to re-fetch / benchmark in. Read-only.
```
python benchmarks/inventory.py
```

### `compare_engines.sh`
Runs N engines on the same URL simultaneously into isolated sandboxes; reports
distinct files, INDEX rows (truthful?), asset-junk count, and file overlap vs the
reference engine (the last one listed).
```
ENGINES="1b=/sandbox/engine-1b.py 3=$PWD/llmdocs.py" \
  PY=python3 ./benchmarks/compare_engines.sh uvicorn https://uvicorn.dev/ --workers 4 --rate-limit 0.2
```
Note: pass engine-appropriate flags only — the oldest single-threaded engine
(#1a, commit 7dea474) does **not** accept `--workers`/`--rate-limit`.

## Engine snapshots for comparison

The historical engines live in the `llmdocs` repo (github.com/satoshi-guru/llmdocs):
- **#1a** = commit `7dea474` (single-threaded, no path-prefix auto-derive)
- **#1b** = commit `326692b` (parallel + prefix, "production crawler")
- **#1aF / #1bF** = branches `engine-1aF` / `engine-1bF` — those bases + all
  applicable crawl fixes (for the record; #1bF converges to #3, #1aF stays broad)
- **#3** = this repo (`llmdocs-next`), the current best baseline

Extract a snapshot with e.g. `git -C ../llmdocs show 326692b:llmdocs.py > /sandbox/engine-1b.py`.

## Verdict (2026-06-07)

#3 ≥ every other engine on all 23 sites tested across 4 size batches; strictly
better on siloed / dup-prone / alias / file-leaf / asset-heavy sites. #1bF ≡ #3
(same lineage). #1aF (broad) does **not** beat #3 — broad crawling pulls
off-topic real pages (blog/legal/keys) that scoping correctly excludes. See the
`fix(crawl)` history and issues for the specific defects found and fixed.
