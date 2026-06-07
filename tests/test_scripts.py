"""Tests for scripts/lookup_merge.py and scripts/store_index.py.

Task 3.5: silent-corruption guards.
  - lookup_merge must skip (warn+skip) lines without a '|' instead of ingesting them
  - lookup_merge must dedup identical lines within an incoming block
  - store_index must survive a non-UTF-8 byte in a COMPACT.md file (errors="ignore")

Task 4.2: shared sorted _raw_pages helper — determinism + _raw_html exclusion.
  - _raw_pages returns a sorted list excluding SKIP_FILES, _raw_html/, and dotdirs
  - manifest and store_index agree on page count (no _raw_html phantom pages)
"""

from __future__ import annotations

import subprocess
import sys
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


def test_lookup_merge_lib_match_is_case_insensitive(tmp_path):
    """Re-merging a lib under different casing must REPLACE its block, not duplicate it (B4)."""
    (tmp_path / "docs").mkdir()
    _run_lookup_merge("fastapi", "fastapi | A() | seed\n", tmp_path)
    _run_lookup_merge("FastApi", "FastApi | B() | recased\n", tmp_path)
    text = (tmp_path / "docs" / "LOOKUP.md").read_text(encoding="utf-8")
    assert "B()" in text and "A()" not in text          # old block dropped, not kept alongside
    libs = {ln.split("|", 1)[0].strip().lower() for ln in text.splitlines() if ln.strip()}
    assert libs == {"fastapi"}                            # one library, not two


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


# ---------------------------------------------------------------------------
# Task 4.2 — shared _raw_pages helper: sorted, excludes _raw_html + dotdirs
# ---------------------------------------------------------------------------

def test_raw_pages_is_sorted(tmp_path):
    """_raw_pages must return pages in lexicographic order."""
    from scripts.manifest import _raw_pages

    lib = tmp_path / "mylib"
    lib.mkdir()
    # Create pages out of alphabetical order
    for name in ("z_page.md", "a_page.md", "m_page.md"):
        (lib / name).write_text(f"# {name}\n", encoding="utf-8")

    pages = _raw_pages(lib)
    names = [p.name for p in pages]
    assert names == sorted(names), f"_raw_pages not sorted: {names}"


def test_raw_pages_excludes_raw_html(tmp_path):
    """_raw_pages must exclude pages inside _raw_html/ subdirectories."""
    from scripts.manifest import _raw_pages

    lib = tmp_path / "mylib"
    raw_html = lib / "_raw_html"
    raw_html.mkdir(parents=True)
    (lib / "real_page.md").write_text("# real\n", encoding="utf-8")
    (raw_html / "cached.md").write_text("# cached\n", encoding="utf-8")

    pages = _raw_pages(lib)
    names = [p.name for p in pages]
    assert "real_page.md" in names
    assert "cached.md" not in names, "_raw_html content must be excluded"


def test_raw_pages_excludes_dotdirs(tmp_path):
    """_raw_pages must exclude pages inside dotdirs (e.g. .git/)."""
    from scripts.manifest import _raw_pages

    lib = tmp_path / "mylib"
    dotdir = lib / ".git"
    dotdir.mkdir(parents=True)
    (lib / "real_page.md").write_text("# real\n", encoding="utf-8")
    (dotdir / "hidden.md").write_text("# hidden\n", encoding="utf-8")

    pages = _raw_pages(lib)
    names = [p.name for p in pages]
    assert "real_page.md" in names
    assert "hidden.md" not in names, "dotdir content must be excluded"


def test_raw_pages_excludes_pycache(tmp_path):
    """_raw_pages must exclude pages inside __pycache__/."""
    from scripts.manifest import _raw_pages

    lib = tmp_path / "mylib"
    pycache = lib / "__pycache__"
    pycache.mkdir(parents=True)
    (lib / "real_page.md").write_text("# real\n", encoding="utf-8")
    (pycache / "phantom.md").write_text("# phantom\n", encoding="utf-8")

    pages = _raw_pages(lib)
    names = [p.name for p in pages]
    assert "real_page.md" in names
    assert "phantom.md" not in names, "__pycache__ content must be excluded"


def test_manifest_and_store_index_agree_on_count(tmp_path):
    """manifest._raw_pages and store_index must agree on page count for a lib
    that contains a _raw_html/ subdirectory."""
    import subprocess
    import sys

    store = tmp_path / "docs"
    lib = store / "testlib"
    raw_html = lib / "_raw_html"
    raw_html.mkdir(parents=True)

    # Two real pages
    (lib / "page_a.md").write_text("# page a\n", encoding="utf-8")
    (lib / "page_b.md").write_text("# page b\n", encoding="utf-8")
    # One _raw_html phantom
    (raw_html / "page_a.html.md").write_text("raw\n", encoding="utf-8")

    # Count via shared helper (manifest path)
    from scripts.manifest import _raw_pages
    manifest_count = len(_raw_pages(lib))

    # Count via store_index render (reads page count from rendered table)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.store_index",
         "--store", str(store), "--out", str(tmp_path / "IDX.md")],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    content = (tmp_path / "IDX.md").read_text(encoding="utf-8")

    # Extract page count from the table row for testlib
    # Row format: | testlib | `XXXX` | N | ...
    import re
    m = re.search(r"\|\s*testlib\s*\|[^|]+\|\s*(\d+)\s*\|", content)
    assert m, f"testlib row not found in:\n{content}"
    store_index_count = int(m.group(1))

    assert manifest_count == 2, f"Expected 2 real pages, got {manifest_count}"
    assert store_index_count == manifest_count, (
        f"manifest count ({manifest_count}) != store_index count ({store_index_count})"
    )
