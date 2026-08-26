# AGENTS.md

Short version for any agent or person landing here. The detailed rules are in
[CLAUDE.md](CLAUDE.md) — read that before making changes.

## What this repo is

Sid Chaturvedi's personal website, plus a small amount of machinery that keeps
the project's written record in step with the code by itself.

## Where the knowledge lives

| | |
|---|---|
| **Plans and specs** | [Confluence — SIDC space](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/overview) |
| **Work items** | [Jira — SIDC project](https://affirma-demo.atlassian.net/jira/core/projects/SIDC/board) |
| **The site** | <https://sidc-rovo.github.io/sidc-rovo/> |
| **Generated release notes** | [`docs/releases/`](docs/releases) |

## The one thing to remember

**Put the Jira ticket number in your commit message.**

```
Make the site answer-engine ready

SIDC-15
```

That single line is what connects the code to everything else. Everything below
happens because of it.

## What happens by itself when you commit

You do not need to update Jira. You do not need to write release notes. You do
not need to tell anyone what changed.

- The ticket you named gets a comment linking your exact commit, and moves along
  from **To Do** to **In Progress** to **Done**.
- The **Release Log** and **Changelog** pages in Confluence are rewritten from
  the project's history.
- Release notes appear in `docs/releases/`, one file per ticket.
- The website's own "Delivery" section updates to show what just shipped.

## If your work drifts from the plan

It usually does, and that is fine. Say you set out to do the AEO ticket and also
tidied something unrelated.

Nothing is hidden and nothing extra is invented. No new ticket appears. Instead:

- A note goes on the ticket saying the work went beyond it.
- A comment goes on the Confluence spec page, so whoever wrote the plan can see
  reality differed from it and decide whether to update it.
- It is listed under **Unplanned changes** in the Release Log.

The plan stays the plan. The record matches what actually shipped.

## If you decided something

Add a line starting with `Decision:` in the commit message.

```
Decision: no CSS framework — plain files outlive dependencies
```

These are collected into the **Decision Log** page in Confluence, so the reason
behind a choice is still findable in a year.

## Two checks that run quietly

- **Stale specs.** If a Confluence spec was last edited by a person *before* the
  work implementing it landed, the page says so. The document reads as current
  while the code has moved on — that is easy to miss and worth flagging.
- **Evidence gaps.** If a ticket is marked Done but no commit ever mentions it,
  it gets listed. Work claimed is worth noticing as much as work unrecorded.

## Do not hand-edit these

They are rebuilt from the project's history every time, so edits are lost:

- `docs/releases/` — all of it
- `site/build-info.json`
- Confluence: **Release Log**, **Changelog by Commit**, **Decision Log**, and the
  *Implementation status* section of each spec page

Everything else on a Confluence page is yours and is left alone. If a generated
page is wrong, the commit message was wrong — fix that.

## Starting the site locally

```bash
python3 -m http.server 8899 --directory site
```

Then open <http://localhost:8899/>.
