#!/bin/bash
# install.sh — set up the global doc store + copy Claude Code skills to ~/.claude/skills/
# Run once per machine after cloning llmdocs.

set -e

SKILLS_DIR="$HOME/.claude/skills"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STORE_HOME="${LLMDOCS_HOME:-$HOME/.llmdocs}"

# 1. Global append-only doc store — shared by every repo, never per-project.
echo "Setting up global doc store at $STORE_HOME/docs ..."
mkdir -p "$STORE_HOME/docs"
mkdir -p "$HOME/.claude"   # may not exist yet on a fresh machine (else the symlink below fails)
# Symlink so the store is reachable from ~/.claude too (one inode, two paths).
if [ ! -e "$HOME/.claude/docs" ]; then
  ln -s "$STORE_HOME/docs" "$HOME/.claude/docs"
  echo "  ✓ symlink ~/.claude/docs -> $STORE_HOME/docs"
else
  echo "  • ~/.claude/docs already exists — leaving as is"
fi

# 2. Skills.
echo "Installing llmdocs Claude Code skills to $SKILLS_DIR..."
for skill in llmdoc doc-prime lib-context doc-indexer; do
  mkdir -p "$SKILLS_DIR/$skill"
  # copy SKILL.md + any sibling files (e.g. llmdoc/PRESETS.md)
  cp "$SCRIPT_DIR/$skill"/*.md "$SKILLS_DIR/$skill/"
  echo "  ✓ $skill"
done

# 3. Agents (optional Claude Code integration folded in from the repo).
if compgen -G "$REPO_DIR/agents/*.md" >/dev/null 2>&1; then
  echo "Installing llmdocs agents to $HOME/.claude/agents..."
  mkdir -p "$HOME/.claude/agents"
  cp "$REPO_DIR/agents/"*.md "$HOME/.claude/agents/"
  for a in "$REPO_DIR/agents/"*.md; do echo "  ✓ $(basename "$a" .md)"; done
fi

# 4. Manifest (index of everything gathered so far).
if [ -f "$REPO_DIR/scripts/manifest.py" ]; then
  (cd "$REPO_DIR" && python3 -m scripts.manifest) >/dev/null 2>&1 || true
fi

echo ""
echo "Done. Skills available in Claude Code:"
echo "  /llmdoc [lib | url]          — fetch docs into the global store"
echo "  /doc-prime [lib1 lib2 ...]   — fetch → compile → index"
echo "  /lib-context                 — compile LIB-CONTEXT.md from the store"
echo "  /doc-indexer [lib]           — build COMPACT.md for fast lookup"
echo ""
echo "IMPORTANT — one-time permission grant so EVERY repo's session can write"
echo "to the store (otherwise Write/Edit is sandboxed to the current project):"
echo "add this to ~/.claude/settings.json under \"permissions\":"
echo ""
echo '    "additionalDirectories": ["'"$STORE_HOME"'", "'"$HOME"'/.claude/docs"]'
echo ""
echo "Store: $STORE_HOME/docs   ·   manifest: $STORE_HOME/MANIFEST.md"
echo "Override the store location anywhere with \$LLMDOCS_HOME."
echo ""
echo "IMPORTANT — the skills locate the engine via \$LLMDOCS_DIR. Add this to your"
echo "shell profile (~/.bashrc, ~/.zshrc) so every Claude Code session sees it:"
echo ""
echo "    export LLMDOCS_DIR=\"$REPO_DIR\""
