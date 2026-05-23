#!/bin/bash
# install.sh — copy Claude Code skills to ~/.claude/skills/
# Run once per machine after cloning llmdocs.

set -e

SKILLS_DIR="$HOME/.claude/skills"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing llmdocs Claude Code skills to $SKILLS_DIR..."

for skill in doc-prime lib-context doc-indexer; do
  mkdir -p "$SKILLS_DIR/$skill"
  cp "$SCRIPT_DIR/$skill/SKILL.md" "$SKILLS_DIR/$skill/SKILL.md"
  echo "  ✓ $skill"
done

echo ""
echo "Done. Skills available in Claude Code:"
echo "  /doc-prime [lib1 lib2 ...]   — fetch → compile → index"
echo "  /lib-context                  — compile LIB-CONTEXT.md from docs/"
echo "  /doc-indexer [lib]            — build COMPACT.md for fast lookup"
echo ""
echo "Update llmdocs path in doc-prime/SKILL.md if llmdocs is not at:"
echo "  /home/rootvault/Dokumente/llmdocs/"
