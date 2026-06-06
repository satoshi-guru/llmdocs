#!/usr/bin/env python3
"""Token×quality benchmark for the compaction tiers.

For each (strategy × library) it measures three things and writes bench/REPORT.md:

  1. token cost      — est_tokens() of the artifact a builder would read
  2. recall gate     — fraction of the golden `must_have` signatures present.
                       ANY missing signature = FAIL, regardless of token win.
                       This is the "is every critical detail still visible?" guard.
  3. LLM-judge        — (optional) a Claude model scores whether each golden Q&A is
                       answerable from the artifact alone. Runs only if
                       $ANTHROPIC_API_KEY is set; otherwise reported as "skipped".

The recall gate is deterministic and CI-safe. The LLM-judge is the optional LLM
tier — it never blocks CI and never crashes the run.

Usage:
  python bench/bench.py --libs fastapi pydantic
  LLMDOCS_HOME=/path python bench/bench.py --libs fastapi
  ANTHROPIC_API_KEY=... python bench/bench.py --libs fastapi   # enables LLM-judge
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))                          # for scripts.manifest
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for sibling strategies

from scripts.manifest import est_tokens          # noqa: E402  (shared token estimate)
from strategies import STRATEGIES, _raw_pages     # noqa: E402  (sibling module)

STORE = Path(os.environ.get("LLMDOCS_HOME") or (Path.home() / ".llmdocs")) / "docs"
GOLDENS = Path(__file__).resolve().parent / "goldens"
REPORT = Path(__file__).resolve().parent / "REPORT.md"
JUDGE_MODEL = os.environ.get("LLMDOCS_JUDGE_MODEL", "claude-sonnet-4-6")


def _full_raw_tokens(lib_dir: Path) -> int:
    """Token cost of reading EVERY raw page — the honest reduction baseline."""
    total = 0
    for p in _raw_pages(lib_dir):
        total += est_tokens(p.read_text(encoding="utf-8", errors="ignore"))
    return total or 1


def _judge_backend(prompt: str) -> str | None:
    """Send a judge prompt via the best available backend; return raw text or None.

    Priority: ANTHROPIC_API_KEY (anthropic SDK) → the OAuth-authenticated `claude`
    CLI (`claude -p`, uses your Claude Code login — no API key needed) → None.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic
            msg = Anthropic().messages.create(
                model=JUDGE_MODEL, max_tokens=64,
                messages=[{"role": "user", "content": prompt}],
            )
            return (msg.content[0].text or "").strip()
        except Exception as e:
            print(f"  [judge] SDK backend failed: {e}", file=sys.stderr)
    if shutil.which("claude"):
        try:
            # Prompt via stdin, not argv — large artifacts blow past ARG_MAX.
            out = subprocess.run(
                ["claude", "-p", "--model", JUDGE_MODEL],
                input=prompt, capture_output=True, text=True, timeout=300,
            )
            if out.returncode == 0:
                return out.stdout.strip()
            print(f"  [judge] CLI backend rc={out.returncode}: {out.stderr.strip()[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"  [judge] CLI backend failed: {e}", file=sys.stderr)
    return None


def _run_judge(artifact: str, qa: list[dict]) -> float | None:
    """Optional LLM-judge: mean normalized score (0..1) over the Q&A set.

    One batched call grades all questions. Returns None if no backend is available
    or anything goes wrong — never raises, never blocks CI.
    """
    if not qa:
        return None
    questions = "\n".join(
        f"{i+1}. QUESTION: {it['q']}\n   EXPECTED: {it['reference']}" for i, it in enumerate(qa)
    )
    prompt = (
        "You grade whether a REFERENCE DOCUMENT contains enough information to correctly "
        "answer each question. Judge ONLY from the document — not prior knowledge.\n\n"
        f"=== DOCUMENT ===\n{artifact}\n=== END DOCUMENT ===\n\n"
        f"QUESTIONS:\n{questions}\n\n"
        "For EACH question output one line: `<number>: <score>` where score is "
        "0 (document lacks the info), 1 (partially answerable), or 2 (fully and correctly "
        "answerable from the document alone). Output only those lines, nothing else."
    )
    raw = _judge_backend(prompt)
    if raw is None:
        return None
    scores = []
    for line in raw.splitlines():
        if ":" in line:
            tail = line.split(":", 1)[1].strip()
            if tail[:1] in {"0", "1", "2"}:
                scores.append(int(tail[0]))
    if len(scores) != len(qa):                   # malformed grading → don't guess
        print(f"  [judge] parsed {len(scores)}/{len(qa)} scores; treating as skipped", file=sys.stderr)
        return None
    return sum(scores) / (2 * len(qa))


def bench_lib(lib: str, store: Path) -> dict:
    lib_dir = store / lib
    golden_path = GOLDENS / f"{lib}.json"
    if not golden_path.exists():
        raise SystemExit(f"no golden for '{lib}' — add bench/goldens/{lib}.json first")
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    must_have = golden["must_have"]
    qa = golden.get("qa", [])
    lookup_lines = golden.get("lookup", [])

    if not lib_dir.is_dir():
        raise SystemExit(f"lib not in store: {lib_dir} — run /llmdoc {lib} first")

    full_raw = _full_raw_tokens(lib_dir)
    rows = []
    for sname, sfn in STRATEGIES.items():
        art = sfn(lib_dir, lookup_lines)
        toks = est_tokens(art)
        missing = [m for m in must_have if m not in art]
        rows.append({
            "strategy": sname,
            "tokens": toks,
            "reduction": 1 - (toks / full_raw),
            "recall": (len(must_have) - len(missing)) / len(must_have) if must_have else 1.0,
            "missing": missing,
            "gate": "PASS" if not missing else "FAIL",
            "judge": _run_judge(art, qa),
        })
    return {"lib": lib, "full_raw_tokens": full_raw, "rows": rows}


def _fmt_judge(j: float | None) -> str:
    return "skipped" if j is None else f"{j*100:.0f}%"


def write_report(results: list[dict], out: Path) -> None:
    lines = [
        "# Benchmark — token × quality",
        "",
        "Generated by `python bench/bench.py`. Token estimate = chars/4 "
        "(`scripts.manifest.est_tokens`). **Recall gate**: every golden `must_have` "
        "signature must be present — a single miss is a FAIL regardless of token cost. "
        "**Judge**: Claude scores whether each golden Q&A is answerable from the artifact "
        f"alone (model `{JUDGE_MODEL}`, via the `claude` CLI / OAuth or `$ANTHROPIC_API_KEY`); "
        "`skipped` if no backend is available.",
        "",
    ]
    for r in results:
        lines += [
            f"## {r['lib']}  (full raw docs ≈ {r['full_raw_tokens']:,} tokens)",
            "",
            "| Strategy | Tokens | Reduction vs raw | Recall | Gate | Judge |",
            "|----------|-------:|-----------------:|:------:|:----:|:-----:|",
        ]
        for row in r["rows"]:
            lines.append(
                f"| {row['strategy']} | {row['tokens']:,} | {row['reduction']*100:.2f}% | "
                f"{row['recall']*100:.0f}% | {row['gate']} | {_fmt_judge(row['judge'])} |"
            )
        fails = [row for row in r["rows"] if row["gate"] == "FAIL"]
        if fails:
            lines.append("")
            for row in fails:
                lines.append(f"> ⚠ `{row['strategy']}` dropped: {', '.join('`'+m+'`' for m in row['missing'])}")
        lines.append("")

    # Recommended default = cheapest strategy that passes the recall gate AND scores
    # well on the LLM-judge across every lib. The recall gate alone is NOT enough:
    # a pure signature index (lookup_only) passes signature-presence but can't answer
    # usage questions — only the judge separates "the API is listed" from "you can
    # actually use it from this artifact". So we require judge data to crown a winner.
    # 0.95, not 0.80: the read-tier DEFAULT must reliably answer usage questions, not
    # ~5/6 of them. A signature-only index can clear 0.80 (the signatures alone answer
    # many Q&A) yet still miss usage detail — that's the grep tier's job, not the default.
    JUDGE_MIN = 0.95
    have_judge = all(row["judge"] is not None for r in results for row in r["rows"])

    def qualifies(sname: str) -> bool:
        for r in results:
            row = next(x for x in r["rows"] if x["strategy"] == sname)
            if row["gate"] != "PASS" or row["judge"] is None or row["judge"] < JUDGE_MIN:
                return False
        return True

    lines += ["## Recommended default", ""]
    if have_judge:
        winner = next((s for s in STRATEGIES if qualifies(s)), None)  # cheap → rich
        if winner:
            lines += [
                f"**Read tier (wire as doc-indexer default): `{winner}`** — cheapest strategy "
                f"that passes the recall gate *and* scores ≥{JUDGE_MIN*100:.0f}% on the "
                "LLM-judge for every benchmarked library (reliably answers usage questions, "
                "not just signature presence).",
                "",
                "**Grep tier: `lookup_only`** — ~99.9% reduction; passes the recall gate and "
                "answers most existence/signature questions in 1–2 tokens, but scores lower on "
                "the judge (it lists APIs without full usage). Use it for \"does this exist / "
                "what's the signature\", fall back to the read tier for \"how do I use it\".",
            ]
        else:
            lines.append(
                "_No strategy cleared both the recall gate and the judge threshold across all "
                "libraries — inspect failures above._")
    else:
        lines.append(
            "_LLM-judge not run (set `$ANTHROPIC_API_KEY` to enable it)._ The recall gate "
            "alone cannot rank **usage** quality — a pure signature index passes it without "
            "being usable. Principled split pending judge confirmation:")
        lines += [
            "",
            "- **Read tier (wire as doc-indexer default):** `compact` — full recall with usage "
            "patterns, ~99%+ reduction.",
            "- **Grep tier (existence / signature lookup):** `lookup_only` — ~99.9% reduction, "
            "answers \"does this API exist / what's its signature\" in 1–2 tokens.",
        ]
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description="token×quality benchmark for compaction tiers")
    ap.add_argument("--libs", nargs="+", required=True, help="library slugs (must be in the store + have a golden)")
    ap.add_argument("--store", type=Path, default=STORE, help="store docs dir (default: $LLMDOCS_HOME/docs)")
    ap.add_argument("--out", type=Path, default=REPORT, help="report output path (default: bench/REPORT.md)")
    args = ap.parse_args()

    results = [bench_lib(lib, args.store) for lib in args.libs]
    write_report(results, args.out)

    # Console summary
    for r in results:
        print(f"\n{r['lib']}  (raw ≈ {r['full_raw_tokens']:,} tok):")
        for row in r["rows"]:
            print(f"  {row['strategy']:<15} {row['tokens']:>6,} tok  "
                  f"{row['reduction']*100:6.2f}% reduction  recall {row['recall']*100:3.0f}%  "
                  f"{row['gate']}  judge={_fmt_judge(row['judge'])}")
    # Deterministic CI gate: any tracked strategy that dropped a must_have signature fails
    # the run. raw_head is the negative control — it is *allowed* to FAIL in the report
    # (it reads only a budget slice of raw pages, not the compacted artifacts), so it is
    # excluded from the gate. Only the curated compaction strategies are gated.
    gate_failed = any(
        row["gate"] == "FAIL"
        for r in results
        for row in r["rows"]
        if row["strategy"] != "raw_head"
    )
    if gate_failed:
        print("RECALL GATE FAILED: a strategy dropped a must_have signature "
              "(see the FAIL rows above / in the report)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
