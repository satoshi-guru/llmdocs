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
