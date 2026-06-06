import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(args, cwd, stdin=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "llmdocs.py"), *args],
        capture_output=True, text=True, cwd=cwd, input=stdin,
    )


def test_compact_min_stdin_to_stdout():
    r = _run(["--compact", "min", "-"], cwd=ROOT, stdin="# T\n\n\nbody\n\n")
    assert r.returncode == 0
    assert "# T" in r.stdout and "\n\n\n" not in r.stdout


def test_compact_dense_writes_sibling(tmp_path):
    src = tmp_path / "page.md"
    src.write_text("## Auth\n\n| k | v |\n| - | - |\n| a | 1 |\n")
    r = _run(["--compact", "dense", str(src)], cwd=ROOT)
    assert r.returncode == 0
    out = src.with_suffix(".dense.md")
    assert out.exists()
    body = out.read_text()
    assert "[2|Auth]" in body and "k,v" in body


def test_compact_dir_skips_reserved(tmp_path):
    (tmp_path / "a.md").write_text("# A\n")
    (tmp_path / "COMPACT.md").write_text("# do not touch\n")
    r = _run(["--compact", "min", str(tmp_path)], cwd=ROOT)
    assert r.returncode == 0
    assert (tmp_path / "a.min.md").exists()
    assert not (tmp_path / "COMPACT.min.md").exists()  # reserved file skipped


def test_expand_roundtrips_stdin():
    r = _run(["--expand", "-"], cwd=ROOT, stdin="[2|H]\nk,v\na,1\n")
    assert r.returncode == 0
    assert "## H" in r.stdout and "| k | v |" in r.stdout


def test_check_passes_on_committed_fixture():
    # --check asserts idempotence: minify(page) == page.
    # The committed fixture is already min-normalised so exit 0 is expected.
    r = _run(["--check", "store/example/alpha-lib/page.md"], cwd=ROOT)
    assert r.returncode == 0, f"idempotence check failed on fresh checkout: {r.stdout}{r.stderr}"


def test_check_fails_on_non_normalised_page(tmp_path):
    # A page with extra blank lines is NOT min-normalised → exit 1.
    src = tmp_path / "page.md"
    src.write_text("# Title\n\n\nbody text\n\n\n")
    r = _run(["--check", str(src)], cwd=ROOT)
    assert r.returncode == 1, f"expected exit 1 for non-normalised page, got: {r.stdout}{r.stderr}"
    assert "DRIFT" in r.stderr


def test_expand_does_not_overwrite_input(tmp_path):
    src = tmp_path / "doc.dense.md"
    src.write_text("[2|H]\nk,v\na,1\n")
    before = src.read_text()
    r = _run(["--expand", str(src)], cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert src.read_text() == before, "--expand must not overwrite its own input file"
    assert (tmp_path / "doc.md").exists(), "expand of doc.dense.md should write doc.md"


def test_compact_min_noop_on_clean_doc():
    # Fetch-time --raw skips compaction entirely; at the compaction CLI the analogous
    # invariant is that `min` on an already-clean doc returns it byte-for-byte (no spurious edits).
    clean = "# T\n\nbody\n"
    r = _run(["--compact", "min", "-"], cwd=ROOT, stdin=clean)
    assert r.returncode == 0
    assert r.stdout == clean, f"min added/dropped bytes on a clean doc: {r.stdout!r}"


def test_compact_min_stdin_exact_output():
    # tests-F6: tighten the weak `"# T" in stdout` assertion to a full-output compare.
    r = _run(["--compact", "min", "-"], cwd=ROOT, stdin="# T\n\n\nbody\n\n")
    assert r.returncode == 0
    assert r.stdout == "# T\n\nbody\n"
