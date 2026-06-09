---
name: doc-store-doctor
description: >-
  Audit, de-duplicate, and refresh the global llmdocs documentation store at
  ~/.llmdocs/docs. Use this skill whenever the user asks what docs need updating, which
  docs are stale or behind, to clean up / tidy / audit / health-check the doc store, to
  find or remove duplicate slugs, to refresh or re-fetch stale libraries, or asks "is the
  store healthy" / "what's the next doc to update". Also use it to keep the doc source-URL
  list current — validate that each doc's source URL is still live, find docs with a missing,
  unknown, or dead (404/moved) source, or recover a doc's correct URL from history. Trigger it
  even when the user only describes the goal (e.g. "the docs folder is a mess", "do we have
  dupes", "are our docs current", "is that doc url still right", "where did this doc come
  from") without naming the store. Reports findings first and only changes anything after the
  user confirms; recovers lost URLs from real provenance (never guesses); archives (never
  hard-deletes) so every action is reversible.
---

# Doc Store Doctor

Keep the global, append-only llmdocs store (`~/.llmdocs/docs/`, override `$LLMDOCS_HOME`)
healthy: current, duplicate-free, and correctly indexed. The store is **append-only by
design** — fetches add, never overwrite — so over time it accumulates stale snapshots,
duplicate slugs, and index drift. This skill finds those and fixes them safely.

## The cardinal rule: report → confirm → fix

Never mutate the store before showing the user what you found and getting an explicit OK.
The audits are read-only; the fixes are gated. Two reasons this matters:

1. **Archiving is reversible but disruptive.** Moving a slug out from under a project that
   greps it can surprise the user. Let them veto.
2. **Heuristics aren't ground truth — especially for duplicates.** Same *source* does not
   mean same *content*. A full docs site and its language-specific API reference can share
   a `Source:` URL yet be two things the user wants to keep (e.g. `supabase` = 1351 pages
   of full docs vs `supabase-js` = 192 pages of just the JS reference). The detector is
   tuned to be conservative, but the human is the final judge of every dup before it moves.

So: run the audits, present a findings report, then execute only the fixes the user approves.

## Step 1 — Audit (read-only)

Run these and collect the findings. They're independent; you can run them in one batch. Run the
repo scripts from the **llmdocs repo root** (the `scripts/` ones below); use the repo's venv
(`.venv/bin/python`) or your `python3`. The two `<skill>/scripts/` tools are bundled with this
skill (at `skills/doc-store-doctor/scripts/` in the repo). The store path defaults to
`~/.llmdocs/docs` (override with `$LLMDOCS_HOME`).

| Check | Command | Finds |
|-------|---------|-------|
| **Duplicate slugs** | `python <skill>/scripts/find_duplicate_slugs.py` | same docs under two names (`hyperliquid`/`hyperliquid-docs`), stub-beside-full (`anthropic` 4pg ⊂ `anthropic-api` 232pg), `-docs` name collisions |
| **Source-URL health** | `python <skill>/scripts/audit_sources.py [--check-urls]` | docs with unknown origin (`Source: ?`) — recovered from backup silos when possible — and (with `--check-urls`) source URLs that 404 or have moved |
| **Stale / behind** | `python scripts/check_outdated.py --behind-only` | libs whose upstream shipped a release after our snapshot |
| **Data defects** | `python scripts/store_doctor.py` | binary-asset junk saved as `.md`, INDEX drift (rows ≠ files on disk). Default mode is a read-only report; `--check` is the CI exit-code gate (there is no `--report` flag) |
| **Tier coverage** | `python -m scripts.store_index --plain` | which libs are missing INDEX / COMPACT / LOOKUP tiers |

`find_duplicate_slugs.py` and `audit_sources.py` are bundled with this skill; the rest are
repo scripts. Add `--json` to the bundled scripts to drive fixes programmatically.

### The source-URL list is the store's lifeline
A doc the store can't trace back to a live URL can't be refreshed — it rots in place. That's
the single most important thing to keep current, and it has its own tier of truth:

- **Every doc records its `Source:`** in `INDEX.md`. `audit_sources.py` rolls these into one
  list and flags any that are `?`/missing.
- **The per-repo `docs/` silos are the backup tier — do NOT delete them.** Before llmdoc, repos
  fetched vendor docs into local `docs/<slug>/` folders. Those are superseded by the global
  store *as content*, but they often preserve a valid source URL the global copy lost (this is
  exactly how the BitUnix URL was recovered: the global INDEX said `Source: ?` while the
  `a project's docs/bitunix/` silo still recorded `https://www.bitunix.com/api-docs/futures/`).
  Keep the silos as a recovery + verification reference; `audit_sources.py` mines them to fill
  unknowns. Don't trade away the safety net.
- **A recorded URL can still go stale.** Vendors move docs (BitUnix's old
  `openapidoc.bitunix.com/.../introduction.html` now 404s). `--check-urls` HEAD-validates every
  source so the list stays *correct and newest*, not one step behind.

## Step 2 — Present the findings

Summarise as a short report grouped by fix type. For duplicates, show each group with page
counts, fetch dates, and sources so the user can sanity-check — and explicitly ask about any
group where the members might legitimately differ (different page counts or scopes). Example:

```
Duplicates (confirm before archiving):
  • hyperliquid (141, 06-07) = hyperliquid-docs (141, 06-07)  → keep hyperliquid, archive -docs   [confident: identical mirror]
  • anthropic (4pg, 05-26) ⊂ anthropic-api (232pg, 06-07)     → keep anthropic-api, archive stub    [confident: stub]
  • supabase (1351) vs supabase-js (192)                       → NOT flagged — different scopes, keep both

Stale (re-fetch?):  viem-siwe (snapshot 06-02, upstream 06-04)
Defects:            <slug> — 3 asset .md files; <slug> — INDEX drift (978 files, 6 rows)
Missing tiers:      hyperliquid — no LOOKUP.md
```

## Step 3 — Fix (only what the user approved)

Apply in this order. Prefer the canonical preset/alias name as the surviving slug.

### De-duplicate
Move the redundant copy to `.archive/` (reversible) — **never `rm`**:
```bash
ts=$(date +%Y%m%dT%H%M%S)
mv ~/.llmdocs/docs/<loser> ~/.llmdocs/docs/.archive/<loser>@dup-$ts
```
**Keep the freshest content under the canonical name.** If the slug to keep is the freshest
but has a non-canonical name (e.g. `hyperliquid-docs` is newer than `hyperliquid`), archive the
older one, then rename the keeper to the bare alias:
```bash
mv ~/.llmdocs/docs/hyperliquid       ~/.llmdocs/docs/.archive/hyperliquid@old-$ts
mv ~/.llmdocs/docs/hyperliquid-docs  ~/.llmdocs/docs/hyperliquid
```

### Recover / correct source URLs
A doc with `Source: ?` or a dead/moved URL can't be refreshed until its real URL is known.
**Recover it from provenance — never invent one.** `audit_sources.py` already proposes a URL
mined from the backup silos and the `.archive/` history (with *when* and *where* it was last
seen). Apply the proposed URL to the doc's `INDEX.md`:
```bash
# e.g. bitunix: lost in the global store, recovered from a project's docs/ silo
sed -i 's|^Source: ?|Source: https://www.bitunix.com/api-docs/futures/|' \
  ~/.llmdocs/docs/bitunix/INDEX.md
```
If `audit_sources.py` reports *"NO recorded source anywhere"*, stop and ask the user for the
URL. Do **not** guess a plausible-looking vendor URL — a hallucinated source is worse than a
blank one, because it looks authoritative and silently re-fetches the wrong thing. When
`--check-urls` flags a URL as **MOVED**, update `INDEX.md` to the new location.

**Treat an apparent 404/timeout as advisory, never as proof a doc is dead — confirm in a real
browser first.** High-value vendor docs routinely bot-block an automated probe with a *fake*
404 or a hang while serving 200 to a browser (verified: TikTok's `/doc/overview` returns 404
to `urllib` but 200 in a browser; Adobe helpx times out a HEAD but loads fine). The probe can't
fake a browser's TLS fingerprint, so it WILL get false 404s. Never remove or stop trusting a
doc on a probe result alone — open the URL in a browser, and only act if it's *also* dead
there. This is the same rule as the dedup detector: the tool surfaces signal; the human (or a
browser) confirms before anything is cut.

### Refresh stale
Re-fetch through the **`/llmdoc` skill** (it owns token→strategy routing and auto-detects
llms.txt) against the doc's *validated* source URL. Use `--archive-existing` so the old
snapshot is preserved as provenance, not clobbered. For a preset lib: `/llmdoc <alias>`. A
fresh crawl can drop the `LOOKUP.md` tier — rebuild it after (see below) if the lib had one.

### Repair defects
```bash
python scripts/store_doctor.py --prune-assets   # delete asset-junk .md (prompts; DESTRUCTIVE)
python scripts/reindex.py <slug>                # rebuild INDEX.md from files on disk (no fetch)
python scripts/build_lookup.py <slug> [--global] # restore the LOOKUP.md grep tier
```

### Finalize (always, after any change)
Regenerate the trackers so the store stays self-describing:
```bash
python3 scripts/manifest.py   # MANIFEST.md
python -m scripts.store_index                                   # store dashboard INDEX.md
```

## Step 4 — Confirm clean
Re-run `find_duplicate_slugs.py`, `audit_sources.py`, and `store_doctor`; report the
before/after (e.g. "139 → 136 libraries, 0 duplicates, 0 unknown sources, 0 defects"). Note
anything left deliberately unfixed and why.

## Principles
- **Reversible by default.** Archive to `.archive/`, never hard-delete. `--prune-assets` is the
  one exception (asset junk is unambiguous garbage) and it prompts. The `.archive/` is not
  clutter — it is the store's provenance trail for recovering lost source URLs.
- **Never hallucinate a source URL.** Recover lost/dead URLs only from real evidence — the
  backup silos and `.archive/` history (what `audit_sources.py` surfaces). If no record exists,
  ask the user. A confident wrong URL silently corrupts the store; a blank one fails loudly.
- **Don't delete the per-repo `docs/` silos.** They're superseded as *content* by the global
  store but remain the backup tier for source URLs (and proof of what was improved). Mine them;
  keep them.
- **Canonical names win.** When deduping, the surviving slug should match the preset/alias the
  user types, so `/llmdoc` and `doc-prime` keep finding it.
- **Freshest content wins** on a tie — but never trade newer content for a nicer name; rename
  instead.
- **The human confirms every dup.** The detector is conservative, not omniscient.
