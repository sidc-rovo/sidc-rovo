# Setup — commit-driven Jira + Confluence sync

Everything here is already in the repo. This is the wiring you do once.

## What's connected

| Thing | Where |
|---|---|
| Site source | `site/` — plain HTML/CSS/JS, no build step |
| Jira project | [SIDC](https://affirma-demo.atlassian.net/jira/core/projects/SIDC/board) (business project) |
| Confluence space | [SIDC](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/overview) |
| Sync engine | `scripts/atlassian_sync.py` — stdlib only |
| On commit | `.githooks/post-commit` (instant, local) |
| On push | `.github/workflows/atlassian-sync.yml` (authoritative, logged) |
| Site deploy | `.github/workflows/pages.yml` |

## 1. Get an Atlassian API token

<https://id.atlassian.com/manage-profile/security/api-tokens> → **Create API token**.

This token can write to Jira and Confluence as you, so treat it like a password.
It is never committed — the two places it goes are a git-ignored local file and
GitHub's encrypted secrets.

## 2. Local hook

```bash
scripts/install-hooks.sh
```

Then create `.atlassian.env` in the repo root (already in `.gitignore`):

```
ATLASSIAN_EMAIL=schaturvedi2@atlassian.com
ATLASSIAN_API_TOKEN=your-token-here
```

Verify the credentials resolve to the right account:

```bash
python3 scripts/atlassian_sync.py --check
```

That calls `/myself` and confirms both the Jira project and the Confluence space
are visible, then exits without writing anything. Do this before anything else —
a bad token otherwise surfaces later as Jira's misleading *"target project
doesn't exist or you don't have permission"*.

To test the logic with no credentials at all:

```bash
python3 scripts/atlassian_sync.py --all --dry-run
```

## 3. CI secrets

```bash
gh secret set ATLASSIAN_EMAIL --body "schaturvedi2@atlassian.com" --repo sidc-rovo/sidc-rovo
```

```bash
gh secret set ATLASSIAN_API_TOKEN --repo sidc-rovo/sidc-rovo
```

The second command prompts for the value so the token never lands in your shell
history. Paste it, press Enter, then Ctrl-D.

## 4. Pages — done

Already enabled with Source: GitHub Actions, and deployed. Live at
**<https://sidc-rovo.github.io/sidc-rovo/>**

It redeploys on every push that touches `site/`. Nothing further to do here.

## 5. First full sync

```bash
python3 scripts/atlassian_sync.py --all
```

This backfills every commit so far, creates the two Confluence pages, and writes
`site/build-info.json`.

---

## How it behaves

**Confluence pages are derived state.** `Release Log` and `Changelog by Commit`
are regenerated *in full* from `git log` on every run. They cannot drift, and
re-running is always safe. The flip side: hand edits to those two pages get
overwritten. Edit the repo, not the page.

**Jira issues are deduplicated by SHA.** Every auto-filed Task carries a
`sha-<short>` label. Before creating anything the script queries for that label,
so re-running never double-files. Tasks hang under a `Workstream` called
*"sidc.ai website — build & release"*, created on first run.

**Reference an issue to attach to it instead.** Put `SIDC-12` in a commit
message and the script comments on `SIDC-12` rather than opening a new Task.
That's the normal path once real work has tickets.

**Changed paths become areas and labels.** The `areas` array in
`atlassian.config.json` maps path prefixes to names — `site/styles.css` becomes
*Design system*, `.github/workflows/` becomes *CI / automation*. Areas show up
in the Jira labels, the Confluence tables, and the site's Delivery panel.

**The site reports its own state.** The sync writes `site/build-info.json`;
`site/app.js` fetches it and fills the Delivery panel. Before the first sync the
panel says so instead of erroring.

## Commands

```bash
python3 scripts/atlassian_sync.py                        # last commit only
python3 scripts/atlassian_sync.py --all                  # whole history
python3 scripts/atlassian_sync.py --range abc123..HEAD   # explicit range
python3 scripts/atlassian_sync.py --dry-run              # no network writes
python3 scripts/atlassian_sync.py --skip-confluence      # Jira only
python3 scripts/atlassian_sync.py --skip-jira            # Confluence only
```

Skip the hook for one commit:

```bash
SKIP_ATLASSIAN_SYNC=1 git commit -m "wip"
```

Re-sync everything from CI: **Actions → Atlassian sync → Run workflow →
`resync_all: true`**.

## Preview the site locally

```bash
python3 -m http.server 8000 --directory site
```

## Troubleshooting

**401 on every call** — the email/token pair is wrong, or the token was revoked.
Note it's the *account* email, not a display name. Run `--check` to see which
account the credentials actually resolve to.

Two gotchas that produce a 401 with credentials that look correct:

- **A truncated token.** Atlassian tokens are long; a partial paste fails the
  same way a wrong one does.
- **The wrong kind of token.** This needs a classic API token from
  `id.atlassian.com/manage-profile/security/api-tokens`. A scoped or Rovo token
  will not authenticate against these endpoints.

**403 on Jira create** — the account can see `SIDC` but can't create issues in
it. Check project permissions.

**`Confluence space 'SIDC' not found`** — the token's account lacks space access,
or the key changed.

**Parent rejected on issue create** — the script retries once without the parent
rather than dropping the issue, and logs that it did. If it happens every run,
check that `Workstream` still exists as a hierarchy-level-1 type in `SIDC`.

**Two syncs racing** — the workflow uses a `concurrency` group so Confluence
version numbers can't collide. Don't remove it.
