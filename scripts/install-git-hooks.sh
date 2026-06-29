#!/usr/bin/env bash
# Install the repo's git hooks (security/data-leak guardrail) into .git/hooks.
# Run once after cloning:  bash scripts/install-git-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/hooks"
DST="$(git rev-parse --git-path hooks)"

for hook in "$SRC"/*; do
  name="$(basename "$hook")"
  cp "$hook" "$DST/$name"
  chmod +x "$DST/$name"
  echo "installed: $name -> $DST/$name"
done

# Verify the gate's own evals are green before trusting it.
python3 "$REPO_ROOT/scripts/security_gate.py" --self-test
echo "git hooks installed. Pushes are now scanned for secrets / personal data."
