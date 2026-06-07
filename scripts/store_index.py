#!/usr/bin/env python3
"""Self-documenting dashboard for the doc store.

Scans a store directory and (re)generates a one-row-per-library table: which tiers
exist (raw / INDEX / COMPACT / LOOKUP), page count, raw vs COMPACT token estimate,
the measured reduction %, and the COMPACT 'Indexed:' date. One generator, no GEN-block
framework — the drift gate is just `--check` (or CI running this then `git diff`).

Determinism note: every field is content-derived (token estimate, the `Indexed:` line
inside COMPACT.md) — never file mtimes — so regenerating on any machine/checkout yields
byte-identical output, which is what makes the `git diff --exit-code` drift gate work.

Rendering is split from scanning: `scan()` returns pure `Row` data, `format_dashboard()`
turns rows into markdown. Reuse `scan()` for other views without touching the formatter.

Usage:
  python -m scripts.store_index                       # live dashboard for your store
  python -m scripts.store_index --check               # exit 1 if the on-disk file is stale
  python -m scripts.store_index --plain               # leaner table, no reduction bar
  python -m scripts.store_index --store store/example --out store/INDEX.md [--check]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.manifest import est_tokens, _SKIP_DIRS, _raw_pages  # noqa: E402

DEFAULT_STORE = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs")) / "docs"
_INDEXED_RE = re.compile(r"Indexed:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")

# Reduction bar: 10 cells, 1/8-block resolution. Pure arithmetic on a content-derived
# fraction → byte-identical on every machine (keeps the `--check` drift gate valid).
_BAR_WIDTH = 8
_EIGHTHS = " ▏▎▍▌▋▊▉"  # 0..7 eighths; full cell is █


class Row(NamedTuple):
    """One library's scanned facts — pure data, no formatting."""
    name: str
    tiers: str            # e.g. "RICL" / "R··L"
    pages: int
    raw_tok: int
    compact_tok: int
    indexed: str          # "YYYY-MM-DD" or "—"

    @property
    def reduction(self) -> float | None:
        """COMPACT savings vs raw as a 0..1 fraction, or None if not indexed."""
        if self.compact_tok and self.raw_tok:
            return 1 - self.compact_tok / self.raw_tok
        return None


def _indexed_date(compact: Path) -> str:
    if not compact.exists():
        return "—"
    m = _INDEXED_RE.search(compact.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1) if m else "—"


def _lookup_libs(store: Path) -> set[str]:
    """Library names that have at least one line in the global LOOKUP.md."""
    lookup = store / "LOOKUP.md"
    if not lookup.exists():
        return set()
    libs = set()
    for line in lookup.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "|" in line:
            libs.add(line.split("|", 1)[0].strip())
    return libs


def scan(store: Path) -> list[Row]:
    """Gather one Row per library — pure data, no markdown. The single source of
    truth for what a library *is*; every renderer consumes these rows."""
    lookup_libs = _lookup_libs(store)
    rows: list[Row] = []
    for lib in sorted(
        p for p in store.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in _SKIP_DIRS
    ):
        pages = _raw_pages(lib)
        raw_tok = sum(est_tokens(p.read_text(encoding="utf-8", errors="ignore")) for p in pages)
        compact = lib / "COMPACT.md"
        compact_tok = est_tokens(compact.read_text(encoding="utf-8", errors="ignore")) if compact.exists() else 0
        tiers = "".join([
            "R" if pages else "·",
            "I" if (lib / "INDEX.md").exists() else "·",
            "C" if compact.exists() else "·",
            "L" if lib.name in lookup_libs else "·",
        ])
        rows.append(Row(lib.name, tiers, len(pages), raw_tok, compact_tok,
                        _indexed_date(compact)))
    return rows


def _bar(frac: float) -> str:
    """A deterministic 8-cell unicode meter for a 0..1 fraction."""
    frac = max(0.0, min(1.0, frac))
    eighths = round(frac * _BAR_WIDTH * 8)
    full, rem = divmod(eighths, 8)
    cells = "█" * full + (_EIGHTHS[rem] if rem else "")
    return (cells + "░" * _BAR_WIDTH)[:_BAR_WIDTH]


def _reduction_cell(frac: float | None) -> str:
    if frac is None:
        return "—"
    return f"`{_bar(frac)}` {frac * 100:.1f}%"


def _ctok_cell(compact_tok: int) -> str:
    return f"{compact_tok:,}" if compact_tok else "—"


def format_dashboard(rows: list[Row], plain: bool = False) -> str:
    """Render scanned rows to the dashboard markdown. `plain` drops the reduction
    bar (a leaner table for token-sensitive contexts); the data is identical."""
    tot_pages = sum(r.pages for r in rows)
    tot_raw = sum(r.raw_tok for r in rows)
    tot_compact = sum(r.compact_tok for r in rows)
    tot_frac = (1 - tot_compact / tot_raw) if tot_raw else None
    saved = f" · {tot_frac * 100:.0f}% saved" if tot_frac is not None else ""

    def red(frac: float | None) -> str:
        if plain:
            return f"{frac * 100:.2f}%" if frac is not None else "—"
        return _reduction_cell(frac)

    lines = [
        "# llmdocs — Store Dashboard",
        "",
        "_Generated by `python -m scripts.store_index` — do not hand-edit._ Tiers: "
        "**R**aw · **I**NDEX · **C**OMPACT · **L**OOKUP (`·` = missing). Tokens estimated at chars/4.",
        "",
        f"**{len(rows)} libraries · {tot_pages} pages · raw≈{tot_raw:,} → "
        f"COMPACT≈{tot_compact:,} tok{saved}**",
        "",
        "| Library | Tiers | Pages | Raw tok | COMPACT | Reduction | Indexed |",
        "|---------|:-----:|------:|--------:|--------:|:----------|:-------:|",
    ]
    for r in rows:
        lines.append(
            f"| {r.name} | `{r.tiers}` | {r.pages} | {r.raw_tok:,} | "
            f"{_ctok_cell(r.compact_tok)} | {red(r.reduction)} | {r.indexed} |"
        )
    if rows:
        lines.append(
            f"| **Total** | — | **{tot_pages}** | **{tot_raw:,}** | "
            f"**{tot_compact:,}** | {red(tot_frac)} | — |"
        )
    return "\n".join(lines) + "\n"


def render(store: Path, plain: bool = False) -> str:
    if not store.is_dir():
        return f"# llmdocs — Store Dashboard\n\n_No store at `{store}`._\n"
    return format_dashboard(scan(store), plain=plain)


def main() -> int:
    ap = argparse.ArgumentParser(description="regenerate the store dashboard (store/INDEX.md)")
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE, help="store docs dir to scan")
    ap.add_argument("--out", type=Path, default=None, help="output file (default: <store>/INDEX.md)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the on-disk file is stale")
    ap.add_argument("--plain", action="store_true",
                    help="leaner table without the reduction bar (~7 tok/row cheaper to read)")
    args = ap.parse_args()

    out = args.out or (args.store / "INDEX.md")
    content = render(args.store, plain=args.plain)

    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != content:
            print(f"STALE: {out} differs from regenerated dashboard. Run `python -m scripts.store_index`"
                  + (f" --store {args.store} --out {out}" if args.out else "") + ".", file=sys.stderr)
            return 1
        print(f"up to date: {out}")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
