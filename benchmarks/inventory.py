#!/usr/bin/env python3
"""Size-sorted inventory of the global doc store, with an INDEX-drift flag.

For every slug in $LLMDOCS_HOME/docs (default ~/.llmdocs/docs) prints: files on
disk, INDEX `Pages:` header, a DUP flag when they disagree, fetch date (INDEX
mtime), and the original Source URL. Smallest-first — the order to re-fetch /
benchmark in. Read-only.

Usage:  python benchmarks/inventory.py
        LLMDOCS_HOME=/some/where python benchmarks/inventory.py
"""
from __future__ import annotations
import datetime, glob, os, re
home = os.path.expanduser(os.environ.get("LLMDOCS_HOME") or "~/.llmdocs")
root = home if os.path.basename(home.rstrip("/")) == "docs" else os.path.join(home, "docs")
rows = []
for d in sorted(os.listdir(root)):
    p = os.path.join(root, d); idx = os.path.join(p, "INDEX.md")
    if not os.path.isdir(p) or not os.path.isfile(idx):
        continue
    txt = open(idx, encoding="utf-8", errors="replace").read()
    m = re.search(r"Source:\s*(\S+)", txt); src = m.group(1) if m else "?"
    m = re.search(r"Pages:\s*(\d+)", txt); hdr = int(m.group(1)) if m else -1
    disk = sum(1 for f in glob.glob(os.path.join(p, "**", "*.md"), recursive=True)
               if os.path.basename(f) not in ("INDEX.md", "COMPACT.md", "LOOKUP.md"))
    dt = datetime.date.fromtimestamp(os.path.getmtime(idx)).isoformat()
    rows.append((disk, d, hdr, src, dt))
rows.sort()
print(f"{'disk':>5} {'hdr':>5} {'dup?':>4}  {'date':10}  {'slug':24} url")
for disk, d, hdr, src, dt in rows:
    dup = "DUP" if hdr != disk and hdr >= 0 else ""
    print(f"{disk:5d} {hdr:5d} {dup:>4}  {dt:10}  {d:24} {src}")
print(f"\nTOTAL slugs={len(rows)}  disk_pages={sum(r[0] for r in rows)}")
