#!/bin/bash
# compare_engines.sh — A/B[/C/D] a doc crawl across multiple llmdocs engine
# versions on the SAME url, simultaneously (so site drift hits all engines
# equally), into isolated sandbox dirs. Reports distinct files, INDEX rows
# (truthful?), asset-junk count, and pairwise file overlap vs the reference engine.
#
# Engines are given as NAME=PATH pairs via $ENGINES (space-separated). Each PATH is
# a llmdocs.py. The LAST engine is the reference for overlap (diff vs it).
#
# Usage:
#   ENGINES="1b=/sandbox/engine-1b.py 3=/repo/llmdocs.py" \
#     ./compare_engines.sh <slug> <url> [extra llmdocs args...]
# Env: PY (python, default python3), OUT (sandbox root, default ./bench-out)
set -u
slug="$1"; url="$2"; shift 2; extra="$*"
PY="${PY:-python3}"; OUT="${OUT:-./bench-out}"; ENGINES="${ENGINES:?set ENGINES=\"name=path ...\"}"
base="$OUT/$slug"; rm -rf "$base"; mkdir -p "$base"
names=(); dirs=()
for pair in $ENGINES; do
  name="${pair%%=*}"; eng="${pair##*=}"; d="$base/$name"; mkdir -p "$d"
  ( cd "$(dirname "$eng")" && LLMDOCS_HOME="$d/home" timeout 600 "$PY" "$eng" \
      --url "$url" $extra --out "$d/$slug" ) >"$base/$name.log" 2>&1 &
  names+=("$name"); dirs+=("$d/$slug")
done
wait
files(){ find "$1" -name '*.md' ! -name INDEX.md ! -name COMPACT.md ! -name LOOKUP.md 2>/dev/null; }
idx(){ grep -cE '^- \[' "$1/INDEX.md" 2>/dev/null || echo 0; }
asset(){ find "$1" -name '*.md' 2>/dev/null | grep -icE '\.(png|jpe?g|gif|pdf|zip|woff2?|css|js|svg|gz|tar)\.md$'; }
ref="${dirs[-1]}"
for i in "${!names[@]}"; do
  d="${dirs[$i]}"; f=$(files "$d"|wc -l); ix=$(idx "$d"); as=$(asset "$d")
  ok=$([ "$f" = "$ix" ] && echo OK || echo DUP)
  only=$(comm -23 <(cd "$d"&&files .|sed 's#^\./##'|sort) <(cd "$ref"&&files .|sed 's#^\./##'|sort) 2>/dev/null|wc -l)
  printf '%-6s files=%-4s index=%-4s(%s) assets=%-3s only-vs-ref=%s\n' \
    "${names[$i]}" "$f" "$ix" "$ok" "$as" "$only"
done
