# tests/test_bench_exit.py
import subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def test_bench_exits_nonzero_when_recall_gate_fails(tmp_path):
    # Temp store whose alpha-lib page can NEVER contain the committed golden's
    # must_have signatures -> every strategy drops them -> recall gate FAIL.
    lib = tmp_path / "alpha-lib"; lib.mkdir(parents=True)
    (lib / "page.md").write_text("# alpha-lib\nNothing useful here.\n")
    r = subprocess.run(
        [sys.executable, "bench/bench.py", "--libs", "alpha-lib",
         "--store", str(tmp_path), "--out", str(tmp_path / "out.md")],
        cwd=REPO, capture_output=True, text=True)
    assert r.returncode != 0, f"expected non-zero exit on FAIL, got 0\n{r.stdout}\n{r.stderr}"


def test_bench_handles_empty_must_have(tmp_path):
    # A golden with empty must_have must NOT crash with ZeroDivisionError.
    # Exercise the guard via a unit-level import+monkeypatch (no --golden flag exists).
    import importlib, json, sys
    sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "bench"))
    bench = importlib.import_module("bench")
    # monkeypatch GOLDENS to a temp dir holding an empty-must_have golden
    gdir = tmp_path / "goldens"; gdir.mkdir()
    (gdir / "lib.json").write_text(json.dumps({"lib": "lib", "must_have": [], "qa": []}))
    lib = tmp_path / "store" / "lib"; lib.mkdir(parents=True)
    (lib / "page.md").write_text("# lib\n")
    bench.GOLDENS = gdir
    res = bench.bench_lib("lib", tmp_path / "store")  # must not raise ZeroDivisionError
    assert all(row["recall"] == 1.0 for row in res["rows"])


def test_bench_clear_error_on_missing_golden(tmp_path):
    r = subprocess.run([sys.executable, "bench/bench.py", "--libs", "no_such_lib",
                        "--store", str(tmp_path), "--out", str(tmp_path / "o.md")],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode != 0
    assert "no golden for 'no_such_lib'" in r.stderr, r.stderr
