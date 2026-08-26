#!/usr/bin/env bash
# Put the demo back to its starting state.
#
#   Code:    site/ restored to the plain baseline (tag: demo-baseline)
#   Jira:    every ticket labelled demo-scope back to To Do
#   Confluence: regenerated from the restored history
#
# Nothing is lost. The polished design lives on the design-v1 tag, and this
# script never touches it.
#
# Usage:
#   scripts/reset-demo.sh           # local only
#   scripts/reset-demo.sh --push    # also reset the remote (force-with-lease)
#   scripts/reset-demo.sh --yes     # skip the confirmation prompt

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PUSH=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

BASELINE="demo-baseline"
if ! git rev-parse -q --verify "refs/tags/$BASELINE" >/dev/null; then
  echo "✗ tag '$BASELINE' not found. Nothing to reset to." >&2
  echo "  Create it at the plain-site commit:  git tag $BASELINE <sha>" >&2
  exit 1
fi

BASE_SHA="$(git rev-parse --short "$BASELINE")"
HEAD_SHA="$(git rev-parse --short HEAD)"
AHEAD="$(git rev-list --count "$BASELINE"..HEAD)"

echo "Reset plan"
echo "  baseline      $BASELINE ($BASE_SHA)"
echo "  current HEAD  $HEAD_SHA  ($AHEAD commit(s) ahead)"
echo "  local git     hard reset to $BASELINE"
if [ "$PUSH" -eq 1 ]; then
  echo "  remote git    force-with-lease push  <-- REWRITES REMOTE HISTORY"
else
  echo "  remote git    untouched (pass --push to reset it too)"
fi
echo "  jira          demo-scope tickets -> To Do"
echo "  confluence    regenerated from restored history"
echo

if [ "$AHEAD" -eq 0 ] && [ "$(git status --porcelain | wc -l | tr -d ' ')" -eq 0 ]; then
  echo "Already at the baseline with a clean tree. Only Jira and Confluence will be reset."
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  printf 'Proceed? [y/N] '
  read -r reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "aborted"; exit 0 ;;
  esac
fi

# ---------------------------------------------------------------- credentials
if [ -f .atlassian.env ]; then
  set -a
  # shellcheck disable=SC1091
  source .atlassian.env
  set +a
fi
if [ -z "${ATLASSIAN_EMAIL:-}" ] || [ -z "${ATLASSIAN_API_TOKEN:-}" ]; then
  echo "✗ ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN not set (see docs/SETUP.md)" >&2
  exit 1
fi

SITE="affirma-demo.atlassian.net"
AUTH="$(printf '%s:%s' "$ATLASSIAN_EMAIL" "$ATLASSIAN_API_TOKEN" | base64)"
TODO_TRANSITION="21"   # To Do

# ---------------------------------------------------------------------- git
echo
echo "▸ git"
# The hook would fire a sync mid-reset and re-advance the tickets we are about
# to move back. Suppress it for the duration.
export SKIP_ATLASSIAN_SYNC=1
git reset --hard "$BASELINE" >/dev/null
git clean -fd site >/dev/null 2>&1 || true
echo "    reset to $BASELINE ($BASE_SHA)"

if [ "$PUSH" -eq 1 ]; then
  git push --force-with-lease origin main
  echo "    remote reset"
fi

# --------------------------------------------------------------------- jira
echo
echo "▸ jira"
KEYS="$(curl -sS -H "Authorization: Basic $AUTH" \
  --get "https://$SITE/rest/api/3/search/jql" \
  --data-urlencode 'jql=project = SIDC AND labels = "demo-scope"' \
  --data-urlencode 'fields=key' \
  | python3 -c 'import json,sys; print(" ".join(i["key"] for i in json.load(sys.stdin).get("issues",[])))')"

if [ -z "$KEYS" ]; then
  echo "    no demo-scope tickets found"
else
  for k in $KEYS; do
    curl -sS -o /dev/null -X POST \
      -H "Authorization: Basic $AUTH" -H 'Content-Type: application/json' \
      -d "{\"transition\":{\"id\":\"$TODO_TRANSITION\"}}" \
      "https://$SITE/rest/api/3/issue/$k/transitions"
    printf '    %s -> To Do\n' "$k"
  done
fi

# --------------------------------------------------------------- confluence
echo
echo "▸ confluence"
python3 scripts/atlassian_sync.py --skip-jira --range HEAD..HEAD >/dev/null
echo "    regenerated from restored history"

echo
echo "✓ demo reset. Preview the plain baseline with:"
echo "    python3 -m http.server 8899 --directory site"
