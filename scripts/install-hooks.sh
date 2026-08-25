#!/usr/bin/env bash
# Point git at the tracked hooks in .githooks/ instead of the untracked
# .git/hooks/. One line of config, and hooks travel with the repo.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

chmod +x .githooks/* 2>/dev/null || true
git config core.hooksPath .githooks

echo "✓ core.hooksPath = .githooks"
echo "  hooks installed:"
for h in .githooks/*; do
  [ -f "$h" ] && echo "    - $(basename "$h")"
done

if [ ! -f .atlassian.env ]; then
  cat <<'EOF'

Next: create .atlassian.env in the repo root (it is git-ignored):

    ATLASSIAN_EMAIL=you@example.com
    ATLASSIAN_API_TOKEN=<token from id.atlassian.com/manage-profile/security/api-tokens>

Without it the hook skips quietly and CI does the sync on push instead.
EOF
else
  echo "  .atlassian.env found"
fi

echo
echo "Test it without touching Atlassian:"
echo "    python3 scripts/atlassian_sync.py --all --dry-run"
