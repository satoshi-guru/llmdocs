# Consuming llmdocs output (the tier ladder)

llmdocs serves the same docs at four cost tiers, cheapest to richest. An agent (or a human) should
read the cheapest tier that answers the question and stop.

| Tier | File | ~Cost | Use it when |
|------|------|-------|-------------|
| LOOKUP | `docs/LOOKUP.md` (+ per-lib `docs/<lib>/LOOKUP.md`) | ~0 tok (grep one line) | You need one signature / one fact |
| COMPACT | `docs/<lib>/COMPACT.md` | ~800 tok | You need the API shape / several signatures |
| min / dense | `docs/<lib>/<page>.min.md` or `<page>.dense.md` | page-sized, ~30-55% of raw | A specific page in full, cheaply |
| raw | `docs/<lib>/<page>.md` | full | Last resort — exact wording, examples, edge cases |

## The ladder, in one rule

Grep LOOKUP first. If that is not enough, read COMPACT. If COMPACT is missing or lacks a detail,
read the `.min.md` (or `.dense.md`) variant of the most relevant page. Only then read the full
raw page.

## Fidelity guarantee (why this is safe)

Every tier is **derived from raw and points back to it** — `min` is mechanically lossless-ish,
COMPACT keeps every signature, LOOKUP indexes the whole surface. **Raw is always on disk; no detail
is ever unreachable.** The ladder saves tokens; it never hides content. If the cheap tier lacks a
detail, the raw page has it.

## Honest numbers (alpha-lib example fixture)

On the `store/example/alpha-lib` fixture (1 raw page, 25 functions):
raw ≈ 4,764 tok → COMPACT ≈ 656 tok = **86.23% reduction**, with **all 25 signatures retained**
(verify in `store/INDEX.md`). This is the realistic figure for real docs — not a delete-everything
ratio. Token-saving is already won at this tier; the goal of the ladder is full access and full
readability, not further compression.

## For agents

See `agents/doc-context.md` — it encodes this ladder as the research workflow with a
≤ 6 000-token fallback ceiling per library. The ceiling is a default-cost bound, not a wall:
raw pages remain on disk and are always reachable on an explicit request.
