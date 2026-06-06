"""Tests for scripts/lookup_merge.py and scripts/store_index.py.

Task 3.5: silent-corruption guards.
  - lookup_merge must skip (warn+skip) lines without a '|' instead of ingesting them
  - lookup_merge must dedup identical lines within an incoming block
  - store_index must survive a non-UTF-8 byte in a COMPACT.md file (errors="ignore")
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run_lookup_merge(lib: str, stdin_text: str, store_dir: Path) -> subprocess.CompletedProcess:
    env = {"LLMDOCS_HOME": str(store_dir), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, "-m", "scripts.lookup_merge", lib],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )


# ---------------------------------------------------------------------------
# lookup_merge — malformed-line guard (scripts-F3)
# ---------------------------------------------------------------------------

def test_lookup_merge_skips_pipeless_line(tmp_path):
    """A line without '|' must NOT be ingested; a warning must appear on stderr."""
    store = tmp_path / "docs"
    store.mkdir()

    result = _run_lookup_merge(
        "fastapi",
        "fastapi | FastAPI(title) | create app\nGARBAGE LINE NO PIPE\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr

    lookup_text = (store / "LOOKUP.md").read_text(encoding="utf-8")
    # The valid line must be kept
    assert "FastAPI(title)" in lookup_text
    # The pipeless line must NOT appear in the file
    assert "GARBAGE LINE NO PIPE" not in lookup_text
    # A warning must be printed to stderr
    assert "warning" in result.stderr.lower()


def test_lookup_merge_pipeless_line_warning_content(tmp_path):
    """The stderr warning must quote or name the offending line."""
    store = tmp_path / "docs"
    store.mkdir()

    result = _run_lookup_merge(
        "mylib",
        "mylib | fn() | d\nBAD LINE\n",
        tmp_path,
    )
    assert "BAD LINE" in result.stderr or "bad line" in result.stderr.lower()


# ---------------------------------------------------------------------------
# lookup_merge — dedup within incoming block (scripts-F8)
# ---------------------------------------------------------------------------

def test_lookup_merge_deduplicates_identical_incoming_lines(tmp_path):
    """Exact duplicate lines in the incoming stdin block must appear only once."""
    store = tmp_path / "docs"
    store.mkdir()

    result = _run_lookup_merge(
        "x",
        "x | f() | d\nx | f() | d\nx | f() | d\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr

    lookup_text = (store / "LOOKUP.md").read_text(encoding="utf-8")
    lines = [ln for ln in lookup_text.splitlines() if "x | f() | d" in ln]
    assert len(lines) == 1, f"Expected 1 occurrence, got {len(lines)}: {lines}"


def test_lookup_merge_dedup_preserves_distinct_lines(tmp_path):
    """Lines that differ (even slightly) must all be kept — no over-filtering."""
    store = tmp_path / "docs"
    store.mkdir()

    result = _run_lookup_merge(
        "x",
        "x | f(a) | note1\nx | f(b) | note2\nx | f(a) | note1\n",
        tmp_path,
    )
    assert result.returncode == 0

    lookup_text = (store / "LOOKUP.md").read_text(encoding="utf-8")
    assert "x | f(a) | note1" in lookup_text
    assert "x | f(b) | note2" in lookup_text
    # But the duplicate f(a) line should appear exactly once
    assert lookup_text.count("x | f(a) | note1") == 1


# ---------------------------------------------------------------------------
# store_index — survives non-UTF-8 byte in COMPACT.md (scripts-F4)
# ---------------------------------------------------------------------------

def test_store_index_survives_nonutf8_compact(tmp_path):
    """store_index must not crash when COMPACT.md contains a non-UTF-8 byte."""
    store = tmp_path / "docs"
    badlib = store / "badlib"
    badlib.mkdir(parents=True)

    # Write a COMPACT.md with an invalid byte (0xff is never valid UTF-8)
    compact_path = badlib / "COMPACT.md"
    compact_path.write_bytes(b"\xff bad byte\nIndexed: 2026-06-01\n")

    # Write a minimal raw page so the library shows up in the table
    (badlib / "page.md").write_text("# x\nbody\n", encoding="utf-8")

    out = tmp_path / "INDEX.md"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.store_index",
         "--store", str(store), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"store_index crashed on non-UTF-8 COMPACT.md.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert out.exists(), "INDEX.md was not written"
    content = out.read_text(encoding="utf-8")
    assert "badlib" in content
