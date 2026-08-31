---
description: Put the demo back to its starting state — plain site, four tickets in To Do
---

# Reset the demo

Run the reset script and report what it did:

```bash
scripts/reset-demo.sh --yes
```

That restores the plain site from the `demo-baseline` tag, moves every
`demo-scope` ticket back to **To Do**, and regenerates the Confluence pages from
the restored history.

Then confirm the state is actually clean rather than assuming it:

```bash
git status --short && git log --oneline -1
```

Report: the baseline SHA, that the tree is clean, and that the four tickets are
back in To Do.

## Notes

- **Local only by default.** If he published during the demo, the remote still
  has the demo commits — add `--push` to reset those too, but say clearly that it
  rewrites remote history before doing it.
- **Comments are not cleared.** Jira ticket comments and Confluence page comments
  from the run remain, because that history is not meant to be erasable. If he
  demos twice to the same audience, the second run shows the first run's
  comments. Mention this rather than letting him discover it live.
- If the Confluence step fails with a network or SSL error, the sync is
  idempotent — just run it again:
  `python3 scripts/atlassian_sync.py --skip-jira --range HEAD..HEAD`
