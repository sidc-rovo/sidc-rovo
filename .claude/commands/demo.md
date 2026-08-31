---
description: Run the whole website demo end to end — four tickets, commits between each, no pushing
---

# Demo autopilot

Work through all four open tickets in order, committing after each one, so Sid can
narrate while Jira and Confluence update themselves in front of the audience.

**Run continuously.** Do not stop to ask for approval between tickets — he is
talking over this. Announce each ticket as you start it in one short line, do the
work, commit, and move on. If he says "pause after each ticket", switch to
stopping after every commit instead.

## Rules that make the record correct

These are not style preferences. Getting them wrong breaks the demo.

- **One ticket per commit.** Never combine two tickets in one commit.
- **The ticket key goes on its own line** at the end of the message. A key
  mentioned in prose or inside a trailer is treated as a cross-reference and will
  not advance anything — that is deliberate.
- **Never put another ticket's key on its own line.** Referring to another ticket
  inside a `Scope-note:` or `Decision:` line is fine and safe.
- **Commit, do not push.** Pushing redeploys the public site mid-demo. Only push
  if he explicitly says "publish".
- **Do not create Jira tickets.** The plan already exists.
- **Do not run `--all`.** It would post divergence notices for ten
  pre-convention commits.
- **Write commit messages in English** even if he is speaking another language —
  the ticket key, `Decision:` and `Scope-note:` trailers are parsed.
- Read each ticket's spec page in Confluence before building. The acceptance
  criteria are written down; do not invent your own.
- Show the site in the browser after any visible change, so he can point at it.

## The sequence

### 1 · SIDC-15 — answer-engine ready, **with deliberate drift**

```bash
python3 scripts/atlassian_sync.py --start SIDC-15
```

Read the **AEO Readiness Spec**, then implement it in `site/`: `Person` and
`FAQPage` JSON-LD, meta description, canonical, Open Graph, `lang`, and
`robots.txt` + `sitemap.xml` + `llms.txt`.

**Then also do one thing the ticket does not cover:** improve the date formatting
in the delivery table, which lives in `site/app.js`. This is the point of the act
— it is site behaviour, not AEO, so it lands outside SIDC-15's scope and the sync
will report the divergence. Do it, and declare it honestly in the commit.

Show him the page. Point out it looks almost unchanged, then show the structured
data. Commit:

```
Make the site answer-engine ready

Person and FAQPage structured data, meta description, canonical link,
Open Graph tags, plus robots.txt, sitemap.xml and llms.txt.

Decision: permissive robots.txt — blocking AI crawlers defeats the point of AEO
Decision: llms.txt over a custom manifest, because it is the convention agents already look for
Scope-note: also reformatted the delivery table dates, which is site behaviour rather
  than AEO — flagging it rather than folding it into this ticket

SIDC-15
```

After the sync prints, say in one line what moved: SIDC-15 to Done, divergence
recorded on the ticket, on the workstream, on the AEO spec page, and in the
Release Log — and no new ticket created.

### 2 · SIDC-16 — the visual design system

```bash
python3 scripts/atlassian_sync.py --start SIDC-16
```

Read **Design System & Tokens** and build `site/styles.css` to it: tokens first,
two accents only, fluid `clamp()` type scale with no font-size media queries,
light and dark via `prefers-color-scheme` with light values re-picked rather than
inverted, `prefers-reduced-motion` honoured, skip link and `:focus-visible` kept.
Add whatever markup hooks `site/index.html` needs.

Show him the page — this is the visual payoff. Commit:

```
Build the visual design system

Token-driven stylesheet implementing the Confluence spec. Fluid type
scale, two accents, light and dark, reduced motion honoured.

Decision: no framework — three static files outlive any dependency

SIDC-16
```

This one should produce **no** divergence. Say so: the system flags drift, not
every change.

### 3 · SIDC-17 — portrait and social card

```bash
python3 scripts/atlassian_sync.py --start SIDC-17
```

Restore the portrait from the `design-v1` tag:

```bash
git checkout design-v1 -- site/assets/sidc.jpeg
```

Place it in the hero with real `alt` text and explicit `width`/`height`, and wire
it to `og:image`, `twitter:image`, and `image` in the `Person` JSON-LD. Show him.
Commit:

```
Restore the portrait and social card image

Hero portrait with alt text and explicit dimensions, wired to og:image,
twitter:image and the Person JSON-LD.

SIDC-17
```

### 4 · SIDC-18 — accessibility and semantics

```bash
python3 scripts/atlassian_sync.py --start SIDC-18
```

Landmarks (`header`, `main`, `nav`, `footer`), skip link first in tab order,
visible `:focus-visible` everywhere, one `<h1>` with no skipped levels, scoped
`th` on tables, AA contrast in both colour schemes, reduced motion fully
honoured. Verify by reading the heading outline and checking the page still works
with CSS disabled. Commit:

```
Accessibility and semantics pass

Landmarks, skip link, focus visibility, heading outline, scoped table
headers, AA contrast in both colour schemes.

SIDC-18
```

## Close

Show the finished site, then summarise in a few lines:

- Four tickets, all moved themselves To Do → In Progress → Done
- One divergence, recorded in four places, no ticket invented
- Confluence Release Log, Changelog and Decision Log all rewritten from `git log`
- The AEO spec now flags itself as stale, because work landed after a human last
  edited it
- Nothing was pushed — the public site is untouched until he says "publish"

Then remind him `/demo-reset` puts everything back.
