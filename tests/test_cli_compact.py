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
