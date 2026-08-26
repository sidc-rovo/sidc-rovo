# Working in this repo

This is Sid's personal website plus the machinery that keeps its **system of
work** — Jira and Confluence — in step with the code automatically.

If you are a fresh session picking this up: read this whole file first. It is
short, and it is the difference between "it just works" and a mess.

---

## The one rule that makes everything work

**Every commit message must name the Jira ticket it delivers.**

```
Make the site answer-engine ready

SIDC-15
```

That reference is the entire coupling mechanism. With it, the ticket gets a
comment linking the commit, moves `To Do → In Progress → Done`, and Confluence
records what shipped against what was planned. Without it, the commit is treated
as unplanned work and logged as scope divergence instead.

Never invent a ticket key. Look it up (below) or ask.

### Record decisions as you make them

If you made a real choice — picked an approach, rejected an alternative, accepted
a tradeoff — add a `Decision:` line. One line each, in the commit body.

```
Rebuild the design system from tokens

Decision: no CSS framework — three static files outlive any dependency
Decision: light mode re-picked rather than inverted, because the accent fails on white

SIDC-16
```

These are collected automatically into the **Decision Log** page in Confluence
and into `docs/releases/`. This is the cheapest form of architecture decision
record that anyone actually keeps up, so use it — but only for genuine choices.
Do not narrate the obvious.

---

## Coordinates

| | |
|---|---|
| Atlassian site | `affirma-demo.atlassian.net` |
| Jira project | **SIDC** — [board](https://affirma-demo.atlassian.net/jira/core/projects/SIDC/board) |
| Confluence space | **SIDC** — [space](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/overview) |
| Parent Workstream | `SIDC-1` |
| GitHub | [sidc-rovo/sidc-rovo](https://github.com/sidc-rovo/sidc-rovo) |
| Live site | <https://sidc-rovo.github.io/sidc-rovo/> |
| Ticket states | `To Do` → `In Progress` → `Done` |

Credentials live in `.atlassian.env` (git-ignored) and in GitHub repo secrets.
Never print them, never commit them, never paste them into chat.

---

## What Sid says, and what you do

He talks in plain English. He is not going to type commands. Map his intent to
these steps and narrate what you did in plain language — not in shell.

### "What's on the list?" / "What should I work on?"

```bash
python3 scripts/atlassian_sync.py --check
```

Then list the open tickets. Use the Atlassian tools if you have them; otherwise:

```bash
curl -sS -u "$ATLASSIAN_EMAIL:$ATLASSIAN_API_TOKEN" \
  --get "https://affirma-demo.atlassian.net/rest/api/3/search/jql" \
  --data-urlencode 'jql=project = SIDC AND statusCategory != Done ORDER BY key ASC' \
  --data-urlencode 'fields=key,summary,status' | python3 -m json.tool
```

Report them as a short list with ticket key, title, and status.

### "Let's work on the AEO one" / "Start on the design ticket"

1. Identify the ticket key from what he said.
2. Mark it started:
   ```bash
   python3 scripts/atlassian_sync.py --start SIDC-15
   ```
3. Read the matching spec page in Confluence for the acceptance criteria. Each
   ticket names its spec page.
4. Do the work in `site/`.
5. Show him the result (see *Previewing* below).
6. **Stop and wait for his approval. Do not commit yet.**

### "Looks good" / "Ship it" / "Commit that"

**Commit only. Do not push.**

```bash
git add -A && git commit -m "<what you did>

SIDC-15"
```

The local `post-commit` hook runs the full sync — Jira advances, Confluence is
rewritten, `build-info.json` refreshes. Committing is enough to show the whole
loop. You do not need to run the sync manually.

Keeping the push separate matters: pushing redeploys the public site at
<https://sidc-rovo.github.io/sidc-rovo/>, and mid-demo that would briefly publish
a half-finished design. So don't.

Then tell him in plain language what moved: which ticket went to Done, and that
the Confluence record was rewritten.

### "Publish it" / "Push it live" / "Put it on GitHub"

Only on one of these — an explicit instruction to publish — do you push.

```bash
git push
```

Then note that GitHub Actions re-runs the same sync as the authoritative pass and
the live site redeploys in about a minute.

### "Undo that" / "Reset the demo"

See *Resetting* below. Confirm with him before resetting, since it moves tickets
backwards.

---

## Previewing

Always show him the site before committing. He approves visually, in a browser.

```bash
python3 -m http.server 8899 --directory site
```

Then open <http://localhost:8899/>. If a preview tool is available, use it and
put the page in front of him rather than telling him a URL.

---

## Repo layout

| Path | What it is |
|---|---|
| `site/index.html` | The website. Single page, no framework, no build step. |
| `site/app.js` | Reads `build-info.json` to fill the Delivery section. |
| `site/build-info.json` | **Generated.** Do not hand-edit. |
| `docs/releases/` | **Generated.** Release notes, one file per ticket, plus an index and a decisions list. Regenerated in full every sync. |
| `site/styles.css` | Absent in the plain baseline. The design work creates it. |
| `scripts/atlassian_sync.py` | The sync engine. Python stdlib only. |
| `atlassian.config.json` | Keys, states, and the path→area map. |
| `.githooks/post-commit` | Fires the sync locally on every commit. |
| `.github/workflows/` | Authoritative sync on push, plus Pages deploy. |
| `docs/SETUP.md` | Credential and CI setup. |

---

## Things not to do

- **Do not create Jira tickets for planned work.** The plan already exists. A
  commit advances it. Creating tickets per commit turns the board into a
  changelog — the config option `commit_mode` is deliberately set to `update`.
- **Do not hand-edit `Release Log` or `Changelog by Commit` in Confluence.**
  They are regenerated in full from `git log` on every sync and your edits will
  vanish. Change the repo instead.
- **Do not edit `site/build-info.json` or anything under `docs/releases/`.**
  Same reason — both are regenerated from `git log` on every sync. If a release
  note is wrong, the commit message is wrong; fix that.
- **Do not quote the literal CI-skip token** (the word "skip" and "ci" in square
  brackets) anywhere in a commit message. GitHub scans the whole message body, so
  merely writing about it silently cancels every workflow for that commit. Say
  "the CI-skip directive" instead.
- **Do not push unless he explicitly says to publish.** "Ship it" means commit.
  Pushing redeploys the public site, so it is a separate, deliberate step.
- **Do not commit `.atlassian.env`.** It is git-ignored; keep it that way.

---

## How the automation actually behaves

Worth knowing so you can explain it when asked.

**Confluence is derived state.** `Release Log` and `Changelog by Commit` are
rebuilt in full from `git log` every run — never appended to. They cannot drift,
and re-running is always safe.

**Jira is not derived**, because you cannot un-create an issue. So the sync
advances what exists and never duplicates. A commit naming `SIDC-15` comments on
it and moves it to Done. A commit naming nothing is logged as unplanned work
against `SIDC-1`.

**Divergence is captured, not filed.** If a commit touches areas its ticket does
not claim — you set out to do AEO and also fixed the nav — that shows up as a
scope note on the ticket, a comment on `SIDC-1`, and a row in the Release Log's
*Unplanned changes* table. No new ticket appears. The plan stays the plan; the
record still matches what shipped.

**The site reports its own state.** The sync writes `site/build-info.json`; the
Delivery section reads it at load. That is why the page can honestly claim to
track its own construction.

---

## Resetting

Restores the plain baseline and puts the demo tickets back to `To Do`.

```bash
./scripts/reset-demo.sh
```

It will tell you exactly what it is about to do and ask for confirmation. Nothing
is destroyed: the polished design is kept on the `design-v1` git tag.
