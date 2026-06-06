#!/usr/bin/env python3
"""Compaction strategies for the token×quality benchmark.

Each strategy is a plain function `(lib_dir, lookup_lines) -> artifact_text`:
the exact text a builder agent would read for that library under that strategy.
`bench.py` measures every strategy's token cost + quality (recall gate + LLM-judge).

Add a new strategy by adding a function and listing it in STRATEGIES — no registry,
no plugins. The ladder runs cheap→rich so the Pareto picture is obvious in REPORT.md.
"""

from __future__ import annotations

from pathlib import Path

# Files in a lib dir that are NOT raw doc pages (mirror scripts.manifest.SKIP_FILES).
_NON_RAW = {"COMPACT.md", "INDEX.md", "LOOKUP.md"}

# Hard char budget for the raw-docs baseline. ~12k chars ≈ ~3k tokens — a realistic
# "skim the top pages" slice enforced on the combined output (not per-page).
# Full raw would be 10–100× larger for real libraries; this is the bounded baseline.
RAW_HEAD_BUDGET = 12_000


def _raw_pages(lib_dir: Path) -> list[Path]:
    """Content pages, largest first (doc-indexer's content-rich heuristic)."""
    pages = [p for p in lib_dir.rglob("*.md")
             if p.name not in _NON_RAW and "_raw_html" not in p.parts]
    return sorted(pages, key=lambda p: p.stat().st_size, reverse=True)


def s_raw_head(lib_dir: Path, lookup_lines: list[str]) -> str:
    """Baseline: first RAW_HEAD_BUDGET chars of the largest raw pages.

    Simulates a realistic 'skim the top pages' read — high cost but bounded.
    RAW_HEAD_BUDGET is enforced on the *combined* output, so even a single large page
    is truncated. This makes the baseline ~3k tokens as documented and comparable to
    the compact tier. For full raw-page reading, use the raw page files directly.
    """
    out, used = [], 0
    for p in _raw_pages(lib_dir):
        if used >= RAW_HEAD_BUDGET:
            break
        text = p.read_text(encoding="utf-8", errors="ignore")
        remaining = RAW_HEAD_BUDGET - used
        out.append(text[:remaining])
        used += min(len(text), remaining)
    combined = "\n\n".join(out)
    return combined[:RAW_HEAD_BUDGET]


def s_compact(lib_dir: Path, lookup_lines: list[str]) -> str:
    """The COMPACT.md tier — the current ~99% reduction."""
    compact = lib_dir / "COMPACT.md"
    return compact.read_text(encoding="utf-8") if compact.exists() else ""


def s_compact_lookup(lib_dir: Path, lookup_lines: list[str]) -> str:
    """COMPACT.md + the lib's grep-tier LOOKUP lines (signature index)."""
    base = s_compact(lib_dir, lookup_lines)
    if not lookup_lines:
        return base
    return base + "\n\n## LOOKUP\n" + "\n".join(lookup_lines) + "\n"


def s_lookup_only(lib_dir: Path, lookup_lines: list[str]) -> str:
    """Just the grep tier — the cheapest serve (the ~99.9% step)."""
    return "\n".join(lookup_lines) + "\n" if lookup_lines else ""


# Cheap → rich. bench.py iterates this order.
STRATEGIES = {
    "lookup_only": s_lookup_only,
    "compact": s_compact,
    "compact_lookup": s_compact_lookup,
    "raw_head": s_raw_head,
}
