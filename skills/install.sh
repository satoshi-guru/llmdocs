#!/bin/bash
# install.sh — set up the global doc store + copy Claude Code skills to ~/.claude/skills/
# Run once per machine after cloning llmdocs.

set -e

SKILLS_DIR="$HOME/.claude/skills"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STORE_HOME="${LLMDOCS_HOME:-$HOME/.llmdocs}"

# Preflight: python3 must be on PATH and the engine must be runnable.
command -v python3 >/dev/null 2>&1 || {
  echo "ERROR: python3 not found on PATH. Install Python 3.10+ first." >&2
  exit 1
}
python3 "$REPO_DIR/crawler.py" --help >/dev/null 2>&1 || {
  echo "ERROR: crawler.py not runnable at $REPO_DIR. Check your clone or Python install." >&2
  exit 1
}

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
for skill in docs-fetch docs-prime docs-context docs-distill; do
  mkdir -p "$SKILLS_DIR/$skill"
  # copy SKILL.md + any sibling files (e.g. docs-fetch/PRESETS.md)
  if ! ls "$SCRIPT_DIR/$skill"/*.md >/dev/null 2>&1; then
    echo "  ⚠ $skill: no .md files found in $SCRIPT_DIR/$skill — skipping" >&2
    continue
  fi
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
  if ! (cd "$REPO_DIR" && python3 -m scripts.manifest) >/dev/null 2>&1; then
    echo "  ⚠ manifest rebuild failed (non-fatal — run: cd $REPO_DIR && python3 -m scripts.manifest)" >&2
  fi
fi

echo ""
echo "Done. Skills available in Claude Code:"
echo "  /docs-fetch [lib | url]          — fetch docs into the global store"
echo "  /docs-prime [lib1 lib2 ...]   — fetch → compile → index"
echo "  /docs-context                 — compile LIB-CONTEXT.md from the store"
echo "  /docs-distill [lib]           — build COMPACT.md for fast lookup"
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
# Persist LLMDOCS_DIR into the user's shell profile (idempotent).
PROFILE="${HOME}/.bashrc"
[ -n "${ZSH_VERSION:-}" ] && PROFILE="${HOME}/.zshrc"
LLMDOCS_DIR_LINE="export LLMDOCS_DIR=\"${REPO_DIR}\""
if grep -qF "$LLMDOCS_DIR_LINE" "$PROFILE" 2>/dev/null; then
  echo "  • LLMDOCS_DIR already set in $PROFILE — no change"
else
  printf '\n# llmdocs engine path (added by install.sh)\n%s\n' "$LLMDOCS_DIR_LINE" >> "$PROFILE"
  echo "  ✓ Added LLMDOCS_DIR to $PROFILE"
fi
echo ""
echo "Run: source $PROFILE   (or open a new shell) so the variable is live."
echo ""
echo "Note: fish users must manually add: set -x LLMDOCS_DIR $REPO_DIR"
echo "  to ~/.config/fish/config.fish"
