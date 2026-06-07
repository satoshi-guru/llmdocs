# llmdocs — Next Steps Plan

Sequenced plan for the 6 open issues (#14–#19). Order respects dependencies:
engine reliability + provenance must land **before** any mass store re-fetch.

```
A #14 incremental writes ─┐
B #16 provenance/version ─┼─► D #15 store cleanup (prune + re-fetch) ─► (store clean)
C1 #17 github strategy  ──┤
C2 #19 blocked sites    ──┘
A,B,C ──► E #18 publish docs-prime + docs-context   (store cleanup not required for publish)
```

Rules in force: never work on main; one branch per task → tests → PR → rebase-merge
→ delete branch. Always commit small + detailed. No bulk tests — smallest doc first,
escalate only if signal insufficient; engines compared on the same URL simultaneously.
File an issue for any new/deferred finding.

---

## Phase A — #14 Incremental page writes (engine reliability)

**Goal:** a crawl that is killed or times out keeps every page it already fetched
(today it writes nothing — all output is buffered until Phase 4).
**Why first:** prerequisite for safe mass re-fetch (D); large legit crawls must not
lose everything on overrun.
**Branch:** `fix/incremental-writes`

**Step-by-step:**
1. Read `phase1_http` + `phase4_write`; map the buffer→Phase-4 flow and where
   compaction is applied.
2. Extract a `write_page(page, out_dir, compact)` helper (compaction per page).
3. In the Phase-1 loop, write each page to disk **immediately** after extraction
   (dedup already guarantees one write per output file); accumulate index entries.
4. Wrap the crawl in `try/finally` and install a SIGTERM/SIGINT handler that sets a
   stop flag → loop exits cleanly and the `finally` writes INDEX from whatever pages
   exist; log `truncated at N pages`.
5. Phase 4 becomes "write INDEX from collected entries" (pages already on disk).
6. Tests: `write_page` output; a mock that raises mid-loop asserts INDEX is still
   written + partial pages persisted.
7. Validate: uvicorn (smallest) output byte-identical to before; one medium doc.

**Acceptance:** interrupted crawl → N valid `.md` + partial INDEX + "truncated" log;
normal output unchanged; tests green.

---

## Phase B — #16 Provenance / versioning scheme

**Goal:** never silently overwrite a slug; tag each fetch with engine git-sha + date;
keep duplicate versions so data quality can be compared across engine versions.
**Why before re-fetch:** D must preserve old copies, not clobber them.
**Branch:** `feat/store-provenance`

**Design (recommended — keeps skills working):**
- Canonical path stays `~/.llmdocs/docs/<slug>/` (skills read this unchanged).
- On (re)write of an existing slug, **archive** the old copy to
  `~/.llmdocs/docs/.archive/<slug>@<engine-sha>-<YYYYMMDD>/` before overwriting.
- Stamp provenance in INDEX header + page frontmatter: `fetched_with: <engine-sha>`,
  `fetched_at: <date>`.
- Engine sha resolved at runtime (embed a `__version__`/VERSION, or `git rev-parse`
  of the engine repo; fall back to `unknown`).

**Step-by-step:**
1. Write a short design note (layout + provenance fields) in this file's "Decisions".
2. Add engine-version resolution helper.
3. Add archive-on-overwrite in the write path (skip if slug absent).
4. Add provenance fields to INDEX header + frontmatter.
5. Surface provenance in `inventory.py` / `manifest.py` / `store_index.py`
   (engine-sha + fetched_at column).
6. Tests: archive-on-overwrite moves old copy; provenance present; absent slug =
   no archive.
7. Validate: fetch smallest doc twice → old archived, new current, both stamped.

**Acceptance:** re-fetch preserves old copy under `.archive/`, records engine-sha +
date; canonical path + skills unaffected; tests green.

---

## Phase C1 — #17 Validate `--strategy github` + benchmark github slugs

**Goal:** the github-strategy path produces clean output (the sweep only covered
HTTP). Many github slugs show drift / had asset junk.
**Branch:** `fix/github-strategy`

**Step-by-step:**
1. Read `phase1_github`; confirm it shares `phase4_write` (so asset/url/dedup fixes
   already apply) or note gaps.
2. Smallest github slug first (e.g. gitleaks ~9 or detect-secrets ~10): run
   `--strategy github`, compare files/INDEX/assets to the stored copy.
3. If the github path bypasses any fix, port it; add asset-skip to github file
   selection too (skip non-doc files in the repo).
4. Test on the smallest github slug; escalate to a mid one (nuclei — has the only
   real inline base64; confirm it's code, not stripped).

**Acceptance:** github slugs fetch with 0 asset files, truthful INDEX; smallest +
one mid slug validated; tests/notes committed.

---

## Phase C2 — #19 Crawler-blocked sites (nftables)

**Goal:** sites returning 0 for all engines (wiki.nftables.org) fetch again, or are
documented as truly blocked.
**Branch:** `fix/crawl-blocked-sites`

**Step-by-step:**
1. Diagnose: `curl` nftables with the engine UA vs a browser UA; inspect status /
   Cloudflare / robots.
2. If UA-gated: default `$LLMDOCS_UA` to a realistic browser UA; add a 429/403
   backoff-retry.
3. Validate nftables fetches > 0 (smallest path first); if still blocked, document
   in the issue as site-side and close.

**Acceptance:** nftables > 0 pages, or a documented site-side block + closed issue.

---

## Phase D — #15 Store cleanup (prune assets + re-fetch drift) — NEEDS GO

**Goal:** remove the 502 asset `.md` and repair the 57 INDEX-drift slugs.
**Depends on:** A (safe writes), B (provenance), C1 (github), C2 (blocked sites).
**Mutates the GLOBAL store — explicit user go-ahead required.**

**Step-by-step:**
1. Backup: `tar czf ~/llmdocs-store-backup-<date>.tgz ~/.llmdocs/docs`.
2. `python scripts/store_doctor.py --prune-assets` (confirm) → delete 502.
3. Regenerate `store_index` + `manifest`.
4. Re-fetch the 57 drift slugs **smallest-first** (use `inventory.py` order), via
   the fixed engine with provenance (B); monitor each — no bulk.
5. `store_doctor.py --check` → expect 0 defects; spot-check a repaired slug
   (ruff: 978 files now correctly indexed).

**Acceptance:** `--check` clean; 502 gone; drift slugs truthful; old copies archived;
backup exists.

---

## Phase E — #18 Publish docs-prime + docs-context — NEEDS GO

**Goal:** the original task — make docs-prime + docs-context public.
**Depends on:** A,B,C complete (solid engine). Store cleanup (D) recommended but not
required (the store is local data, not published).
**Branch:** `chore/publish-prep`

**Step-by-step:**
1. Decide scope/repo: publish `llmdocs` itself, or a clean public mirror;
   choose a license; confirm with user.
2. De-personalization audit: grep for private paths/hosts/tokens; scrub.
3. Ensure skills (docs-prime, docs-fetch, docs-context, docs-distill) + install.sh are
   included and documented for external users.
4. Quickstart README for outsiders.
5. Make public (explicit user action). Verify with `gh repo view`.

**Acceptance:** public repo with engine + skills + docs; de-personalized; user
confirmed.

---

## Decisions log
(to be filled as phases land)
