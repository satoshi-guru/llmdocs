"""scripts/query.py — offline resolve/query/page over a temp store (the program's own --selftest)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_query_selftest() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "query.py"), "--selftest"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest ok" in r.stdout


def test_missing_exit_code(tmp_path: Path) -> None:
    env = {"LLMDOCS_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "query.py"), "resolve", "nothing-here"], capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 3 and "llmdoc" in r.stdout
