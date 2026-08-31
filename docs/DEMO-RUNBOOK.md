# Demo Runbook — Confluence-led

Everything below is typed into Claude in plain English. Copy the prompts as
written. There is exactly one shell command, in Act 0, and it only opens Claude
in the right folder. About 9 minutes end to end.

---

## The argument you are making

Confluence is where teams write down what they mean to do. Its failure mode isn't
being wrong on day one — it's being **right on day one and never touched again**.

> Documentation doesn't rot because people are lazy. It rots because nothing
> connects it to the thing it describes.

So this demo runs in that direction: **start in the document, end in the
document.** The spec defines done before any work happens. The code gets built
against it. And then the page updates itself — including telling you, unprompted,
that reality went somewhere the spec didn't describe.

Three beats carry it. Know these cold:

| Beat | Act | The line |
|---|---|---|
| The spec defines "done" before the work | 2 | *"The agent read the plan rather than inventing its own definition of done."* |
| The page comments on itself when reality diverges | 5 | *"Nobody told it to write that. The document noticed."* |
| The page flags itself as stale | 6 | *"This spec just told me it might be out of date."* |

Everything else is scaffolding for those three.

---

## Autopilot — if you'd rather just narrate

One keystroke runs all four tickets end to end, committing between each, while
you talk over it and point at Confluence and Jira updating themselves:

```
/demo
```

It does not stop for approval — it announces each ticket, does the work, commits,
and moves on. Say **"pause after each ticket"** if you want gates instead. It
never pushes, so the public site is untouched until you say *publish*.

And to put everything back:

```
/demo-reset
```

The acts below are the manual version. Run them when you want to control the
pacing, take questions between beats, or type the prompts yourself. **Act 5 and
Act 6 are the payoff either way** — read those two before you present, because
autopilot will fly past them and you need to know what to point at.

---

## Act 0 — before you start

- [ ] Tabs open: the **[SIDC space](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/overview)**, the **[AEO Readiness Spec](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/pages/17530882/AEO+Readiness+Spec)**, the **[Release Log](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/pages/17039362/Release+Log)**, the [Jira board](https://affirma-demo.atlassian.net/jira/core/projects/SIDC/board), and a blank tab for the site
- [ ] Lead with the **space**, not the board — the board is the second tab, not the first
- [ ] Terminal ready

```bash
cd /Users/schaturvedi2/Claude/sidc-rovo && claude
```

Claude reads `CLAUDE.md` on start. You do not need to explain anything to it.

> **Nothing is published during this demo.** Committing runs the whole loop —
> Jira moves, Confluence rewrites. Pushing is a separate, optional final step.

**Open on the space, before typing anything.** Six pages. Point out that four are
hand-written — Architecture, Content Inventory, and two specs — and three are
generated. Say you'll come back to that distinction, because it's the whole
design.

---

## Act 1 — the plan lives in the document · 1 min

```
What's in my Confluence space for the website project?
```

| Expected | Point at |
|---|---|
| Claude lists the pages and distinguishes the specs from the generated records. | The space tab. Same pages. It read the real space. |

> "This is where the intent lives. Not a ticket title — actual acceptance
> criteria, written by a person, before anyone opened an editor."

---

## Act 2 — the spec defines done · 2 min ★

```
Read the AEO spec and tell me what it says "done" looks like.
```

| Expected | Point at |
|---|---|
| Claude summarises the five acceptance buckets — identity JSON-LD, extractable claims, FAQ markup, crawler files, meta basics — and the explicit out-of-scope list. | The spec page itself, side by side. It didn't invent this. |

This is beat one:

> "The definition of done was written down before the work started, by a human,
> in Confluence. The agent read it. It isn't guessing what good looks like, and
> it isn't negotiating scope with itself — the out-of-scope list is in the page
> too."

---

## Act 3 — the document hands off to the board · 1 min

```
Which ticket implements that spec? Start it.
```

| Expected | Point at |
|---|---|
| Claude identifies **SIDC-15** from the spec and marks it In Progress. | Now switch to the board. **SIDC-15 has moved to In Progress.** Nobody dragged it. |

> "Confluence said what. Jira says where it is. The link between them was already
> written into the page — the agent followed it rather than being told."

---

## Act 4 — build to the written criteria · 2 min

```
Build it to the spec, then show me the site.
```

| Expected | Point at |
|---|---|
| Claude edits the page, adds `robots.txt`, `sitemap.xml`, `llms.txt`, opens a local preview. | The page looks *almost identical*. Say so before anyone else notices. |

```
Show me what a machine sees now that it couldn't before.
```

> "Nothing changed for you. Everything changed for a machine reading this page.
> That's the dual-intent bet from the site's own copy — one page, two classes of
> user."

---

## Act 5 — the document notices the drift · 3 min ★★

This is the act that matters. Ask for something the spec **does not** cover — the
way real work always drifts:

```
The dates in the delivery table are hard to read — format them nicer.
```

Claude will do it. **Say nothing about scope.** Let it look like an ordinary
aside. Then:

```
Looks good. Ship it.
```

The sync runs in your terminal while you talk:

```
a1b2c3d -> SIDC-15: Done
a1b2c3d -> divergence: also touched Site behaviour (outside SIDC-15) — recorded, not filed
```

Now walk it **document-first**:

| 1. Where | What is there |
|---|---|
| **AEO Readiness Spec** → comments | *"Reality diverged from this spec."* Names the commit and the extra scope, and says the page is the thing to change if the scope should have been in it. |
| **Release Log** | An **Unplanned changes** table naming exactly what fell outside the plan, plus a new release row linked to commit and ticket. |
| **SIDC-1** (workstream) | The divergence recorded at programme level, not buried in one ticket. |
| **SIDC-15** | Done, with a scope note on the delivery comment. |
| **The board** | **Still four tickets.** Count them before and after. |

Land it:

> "Nobody told it to write that. The document noticed. And notice what it *didn't*
> do — it didn't file a ticket nobody asked for, and it didn't quietly drop the
> extra work. The plan stayed the plan. The record matches what shipped. The
> person who owns the spec now has a decision to make, and they can see it."

If asked why not just create a ticket: that's a config choice, `commit_mode`,
deliberately set to `update`. Per-commit tickets turn a board into a changelog.

**Two channels catch drift, not one:**

- **Inferred** — from which files changed.
- **Declared** — a `Scope-note:` line the agent writes itself. This exists because
  path matching is structurally blind to scope creep inside a file the ticket
  already owns. In an early run the agent noticed exactly that about itself and
  wrote it in the commit message while the tooling stayed silent. That channel is
  now first-class.

---

## Act 6 — the page tells you it's behind · 1 min ★

```
Is the AEO spec still accurate?
```

| Expected | Point at |
|---|---|
| Claude reads the **Implementation status** section on the spec, which now says the spec may be out of date. | The panel on the spec page, with both timestamps. |

> "Read that back. The work implementing this spec landed *after* a person last
> edited it. The page is telling me it might be behind the code. Nothing is
> broken — which is exactly why this normally goes unnoticed for six months."

Worth naming the mechanism, because it's the subtle bit:

> "It tracks the last time a *human* touched the page, not the last time anything
> touched it. Otherwise stamping this status would reset the clock and the check
> could never fire."

Re-saving the page after reviewing it clears the flag. That's the intended loop:
the document asks for attention, a person gives it, the flag goes away.

---

## Act 7 — what else wrote itself · 1 min

```
Show me everything that got written down.
```

| Where | What is there | Who it is for |
|---|---|---|
| **Decision Log** | Every `Decision:` line from the commit messages, with ticket and commit. | Whoever asks "why is it like this" in six months. |
| **Changelog by Commit** | Full per-commit detail, regenerated from `git log`. | Whoever needs the long version. |
| **Release Log → Evidence gaps** | Tickets marked Done that no commit references. | Whoever has to trust the board. |
| [`/releases/`](https://sidc-rovo.github.io/sidc-rovo/releases/) | The same notes published on the site. | Whoever wants release notes without writing release notes. |

The Decision Log line:

> "Architecture decision records are a great idea that almost nobody keeps up,
> because the ceremony costs more than the benefit. This costs one line in a
> commit message, sits next to the change it justifies, and can't drift from the
> code — because it *is* the code's history."

And the honesty point, which is worth making explicitly:

> "Those three pages are regenerated in full from `git log` every run. They can't
> drift, and re-running is free. The cost is that you can't hand-edit them — and
> each one says so at the top. The other three pages in this space are yours and
> are never touched."

---

## Act 8 — the spec you can see · 2 min

```
Read the design spec and build the site to it.
```

| Expected | Point at |
|---|---|
| Claude reads **Design System & Tokens**, writes the stylesheet, shows you the page. | Dramatic change — the crowd-pleaser after two acts of invisible work. |

The point is not that it looks good. It's that the tokens, type scale, contrast
rules and reduced-motion requirement were **written in Confluence first**, and
the page has a "Done when" checklist you can read back against the result.

```
Ship it.
```

SIDC-16 → Done. This time there should be **no** divergence — the commit stayed
inside the ticket's scope. Contrast with Act 5: the system isn't flagging
everything, it's flagging drift.

---

## Act 9 — finish the board · 1 min

```
Put my photo back, then ship it.
```

```
Check the page is accessible and fix anything that isn't, then ship it.
```

SIDC-17 and SIDC-18 → Done. The board is empty except the workstream, and every
card moved itself.

---

## Act 10 — publish · optional, 1 min

```
Publish it.
```

GitHub Actions re-runs the identical sync as the authoritative pass, regenerates
the release notes, and redeploys. Point at the [Actions
tab](https://github.com/sidc-rovo/sidc-rovo/actions) — same script, retained
logs, an audit trail — then [the live site](https://sidc-rovo.github.io/sidc-rovo/).

---

## Reset

```
Reset the demo.
```

| Restores | How |
|---|---|
| The plain site | Hard reset to the `demo-baseline` tag |
| The four tickets | Every `demo-scope` ticket back to **To Do** |
| Confluence | Regenerated from the restored history — it self-heals, being derived state |

Nothing is destroyed. The polished design stays on the `design-v1` tag.

**What reset does not clear:** comments left on Jira tickets and spec pages. Jira
history isn't meant to be erasable, and honestly it shouldn't be. If you demo
twice to the same audience, the second run shows the first run's comments.

If you published in Act 10, add `--push` to reset the remote too:
`scripts/reset-demo.sh --push`.

---

## If something goes sideways

| Symptom | What to do |
|---|---|
| "no credentials found, skipping" | `.atlassian.env` is missing. The commit still succeeded. Run `python3 scripts/atlassian_sync.py --check`. |
| A ticket didn't move | The commit message needs the key **on its own line** — that's the rule, deliberately strict. Ask Claude: *"that commit didn't reference the ticket — fix the record."* |
| A ticket moved that shouldn't have | Shouldn't happen any more, but tell Claude to revert it and say which. Mentions in `Decision:` / `Scope-note:` lines and in prose no longer count as deliveries. |
| Claude offers to create a new ticket | Tell it not to. `CLAUDE.md` forbids it, but say *"don't create tickets, the plan already exists"*. |
| A script can't reach Atlassian | Expected to self-heal — Claude should fall back to the Atlassian tools and say which route it used. If it stops instead, tell it to try the other route. That fallback is designed, and worth pointing out when it happens. |
| Preview shows a stale page | Hard-reload. The local server doesn't cache; the browser might. |
| Don't run `--all` | It would post divergence notices for ten pre-convention commits. The normal path never needs it. |

---

## Questions you will get

| Question | Answer |
|---|---|
| "Isn't this just a commit-message convention?" | The convention is the cheap half. The hard half is deciding what to do when the commit doesn't match the ticket — Act 5 — and that's not a convention, it's a policy. |
| "What stops the docs being wrong?" | Two different mechanisms. The generated pages can't be wrong because they're derived from `git log`. The hand-written pages can be wrong, which is why they carry a staleness check instead of a promise. |
| "Why not Jira's native GitHub integration?" | Excellent at linking commits to existing issues. It won't move a ticket through a workflow on your rules, own Confluence, or reason about scope drift. Complementary. |
| "Does this scale to a team?" | The mechanism does — path classification plus idempotent writes. One-issue-per-commit does not, which is why this is in update mode. At team scale you'd key off the PR. |
| "Could the agent just lie about what it did?" | Fair challenge. Not for the parts that matter: the Confluence record is derived from git, not from the agent's account of itself. The commit is the evidence. |
| "Is this Rovo?" | No — plain REST against Jira and Confluence, standard-library Python. It's the substrate that makes work legible enough for Rovo to be useful on top. |
| "What happens when the spec and the code disagree?" | That's Act 5 and Act 6. The system doesn't resolve it — it surfaces it and names who has to decide. Automating the decision would be the wrong move. |

---

## Related

- Confluence: [SIDC space](https://affirma-demo.atlassian.net/wiki/spaces/SIDC/overview) — **AEO Readiness Spec** · **Design System & Tokens** · **Website Architecture** · **Content Inventory** · *Release Log* · *Changelog by Commit* · *Decision Log* (italics = generated)
- Jira: [SIDC-1](https://affirma-demo.atlassian.net/browse/SIDC-1) workstream · [SIDC-15](https://affirma-demo.atlassian.net/browse/SIDC-15) · [SIDC-16](https://affirma-demo.atlassian.net/browse/SIDC-16) · [SIDC-17](https://affirma-demo.atlassian.net/browse/SIDC-17) · [SIDC-18](https://affirma-demo.atlassian.net/browse/SIDC-18)
- Code: [`CLAUDE.md`](../CLAUDE.md) · [`AGENTS.md`](../AGENTS.md) · [`scripts/atlassian_sync.py`](../scripts/atlassian_sync.py) · [`SETUP.md`](SETUP.md)
