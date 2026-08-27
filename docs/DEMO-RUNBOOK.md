# Demo Runbook

Everything below is typed into Claude in plain English. Copy the prompts as
written. There is exactly one shell command, in Act 0, and it only opens Claude
in the right folder. About 8 minutes end to end.

---

## What you are actually demonstrating

Not "AI writes code". Everyone has seen that. The claim is narrower and harder:

> When work happens, the system of record updates itself — including when the
> work drifts away from what was planned. Nobody moves a card. Nobody writes a
> status update. And nothing gets invented to paper over the gap.

The site's own copy makes this argument in bet #1: *the future of AI is
coordination, not generation*. This demo tests that claim on the site itself.

**The moment that lands is Act 4.** Everything before it is setup for that.

---

## Act 0 — before you start

- [ ] Four browser tabs: the [Jira board](https://affirma-demo.atlassian.net/jira/core/projects/SIDC/board), the [SIDC space](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/overview), the [AEO spec](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/pages/17530882/AEO+Readiness+Spec), and a blank tab for the local site
- [ ] Board shows exactly four things in **To Do**: SIDC-15, 16, 17, 18
- [ ] Terminal ready

Open Claude in the project:

```bash
cd /Users/schaturvedi2/Claude/sidc-rovo && claude
```

Claude reads `CLAUDE.md` on start, which is what makes plain-English instructions
work. You do not need to explain anything to it.

> **Nothing is published during this demo.** Committing runs the whole loop
> locally — Jira moves, Confluence rewrites. Pushing is a separate, optional
> final step, so the public site stays as it is until you decide otherwise.

---

## Act 1 — show the plan · 1 min

```
What's on my plate for the website?
```

| Expected | Point at |
|---|---|
| Four open tickets with keys, titles, status — AEO, design system, portrait, accessibility. | The Jira board. Same four, same order. It read the real board. |

---

## Act 2 — pick up the work · 1 min

```
Let's do the answer-engine one. Read the spec and tell me what it actually needs.
```

| Expected | Point at |
|---|---|
| Claude summarises the AEO spec — structured data, FAQ markup, crawler files, meta basics — and marks the ticket started. | Refresh the board. **SIDC-15 has moved to In Progress.** Nobody dragged it. |

Worth saying: the acceptance criteria came from Confluence. The plan was written
down *before* the work started, and the agent read it rather than inventing its
own definition of done.

---

## Act 3 — do the work · 2 min

```
Go ahead and make those changes, then show me the site.
```

| Expected | Point at |
|---|---|
| Claude edits the page, adds `robots.txt`, `sitemap.xml`, `llms.txt`, starts a local preview, shows you the page. | The page looks *almost identical*. Say so before anyone else notices. |

Then:

```
Show me what a machine sees now that it couldn't before.
```

It will show the structured data. This is the line:

> "Nothing changed for you. Everything changed for a machine reading this page.
> That's the dual-intent bet from the site's own copy — one page, two classes of
> user."

---

## Act 4 — the divergence · 2 min ★

Ask for something that is **not** in the ticket, the way real work always drifts:

```
The dates in the delivery table are hard to read — format them nicer.
```

Claude will do it. **Say nothing about scope yet.** Let it look like an ordinary
aside. Then:

```
Looks good. Ship it.
```

The commit fires the sync in your terminal, live, while you talk. You will see
something like:

```
▸ Jira — SIDC (update mode)
    workstream exists: SIDC-1
    a1b2c3d -> SIDC-15: Done
    a1b2c3d -> divergence: also touched Site behaviour (outside SIDC-15) — recorded, not filed
```

Then walk the tabs:

| Where | What happened |
|---|---|
| **SIDC-15** | Moved to **Done**. New comment linking the exact commit — plus a *scope note* saying the commit also touched an area this ticket does not cover. |
| **SIDC-1** (workstream) | A comment recording the divergence, so it is visible at programme level rather than buried in one ticket. |
| **AEO Readiness Spec** | A comment: *"Reality diverged from this spec."* Page bodies get regenerated every run; comments persist, so this is what accumulates. |
| **Release Log** | A new row linked to both commit and ticket. Above it, an **Unplanned changes** table naming exactly what fell outside the plan. |
| **The board** | **Still four tickets.** Count them before and after. |

Then land it:

> "The work diverged from the plan — which is what always happens. Two bad
> options are usually on offer: pretend it didn't, or file a ticket nobody asked
> for. This did neither. The plan stayed the plan, the record matches what
> actually shipped, and the divergence is visible to anyone who looks."

If someone asks why it doesn't just create a ticket: that's a config choice,
`commit_mode`, deliberately set to `update`. Per-commit tickets turn a board into
a changelog.

> **Why this exact prompt.** An earlier version said "tidy the delivery table",
> and Claude solved it with a small style block inside `index.html` — a file
> SIDC-15 already claims — so no divergence was detected and the act fell flat.
> Formatting the dates lands in `site/app.js`, which SIDC-15 does not claim, so
> the drift is guaranteed.

---

## Act 4b — the rest of the record · 2 min

```
Show me everything that just got written down.
```

| Where | What is there | Who it is for |
|---|---|---|
| **AEO spec** — a comment | "Reality diverged from this spec", naming the commit and the extra scope. | Whoever owns the plan. |
| **Decision Log** | Every `Decision:` line from the commit messages, with ticket and commit. | Whoever asks "why is it like this" in six months. |
| `docs/releases/SIDC-15.md` | What shipped, decisions, scope notes, files touched. | Whoever wants release notes without writing release notes. |
| **Release Log → Evidence gaps** | Tickets marked Done that no commit references. | Whoever has to trust the board. |
| **AEO spec → Implementation status** | Now flagged **stale**: the work landed after a human last edited the spec. | Whoever assumes the doc is current. |

The line for the Decision Log:

> "Architecture decision records are a great idea that almost nobody keeps up,
> because the ceremony costs more than the benefit. This costs one line in a
> commit message, sits next to the change it justifies, and can't drift from the
> code — because it *is* the code's history."

And for evidence gaps, the uncomfortable version:

> "Everything so far catches work that wasn't planned. This catches the opposite
> — work that was *claimed*. A Done card with no commit behind it is the failure
> mode every status report has. Same mechanism, pointed the other way."

**Two channels catch drift, not one:**

- **Inferred** — from which files changed.
- **Declared** — a `Scope-note:` line in the commit message. This exists because
  path matching is structurally blind to scope creep inside a file the ticket
  already owns. In the first live run the agent noticed that about itself and
  wrote it in the commit message while the tooling stayed silent. That channel is
  now first-class.

---

## Act 5 — the visual payoff · 2 min

```
Now make it look good.
```

| Expected | Point at |
|---|---|
| Claude picks up SIDC-16, reads the design spec from Confluence, writes the stylesheet, shows you the page. | Dramatic change. The crowd-pleaser after two acts of invisible work. |

The design was not improvised — tokens, type scale, and accessibility rules were
written down in Confluence first. Then:

```
Ship it.
```

SIDC-16 goes to Done. This time there should be **no** divergence — the commit
stayed inside the ticket's scope. Contrast with Act 4: the system is not flagging
everything, it is flagging drift.

---

## Act 6 — finish the board · 1 min

```
Put my photo back, then ship it.
```

```
Check the page is accessible and fix anything that isn't, then ship it.
```

SIDC-17 and SIDC-18 to Done. The board is now empty except the workstream — and
every card moved itself.

---

## Act 7 — publish · optional, 1 min

```
Publish it.
```

| Expected | Point at |
|---|---|
| Claude pushes. GitHub Actions re-runs the identical sync as the authoritative pass, then regenerates the release notes and redeploys. | The [Actions tab](https://github.com/sidc-rovo/sidc-rovo/actions) — same script, retained logs, an audit trail. Then [the live site](https://sidc-rovo.github.io/sidc-rovo/) about a minute later, and the notes at `/releases/`. |

The Delivery section on the live page now shows the commits you just made, with
their ticket keys. The page reports its own construction.

---

## Reset

```
Reset the demo.
```

Claude runs `scripts/reset-demo.sh`, which asks for confirmation, then:

| Restores | How |
|---|---|
| The plain site | Hard reset to the `demo-baseline` tag |
| The four tickets | Every `demo-scope` ticket back to **To Do** |
| Confluence | Regenerated from the restored history — it self-heals, being derived state |

Nothing is destroyed. The polished design stays on the `design-v1` tag. Comments
left on tickets during the demo remain, which is honest — Jira history is not
meant to be erasable.

> If you published in Act 7, add `--push` to reset the remote too:
> `scripts/reset-demo.sh --push`. That rewrites remote history, so only on this
> demo repo.

---

## If something goes sideways

| Symptom | What to do |
|---|---|
| "no credentials found, skipping" | `.atlassian.env` is missing. The commit still succeeded. Run `python3 scripts/atlassian_sync.py --check`. |
| A ticket didn't move | The commit message probably didn't have the key **on its own line** — that's the rule. Ask Claude: *"that commit didn't reference the ticket — fix the record."* |
| Claude offers to create a new ticket | Tell it not to. `CLAUDE.md` forbids it, but say *"don't create tickets, the plan already exists"* and move on. |
| A script can't reach Atlassian | Expected to self-heal — Claude should fall back to the Atlassian tools and say so. If it stops instead, tell it to try the other route. |
| Claude pushes when you said ship | Harmless, just deploys early. Carry on. |
| Preview shows a stale page | Hard-reload. The local server doesn't cache; the browser might. |

---

## Questions you will get

| Question | Answer |
|---|---|
| "Is the ticket reference in the commit doing all the work?" | Yes, and say so — it's the whole coupling mechanism. The honest version: the hard part isn't reading the key, it's deciding what to do when the commit doesn't match the ticket. That's Act 4. |
| "Why not Jira's native GitHub integration?" | Excellent at linking commits to existing issues. It won't move a ticket through a workflow on your rules, own Confluence, or reason about scope drift. Complementary. |
| "Does this scale to a team?" | The mechanism does — path classification plus idempotent writes. One-issue-per-commit does not, which is exactly why this is in update mode. At team scale you'd key off the PR. |
| "What stops it corrupting the record?" | Confluence is regenerated from `git log` in full every run, so it cannot drift. Jira is only ever advanced or commented, never rewritten. |
| "Is this Rovo?" | No — plain REST against Jira and Confluence, standard-library Python. It's the substrate that makes work legible enough for Rovo to be useful on top. |
| "Could the agent just lie about what it did?" | Fair challenge. Not for the parts that matter: the Confluence record is derived from git, not from the agent's account of itself. The commit is the evidence. |

---

## Related

- Jira: [SIDC-1](https://affirma-demo.atlassian.net/browse/SIDC-1) workstream · [SIDC-15](https://affirma-demo.atlassian.net/browse/SIDC-15) · [SIDC-16](https://affirma-demo.atlassian.net/browse/SIDC-16) · [SIDC-17](https://affirma-demo.atlassian.net/browse/SIDC-17) · [SIDC-18](https://affirma-demo.atlassian.net/browse/SIDC-18)
- Confluence: **AEO Readiness Spec** · **Design System & Tokens** · **Website Architecture** · **Content Inventory** · **Decision Log** · **Release Log**
- Code: [`CLAUDE.md`](../CLAUDE.md) · [`AGENTS.md`](../AGENTS.md) · [`scripts/atlassian_sync.py`](../scripts/atlassian_sync.py) · [`SETUP.md`](SETUP.md)
