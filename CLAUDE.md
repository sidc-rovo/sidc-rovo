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

Treat all of these as: commit **and** push.

```bash
git add -A && git commit -m "<what you did>

SIDC-15" && git push
```

The push is what triggers the authoritative sync. The local hook fires first for
instant feedback. You do not need to run the sync manually — both triggers do it.

Then tell him, in plain language, what moved: which ticket went to Done, that the
Confluence record was rewritten, and that the live site is redeploying.

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
- **Do not edit `site/build-info.json`.** Same reason.
- **Do not quote the literal CI-skip token** (the word "skip" and "ci" in square
  brackets) anywhere in a commit message. GitHub scans the whole message body, so
  merely writing about it silently cancels every workflow for that commit. Say
  "the CI-skip directive" instead.
- **Do not push without being asked.** Commit and push happen together, but only
  when he says to ship.
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
