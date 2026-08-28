#!/usr/bin/env python3
"""
atlassian_sync.py — keep Jira and Confluence in step with git history.

Design notes worth knowing before you change anything:

* Confluence pages are DERIVED STATE. Both the release log and the per-commit
  changelog are regenerated in full from `git log` on every run. Nothing is
  appended or patched, so the pages cannot drift out of sync with the repo and
  re-running is always safe.

* Jira issues are NOT derived state — you can't un-create an issue. Dedupe is
  therefore explicit: every auto-filed issue carries a `sha-<short>` label, and
  we check for that label before creating anything. Re-running is a no-op.

* Stdlib only. No pip install, so the same file works in CI and in a git hook.

Credentials come from the environment, never from this file or the config:
    ATLASSIAN_EMAIL      e.g. you@example.com
    ATLASSIAN_API_TOKEN  https://id.atlassian.com/manage-profile/security/api-tokens
    ATLASSIAN_SITE       optional; overrides config "site"

Usage:
    atlassian_sync.py                       # sync the last commit (hook mode)
    atlassian_sync.py --range HEAD~5..HEAD  # sync a range (CI mode)
    atlassian_sync.py --all                 # sync every commit on the branch
    atlassian_sync.py --dry-run             # print what would happen, touch nothing
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "atlassian.config.json"

TIMEOUT = 30
RECENT_ON_SITE = 12  # rows surfaced in build-info.json / the Delivery panel

# Spec pages are hand-maintained, so the sync may only touch one region of them.
# Everything between this heading and the next h2 is generated; the rest is the
# author's and must survive untouched.
STATUS_HEADING = "Implementation status"

# Version messages the sync writes. Used to tell its own edits apart from a
# human's when working out whether a spec has gone stale — without this, the act
# of stamping the badge would reset the staleness clock and the check could never
# fire.
SYNC_VERSION_PREFIX = "auto:"

FIELD_SEP = "\x1f"
REC_SEP = "\x1e"

#: Commits already reported as excluded, so the notice appears once per run
#: rather than once per collect_commits call.
_REPORTED_DROPS: set[str] = set()


class Fail(RuntimeError):
    """Something went wrong that the user needs to read."""


def log(msg: str) -> None:
    print(f"    {msg}", flush=True)


def load_env_file() -> bool:
    """Load .atlassian.env if the credentials aren't already in the environment.

    The hook and reset script both source this file before invoking us, but a
    human or an agent running the script straight from a shell has no reason to
    know that — and the failure looked like "credentials missing" rather than
    "you forgot to source a file". Owning the load here removes the trap.
    """
    if os.environ.get("ATLASSIAN_EMAIL") and os.environ.get("ATLASSIAN_API_TOKEN"):
        return False

    path = REPO_ROOT / ".atlassian.env"
    if not path.exists():
        return False

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)
    return True


def step(msg: str) -> None:
    print(f"\n▸ {msg}", flush=True)


# ----------------------------------------------------------------------------
# git
# ----------------------------------------------------------------------------

def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise Fail(f"git {' '.join(args)} failed:\n{out.stderr.strip()}")
    return out.stdout.strip()


def classify(
    paths: list[str], area_rules: list[dict[str, str]]
) -> tuple[list[str], list[str]]:
    """Map changed paths to areas. First matching prefix wins.

    Returns (areas, unclassified_paths). The second value matters: a file that
    matches no rule contributes no area, so it can never trigger a divergence —
    it enters the repository completely invisible to the record. Silence is the
    worst failure mode for a system whose claim is that the record matches what
    shipped, so callers are expected to surface these.
    """
    found: list[str] = []
    unknown: list[str] = []
    for path in paths:
        for rule in area_rules:
            if path.startswith(rule["prefix"]):
                if rule["area"] not in found:
                    found.append(rule["area"])
                break
        else:
            unknown.append(path)
    return found, unknown


def collect_commits(
    rev_range: str,
    area_rules: list[dict[str, str]],
    exclude_prefixes: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    exclude_shas: list[dict] | None = None,
) -> list[dict[str, Any]]:
    fmt = FIELD_SEP.join(["%H", "%h", "%s", "%b", "%an", "%ae", "%aI"]) + REC_SEP
    raw = git("log", f"--pretty=format:{fmt}", "--no-merges", rev_range)
    skip = tuple(exclude_prefixes or ())
    skip_paths = tuple(exclude_paths or ())

    # Normalise to lowercase hex so short and full SHAs both match.
    sha_rules = {
        str(e["sha"]).strip().lower(): e.get("why", "")
        for e in (exclude_shas or [])
        if e.get("sha")
    }
    dropped: list[tuple[str, str]] = []

    commits: list[dict[str, Any]] = []
    for chunk in raw.split(REC_SEP):
        if not chunk.strip():
            continue
        parts = chunk.strip("\n").split(FIELD_SEP)
        if len(parts) < 7:
            continue
        sha, short, subject, body, author, email, date = parts[:7]

        # The sync's own derived-state commits are not work worth tracking.
        if skip and subject.strip().startswith(skip):
            continue

        # Explicitly excluded commits — scaffolding that history has to keep
        # because something already links to its SHA.
        matched = next(
            (r for r in sha_rules if sha.lower().startswith(r) or r.startswith(sha.lower())),
            None,
        )
        if matched:
            dropped.append((short, sha_rules[matched]))
            continue

        # Generated files are dropped here, before classification. Otherwise the
        # sync's own output counts as work and every commit reports a phantom
        # divergence into whatever area those files live in.
        files = [
            f
            for f in git("show", "--name-only", "--pretty=format:", sha).splitlines()
            if f and not (skip_paths and f.startswith(skip_paths))
        ]
        areas, unclassified = classify(files, area_rules)
        commits.append(
            {
                "sha": sha,
                "short": short,
                "subject": subject.strip(),
                "body": body.strip(),
                "author": author,
                "author_email": email,
                "date": date,
                "files": files,
                "areas": areas,
                "unclassified": unclassified,
            }
        )

    # Report exclusions once per run. collect_commits is called several times
    # (range and full history), and this must never be silent — a commit
    # vanishing from the record without a word is the exact dishonesty this
    # whole system is built to prevent.
    for short, why in dropped:
        if short in _REPORTED_DROPS:
            continue
        _REPORTED_DROPS.add(short)
        log(f"excluded {short} from tracking" + (f" — {why}" if why else ""))

    commits.reverse()  # oldest first, so Jira issue order matches history
    return commits


#: Body lines that are metadata, not a claim of delivery. A ticket key
#: mentioned inside one of these is a cross-reference — "this belongs with
#: SIDC-18" — and must not advance that ticket. Found the hard way: a
#: Scope-note naming a related ticket closed it.
TRAILER_PREFIXES = ("decision:", "scope-note:", "co-authored-by:", "signed-off-by:", "refs:")


def referenced_keys(commit: dict[str, Any], project_key: str) -> list[str]:
    """Tickets this commit claims to deliver.

    Deliberately strict: a key counts only if it appears in the subject, or on a
    body line consisting of nothing but keys — which is exactly the convention
    CLAUDE.md prescribes ("SIDC-15" on its own line).

    Prose mentions do NOT count. Rehearsing this caught two ways a loose match
    goes wrong: a Scope-note reading "belongs with SIDC-18" closed SIDC-18, and
    then a commit message *describing that bug* closed it again. Discussing a
    ticket is not delivering it, and silently closing work nobody did is worse
    than missing a link.
    """
    key_re = rf"\b{re.escape(project_key)}-\d+\b"
    found = set(re.findall(key_re, commit["subject"]))

    for line in commit["body"].splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(TRAILER_PREFIXES):
            continue
        # A line that is only keys (optionally comma/space separated).
        if re.fullmatch(rf"(?:{key_re}[,\s]*)+", stripped):
            found.update(re.findall(key_re, stripped))

    return sorted(found)


def mentioned_keys(commit: dict[str, Any], project_key: str) -> list[str]:
    """Tickets named only in trailers — related, but not delivered here."""
    delivered = set(referenced_keys(commit, project_key))
    all_keys = set(
        re.findall(
            rf"\b{re.escape(project_key)}-\d+\b",
            f"{commit['subject']} {commit['body']}",
        )
    )
    return sorted(all_keys - delivered)


# ----------------------------------------------------------------------------
# Atlassian REST client
# ----------------------------------------------------------------------------

class Atlassian:
    def __init__(self, site: str, email: str, token: str, dry_run: bool = False) -> None:
        self.site = site.replace("https://", "").rstrip("/")
        self.base = f"https://{self.site}"
        self.dry_run = dry_run
        blob = base64.b64encode(f"{email}:{token}".encode()).decode()
        self._auth = f"Basic {blob}"

    # -- transport ----------------------------------------------------------
    def _call(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode() or "{}"
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1200]
            if exc.code in (401, 403):
                raise Fail(
                    f"Atlassian rejected the credentials ({exc.code}) on {method} {path}.\n"
                    f"Check ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN and that the account "
                    f"can write to this project and space.\n{detail}"
                ) from exc
            raise Fail(f"{method} {path} -> HTTP {exc.code}\n{detail}") from exc
        except urllib.error.URLError as exc:
            raise Fail(f"could not reach {self.site}: {exc.reason}") from exc

    def get(self, path: str) -> Any:
        return self._call("GET", path)

    def post(self, path: str, payload: dict) -> Any:
        if self.dry_run:
            log(f"[dry-run] POST {path}")
            return {}
        return self._call("POST", path, payload)

    def put(self, path: str, payload: dict) -> Any:
        if self.dry_run:
            log(f"[dry-run] PUT {path}")
            return {}
        return self._call("PUT", path, payload)

    # -- Jira ---------------------------------------------------------------
    def jql(self, query: str, fields: str = "key,summary,labels") -> list[dict]:
        res = self._call(
            "POST",
            "/rest/api/3/search/jql",
            {"jql": query, "maxResults": 100, "fields": fields.split(",")},
        )
        return res.get("issues", []) or []

    def create_issue(self, fields: dict) -> dict:
        return self.post("/rest/api/3/issue", {"fields": fields})

    def comment(self, key: str, adf: dict) -> dict:
        return self.post(f"/rest/api/3/issue/{key}/comment", {"body": adf})

    def issue_status(self, key: str) -> str:
        res = self.get(f"/rest/api/3/issue/{key}?fields=status")
        return res.get("fields", {}).get("status", {}).get("name", "")

    def transitions(self, key: str) -> dict[str, str]:
        """{target status name: transition id}"""
        res = self.get(f"/rest/api/3/issue/{key}/transitions")
        return {t["to"]["name"]: t["id"] for t in res.get("transitions", [])}

    def transition(self, key: str, transition_id: str) -> None:
        self.post(f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": transition_id}})

    def advance_issue(self, key: str, target: str, via: list[str]) -> list[str]:
        """Move an issue to `target`, stepping through `via` first.

        Stepping through intermediate states matters for the demo and for any
        real audit: a ticket that jumps straight from To Do to Done leaves no
        evidence it was ever worked on.
        """
        current = self.issue_status(key)
        if current == target:
            return []

        applied: list[str] = []
        for state in [*via, target]:
            if state == current:
                continue
            avail = self.transitions(key)
            tid = avail.get(state)
            if not tid:
                continue
            self.transition(key, tid)
            applied.append(state)
            current = state
            if state == target:
                break
        return applied

    def issue_index(self, project_key: str, keys: list[str]) -> dict[str, dict]:
        """One call for many issues. Used for both syncing and page generation."""
        if not keys:
            return {}
        joined = ", ".join(sorted(set(keys)))
        try:
            issues = self.jql(f"project = {project_key} AND key IN ({joined})")
        except Fail as exc:
            log(f"could not load issue index (non-fatal): {exc}")
            return {}
        return {
            i["key"]: {
                "summary": i["fields"].get("summary", ""),
                "labels": i["fields"].get("labels", []),
            }
            for i in issues
        }

    # -- Confluence ---------------------------------------------------------
    def space_id(self, key: str) -> str:
        res = self.get(f"/wiki/api/v2/spaces?keys={urllib.parse.quote(key)}")
        results = res.get("results", []) or []
        if not results:
            raise Fail(f"Confluence space '{key}' not found on {self.site}")
        return str(results[0]["id"])

    def find_page(self, space_id: str, title: str) -> dict | None:
        res = self.get(
            f"/wiki/api/v2/spaces/{space_id}/pages"
            f"?title={urllib.parse.quote(title)}&status=current&limit=5"
        )
        results = res.get("results", []) or []
        return results[0] if results else None

    def page(self, page_id: str) -> dict:
        return self.get(f"/wiki/api/v2/pages/{page_id}?body-format=storage")

    def last_human_edit(self, page_id: str) -> str | None:
        """When a person last changed this page, ignoring the sync's own edits.

        Without this distinction the staleness check is self-defeating: stamping
        the status badge would count as an edit and the page would look freshly
        reviewed forever.
        """
        try:
            res = self.get(f"/wiki/api/v2/pages/{page_id}/versions?limit=50")
        except Fail:
            return None
        for v in res.get("results", []) or []:  # newest first
            msg = (v.get("message") or "").strip()
            if not msg.startswith(SYNC_VERSION_PREFIX):
                return v.get("createdAt")
        return None

    def replace_section(
        self, page_id: str, heading: str, new_html: str, version_message: str
    ) -> str:
        """Swap one <h2> section of a page, leaving the rest of the body alone.

        Returns "inserted", "replaced", or "unchanged". This is what makes it
        safe to write into a page a human also owns.
        """
        if self.dry_run:
            log(f"[dry-run] would update '{heading}' section on page {page_id}")
            return "dry-run"

        current = self.page(page_id)
        body = current.get("body", {}).get("storage", {}).get("value", "")
        block = f"<h2>{heading}</h2>{new_html}"

        pattern = re.compile(
            rf"<h2>\s*{re.escape(heading)}\s*</h2>.*?(?=<h2[\s>]|\Z)", re.S
        )
        if pattern.search(body):
            updated = pattern.sub(block, body, count=1)
            action = "replaced"
        else:
            updated = block + body
            action = "inserted"

        if updated == body:
            return "unchanged"

        self.put(
            f"/wiki/api/v2/pages/{page_id}",
            {
                "id": str(page_id),
                "status": "current",
                "title": current["title"],
                "body": {"representation": "storage", "value": updated},
                "version": {
                    "number": int(current["version"]["number"]) + 1,
                    "message": f"{SYNC_VERSION_PREFIX} {version_message}",
                },
            },
        )
        return action

    def footer_comment(self, page_id: str, storage_html: str) -> dict:
        """Comment on a page. Comments survive body regeneration, which is what
        makes them the right place for an audit trail on a derived page."""
        return self.post(
            "/wiki/api/v2/footer-comments",
            {"pageId": str(page_id), "body": {"representation": "storage", "value": storage_html}},
        )

    def upsert_page(
        self, space_id: str, title: str, storage_html: str, parent_id: str | None
    ) -> dict:
        # Guard before the lookup: dry-run must not touch the network at all,
        # and find_page is a GET, which the transport layer does not gate.
        if self.dry_run:
            log(f"[dry-run] would upsert page '{title}' ({len(storage_html)} bytes of storage HTML)")
            return {"id": "", "created": False}

        existing = self.find_page(space_id, title)
        body = {"representation": "storage", "value": storage_html}

        if existing:
            page_id = str(existing["id"])
            current = self.get(f"/wiki/api/v2/pages/{page_id}")
            version = int(current.get("version", {}).get("number", 1))
            payload = {
                "id": page_id,
                "status": "current",
                "title": title,
                "body": body,
                "version": {"number": version + 1, "message": "Regenerated by atlassian_sync"},
            }
            self.put(f"/wiki/api/v2/pages/{page_id}", payload)
            return {"id": page_id, "created": False}

        payload = {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "body": body,
        }
        if parent_id:
            payload["parentId"] = str(parent_id)
        res = self.post("/wiki/api/v2/pages", payload)
        return {"id": str(res.get("id", "")), "created": True}


# ----------------------------------------------------------------------------
# preflight
# ----------------------------------------------------------------------------

def preflight(api: Atlassian, cfg: dict) -> None:
    """Verify who we are and that we can actually see the targets.

    Worth the three extra calls: without this, a credential pointing at the
    wrong Atlassian account fails much later with Jira's misleading
    "target project doesn't exist or you don't have permission" — which reads
    like a config error when it is really an identity error.
    """
    who = api.get("/rest/api/3/myself")
    account = who.get("emailAddress") or who.get("accountId", "unknown")
    log(f"authenticated as: {who.get('displayName', '?')} <{account}>")

    project_key = cfg["jira"]["project_key"]
    try:
        proj = api.get(f"/rest/api/3/project/{project_key}")
        log(f"jira project visible: {proj.get('key')} — {proj.get('name')}")
    except Fail as exc:
        raise Fail(
            f"The account above cannot see Jira project '{project_key}'.\n"
            f"This is an identity problem, not a config one: the API token "
            f"belongs to an account without access to that project.\n"
            f"Fix ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN so they belong to an "
            f"account that can create issues in {project_key}.\n\n{exc}"
        ) from exc

    space_key = cfg["confluence"]["space_key"]
    res = api.get(f"/wiki/api/v2/spaces?keys={urllib.parse.quote(space_key)}")
    if not (res.get("results") or []):
        raise Fail(
            f"The account above cannot see Confluence space '{space_key}'.\n"
            f"Grant it access, or use credentials for an account that has it."
        )
    log(f"confluence space visible: {space_key}")


# ----------------------------------------------------------------------------
# ADF builders (Jira v3 wants Atlassian Document Format, not markdown)
# ----------------------------------------------------------------------------

def adf_text(s: str) -> dict:
    return {"type": "text", "text": s}


def adf_para(*nodes: dict) -> dict:
    return {"type": "paragraph", "content": list(nodes)}


def adf_doc(*blocks: dict) -> dict:
    return {"type": "doc", "version": 1, "content": list(blocks)}


def adf_code(text: str) -> dict:
    return {
        "type": "codeBlock",
        "attrs": {"language": "text"},
        "content": [adf_text(text)] if text else [],
    }


def adf_link(text: str, href: str) -> dict:
    return {"type": "text", "text": text, "marks": [{"type": "link", "attrs": {"href": href}}]}


def commit_description(commit: dict, repo_url: str) -> dict:
    sha_url = f"{repo_url}/commit/{commit['sha']}"
    blocks = [
        adf_para(adf_text("Filed automatically from a git commit. ")),
        adf_para(
            adf_text("Commit: "),
            adf_link(commit["short"], sha_url),
            adf_text(f"  ·  Author: {commit['author']}  ·  {commit['date']}"),
        ),
    ]
    if commit["body"]:
        blocks.append(adf_para(adf_text(commit["body"][:2000])))
    if commit["areas"]:
        blocks.append(adf_para(adf_text("Areas touched: " + ", ".join(commit["areas"]))))
    if commit["files"]:
        listing = "\n".join(commit["files"][:40])
        if len(commit["files"]) > 40:
            listing += f"\n… and {len(commit['files']) - 40} more"
        blocks.append(adf_code(listing))
    return adf_doc(*blocks)


# ----------------------------------------------------------------------------
# Confluence page bodies (storage format = XHTML)
# ----------------------------------------------------------------------------

def storage_release_log(
    commits: list[dict],
    cfg: dict,
    synced_at: str,
    divergence: list[dict] | None = None,
    gaps: list[dict] | None = None,
    stale: list[dict] | None = None,
) -> str:
    repo_url = cfg["repo"]["web_url"]
    jira_url = cfg["jira"]["project_url"]
    site_base = f"https://{cfg['site']}"
    project = cfg["jira"]["project_key"]
    newest_first = list(reversed(commits))

    by_area: dict[str, int] = {}
    for c in commits:
        for a in c["areas"] or ["Unclassified"]:
            by_area[a] = by_area.get(a, 0) + 1

    def ticket_links(c: dict) -> str:
        refs = referenced_keys(c, project)
        if not refs:
            return "<em>unplanned</em>"
        return ", ".join(
            f"<a href='{escape(site_base)}/browse/{escape(r)}'>{escape(r)}</a>"
            for r in refs
        )

    rows = "".join(
        f"<tr>"
        f"<td><a href='{escape(repo_url)}/commit/{escape(c['sha'])}'>"
        f"<code>{escape(c['short'])}</code></a></td>"
        f"<td>{escape(c['subject'])}</td>"
        f"<td>{ticket_links(c)}</td>"
        f"<td>{escape(', '.join(c['areas']) or '—')}</td>"
        f"<td>{escape(c['date'][:10])}</td>"
        f"</tr>"
        for c in newest_first
    )

    div_rows = "".join(
        f"<tr>"
        f"<td><a href='{escape(repo_url)}/commit/{escape(d['sha'])}'>"
        f"<code>{escape(d['short'])}</code></a></td>"
        f"<td>{escape(d['subject'])}</td>"
        f"<td>{escape(d['kind'])}</td>"
        f"<td>{escape(', '.join(d['areas']) or '—')}</td>"
        f"</tr>"
        for d in (divergence or [])
    )
    divergence_section = (
        f"""
<h2>Unplanned changes in the last sync</h2>
<p>Work that landed outside the scope of the ticket it referenced, or with no
ticket at all. Recorded rather than filed as new work, so the plan stays the
plan and the record still matches what shipped.</p>
<table>
  <thead><tr><th>Commit</th><th>Change</th><th>Why flagged</th><th>Area</th></tr></thead>
  <tbody>{div_rows}</tbody>
</table>
"""
        if div_rows
        else ""
    )

    gap_rows = "".join(
        f"<tr>"
        f"<td><a href='{escape(site_base)}/browse/{escape(g['key'])}'>"
        f"{escape(g['key'])}</a></td>"
        f"<td>{escape(g['summary'])}</td>"
        f"</tr>"
        for g in (gaps or [])
    )
    gap_section = (
        f"""
<ac:structured-macro ac:name="warning">
  <ac:rich-text-body>
    <p><strong>Marked Done, but no commit references them.</strong> The inverse of
    unplanned work, and the more uncomfortable direction: work claimed rather
    than work unrecorded. Either the commit forgot its ticket reference, or the
    ticket was closed without a change behind it. Both are worth knowing.</p>
  </ac:rich-text-body>
</ac:structured-macro>
<table>
  <thead><tr><th>Ticket</th><th>Summary</th></tr></thead>
  <tbody>{gap_rows}</tbody>
</table>
"""
        if gap_rows
        else ""
    )

    stale_rows = "".join(
        f"<tr>"
        f"<td><a href='{escape(cfg['confluence']['space_url'].rsplit('/', 1)[0])}"
        f"/pages/{escape(s['page_id'])}'>{escape(s['title'])}</a></td>"
        f"<td>{escape(', '.join(s['tickets']))}</td>"
        f"<td>{escape(s['edited'])}</td>"
        f"<td>{escape(s['implemented'])}</td>"
        f"</tr>"
        for s in (stale or [])
    )
    stale_section = (
        f"""
<h2>Specs that may be out of date</h2>
<ac:structured-macro ac:name="note">
  <ac:rich-text-body>
    <p>The work implementing these specs landed <em>after</em> a person last edited
    them. Nothing is broken, which is exactly why this goes unnoticed: the
    document still reads as current while the code has moved on. Re-saving a page
    after reviewing it clears the flag.</p>
  </ac:rich-text-body>
</ac:structured-macro>
<table>
  <thead><tr><th>Spec</th><th>Tickets</th><th>Last human edit</th><th>Implemented</th></tr></thead>
  <tbody>{stale_rows}</tbody>
</table>
"""
        if stale_rows
        else ""
    )

    area_rows = "".join(
        f"<tr><td>{escape(area)}</td><td>{count}</td></tr>"
        for area, count in sorted(by_area.items(), key=lambda kv: -kv[1])
    )

    return f"""
<ac:structured-macro ac:name="info">
  <ac:rich-text-body>
    <p><strong>This page is generated.</strong> It is rewritten in full from
    <code>git log</code> every time a commit lands in
    <a href="{escape(repo_url)}">{escape(cfg['repo']['slug'])}</a>.
    Edits made by hand here will be overwritten on the next sync &mdash; change the
    repository instead.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>At a glance</h2>
<table>
  <tbody>
    <tr><th>Commits tracked</th><td>{len(commits)}</td></tr>
    <tr><th>Last synced</th><td>{escape(synced_at)}</td></tr>
    <tr><th>Repository</th><td><a href="{escape(repo_url)}">{escape(cfg['repo']['slug'])}</a></td></tr>
    <tr><th>Jira project</th><td><a href="{escape(jira_url)}">{escape(cfg['jira']['project_key'])}</a></td></tr>
  </tbody>
</table>

<h2>Where the work went</h2>
<table>
  <thead><tr><th>Area</th><th>Commits</th></tr></thead>
  <tbody>{area_rows or "<tr><td>—</td><td>0</td></tr>"}</tbody>
</table>

{divergence_section}
{f"<h2>Evidence gaps</h2>{gap_section}" if gap_section else ""}
{stale_section}
<h2>Release history</h2>
<table>
  <thead>
    <tr><th>Commit</th><th>Change</th><th>Ticket</th><th>Area</th><th>Date</th></tr>
  </thead>
  <tbody>{rows or "<tr><td colspan='5'>No commits yet.</td></tr>"}</tbody>
</table>
""".strip()


def _iso_day(ts: str | None) -> str:
    """Date and time, because same-day comparisons are the common case.

    "landed on 2026-08-26, after the page was edited on 2026-08-26" reads as
    nonsense even when it is true.
    """
    dt = to_utc(ts)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "unknown"


def to_utc(ts: str | None) -> datetime | None:
    """Parse a timestamp to an aware UTC datetime.

    Necessary because the two sources disagree on format: git's %aI is local
    time with a numeric offset, Confluence returns UTC with a trailing Z and
    milliseconds. Comparing those as strings silently gives the wrong answer for
    anyone not sitting in UTC — which is how the staleness check first failed.
    """
    if not ts:
        return None
    raw = ts.strip().replace("Z", "+00:00")
    # fromisoformat on older Pythons chokes on more than 6 fractional digits
    raw = re.sub(r"\.(\d{6})\d+", r".\1", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sync_spec_pages(
    api: Atlassian, cfg: dict, all_commits: list[dict], synced_at: str
) -> list[dict]:
    """Stamp each spec page with its implementation state, and flag stale specs.

    A spec is stale when the work implementing it landed *after* the last time a
    human touched the spec. That is the quiet failure mode of written plans: the
    doc still reads as current, the code has moved on, and nobody notices because
    nothing is broken. Cheap to detect once commits name their tickets.

    Returns stale records for the Release Log.
    """
    conf = cfg["confluence"]
    project = cfg["jira"]["project_key"]
    spec_map = conf.get("spec_pages") or {}
    site_base = f"https://{cfg['site']}"
    repo_url = cfg["repo"]["web_url"]

    if not spec_map or api.dry_run:
        return []

    # label -> [tickets], via one query
    try:
        labels = ", ".join(f'"{l}"' for l in sorted(spec_map))
        issues = api.jql(
            f"project = {project} AND labels IN ({labels}) ORDER BY key ASC",
            fields="key,summary,labels,status",
        )
    except Fail as exc:
        log(f"could not load spec tickets (non-fatal): {exc}")
        return []

    # ticket -> latest commit that referenced it
    last_commit: dict[str, dict] = {}
    for c in all_commits:  # oldest first, so the last write wins
        for r in referenced_keys(c, project):
            last_commit[r] = c

    # page -> tickets governed by it
    by_page: dict[str, list[dict]] = {}
    for issue in issues:
        for label in issue["fields"].get("labels", []):
            page = spec_map.get(label)
            if page:
                by_page.setdefault(page, []).append(issue)
                break

    stale: list[dict] = []
    for page_id, tickets in by_page.items():
        edited = api.last_human_edit(page_id)
        try:
            title = api.page(page_id)["title"]
        except Fail:
            title = f"page {page_id}"

        edited_dt = to_utc(edited)
        rows, newest_impl, is_stale = [], None, False
        for t in sorted(tickets, key=lambda i: i["key"]):
            key = t["key"]
            status = t["fields"].get("status", {}).get("name", "?")
            done = status.lower() == str(cfg["jira"].get("done_status", "Done")).lower()
            c = last_commit.get(key)

            colour = "green" if done else ("blue" if c else "neutral")
            evidence = (
                f"<a href='{escape(repo_url)}/commit/{escape(c['sha'])}'>"
                f"<code>{escape(c['short'])}</code></a> · {escape(c['date'][:10])}"
                if c
                else "<em>no commit yet</em>"
            )

            commit_dt = to_utc(c["date"]) if c else None
            if done and commit_dt and edited_dt and commit_dt > edited_dt:
                is_stale = True
                if newest_impl is None or commit_dt > to_utc(newest_impl):
                    newest_impl = c["date"]

            rows.append(
                f"<tr>"
                f"<td><a href='{escape(site_base)}/browse/{escape(key)}'>{escape(key)}</a></td>"
                f"<td>{escape(t['fields'].get('summary', ''))}</td>"
                f"<td><ac:structured-macro ac:name='status'>"
                f"<ac:parameter ac:name='title'>{escape(status.upper())}</ac:parameter>"
                f"<ac:parameter ac:name='colour'>{colour}</ac:parameter>"
                f"</ac:structured-macro></td>"
                f"<td>{evidence}</td>"
                f"</tr>"
            )

        verdict = (
            "<ac:structured-macro ac:name='warning'><ac:rich-text-body>"
            f"<p><strong>This spec may be out of date.</strong> Work implementing it "
            f"landed on {escape(_iso_day(newest_impl))}, after this page was last "
            f"edited by a person on {escape(_iso_day(edited))}. The code has moved; "
            f"the words here may not have. Worth a read — and if it is still "
            f"accurate, just re-save the page to clear this.</p>"
            "</ac:rich-text-body></ac:structured-macro>"
            if is_stale
            else "<ac:structured-macro ac:name='tip'><ac:rich-text-body>"
            f"<p>Spec is current: last edited by a person on "
            f"{escape(_iso_day(edited))}, no implementing work has landed since.</p>"
            "</ac:rich-text-body></ac:structured-macro>"
        )

        block = (
            "<ac:structured-macro ac:name='info'><ac:rich-text-body>"
            "<p>Generated section. The table and the verdict below are written by "
            "<code>scripts/atlassian_sync.py</code> on every sync. Everything else on "
            "this page is hand-maintained and untouched.</p>"
            "</ac:rich-text-body></ac:structured-macro>"
            f"{verdict}"
            "<table><thead><tr><th>Ticket</th><th>Summary</th><th>Status</th>"
            "<th>Evidence</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
            f"<p><em>Checked {escape(synced_at)}.</em></p>"
        )

        action = api.replace_section(
            page_id, STATUS_HEADING, block, "implementation status"
        )
        flag = " — STALE" if is_stale else ""
        log(f"spec '{title}': status {action}{flag}")

        if is_stale:
            stale.append(
                {
                    "page_id": page_id,
                    "title": title,
                    "edited": _iso_day(edited),
                    "implemented": _iso_day(newest_impl),
                    "tickets": [t["key"] for t in tickets],
                }
            )

    return stale


def storage_decision_log(commits: list[dict], cfg: dict, synced_at: str) -> str:
    repo_url = cfg["repo"]["web_url"]
    site_base = f"https://{cfg['site']}"
    project = cfg["jira"]["project_key"]
    trailer = (cfg.get("docs") or {}).get("decision_trailer", "Decision:")
    newest_first = list(reversed(commits))

    rows = []
    for c in newest_first:
        for d in decisions_in(c, trailer):
            refs = referenced_keys(c, project)
            ticket = (
                ", ".join(
                    f"<a href='{escape(site_base)}/browse/{escape(r)}'>{escape(r)}</a>"
                    for r in refs
                )
                or "—"
            )
            rows.append(
                f"<tr>"
                f"<td>{escape(d)}</td>"
                f"<td>{ticket}</td>"
                f"<td><a href='{escape(repo_url)}/commit/{escape(c['sha'])}'>"
                f"<code>{escape(c['short'])}</code></a></td>"
                f"<td>{escape(c['date'][:10])}</td>"
                f"</tr>"
            )

    empty = (
        "<tr><td colspan='4'>No decisions recorded yet. Add a "
        "<code>Decision:</code> line to a commit message and it appears here.</td></tr>"
    )

    return f"""
<ac:structured-macro ac:name="info">
  <ac:rich-text-body>
    <p><strong>This page is generated.</strong> Every line comes from a
    <code>{escape(trailer)}</code> trailer in a commit message, rebuilt from
    <code>git log</code> on each sync. Hand edits are overwritten.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>Why this exists</h2>
<p>Decisions are the first thing lost and the most expensive to reconstruct. They
get made in a chat window, never written down, and six months later nobody can
say why the thing is the way it is. Architecture decision records solve this and
almost nobody keeps them up, because the ceremony costs more than the benefit.</p>
<p>A commit trailer costs one line, sits next to the change it justifies, and
cannot drift from the code — because it <em>is</em> the code's history. This page is
just that history, made readable.</p>

<h2>How to add one</h2>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">text</ac:parameter>
  <ac:plain-text-body><![CDATA[Rebuild the design system from tokens

Decision: no CSS framework — three static files outlive any dependency
Decision: light mode re-picked rather than inverted, because the accent fails on white

SIDC-16]]></ac:plain-text-body>
</ac:structured-macro>

<h2>Decisions</h2>
<table>
  <thead><tr><th>Decision</th><th>Ticket</th><th>Commit</th><th>Date</th></tr></thead>
  <tbody>{''.join(rows) or empty}</tbody>
</table>

<p><em>Last synced {escape(synced_at)}. {len(rows)} decision(s) recorded.</em></p>
""".strip()


def storage_divergence_comment(
    divergence: list[dict], cfg: dict, synced_at: str
) -> str:
    """Footer comment posted to a spec page when reality left its scope."""
    repo_url = cfg["repo"]["web_url"]
    items = "".join(
        f"<li><a href='{escape(repo_url)}/commit/{escape(d['sha'])}'>"
        f"<code>{escape(d['short'])}</code></a> — {escape(d['subject'])} "
        f"(also touched {escape(', '.join(d['areas']))})</li>"
        for d in divergence
    )
    return (
        f"<p><strong>Reality diverged from this spec.</strong> A commit delivered "
        f"work described here and also went beyond it:</p>"
        f"<ul>{items}</ul>"
        f"<p>Nothing was filed as new work — the record was updated instead. "
        f"If the extra scope should have been part of this spec, this page is the "
        f"thing to change. Posted automatically at {escape(synced_at)}.</p>"
    )


def storage_changelog(commits: list[dict], cfg: dict, synced_at: str) -> str:
    repo_url = cfg["repo"]["web_url"]
    newest_first = list(reversed(commits))

    sections = []
    for c in newest_first:
        files = "".join(f"<li><code>{escape(f)}</code></li>" for f in c["files"][:60])
        if len(c["files"]) > 60:
            files += f"<li>… and {len(c['files']) - 60} more</li>"
        body = f"<p>{escape(c['body'])}</p>" if c["body"] else ""
        sections.append(
            f"<h3>{escape(c['subject'])}</h3>"
            f"<p><a href='{escape(repo_url)}/commit/{escape(c['sha'])}'>"
            f"<code>{escape(c['short'])}</code></a>"
            f" &middot; {escape(c['author'])}"
            f" &middot; {escape(c['date'])}"
            f" &middot; {escape(', '.join(c['areas']) or 'unclassified')}</p>"
            f"{body}"
            f"<p><strong>Files changed ({len(c['files'])})</strong></p>"
            f"<ul>{files or '<li>none</li>'}</ul>"
        )

    return f"""
<ac:structured-macro ac:name="info">
  <ac:rich-text-body>
    <p><strong>Generated page.</strong> Full per-commit detail, newest first.
    Rewritten from <code>git log</code> on every sync. Last run: {escape(synced_at)}.</p>
  </ac:rich-text-body>
</ac:structured-macro>
{''.join(sections) or '<p>No commits yet.</p>'}
""".strip()


# ----------------------------------------------------------------------------
# Jira sync
# ----------------------------------------------------------------------------

def ensure_workstream(api: Atlassian, cfg: dict) -> str | None:
    """Find or create the parent Workstream that auto-filed Tasks hang under."""
    jira = cfg["jira"]
    key = jira["project_key"]
    summary = jira["workstream_summary"]

    safe = summary.replace('"', '\\"')
    found = api.jql(f'project = {key} AND summary ~ "\\"{safe}\\"" ORDER BY created ASC')
    for issue in found:
        if issue["fields"]["summary"].strip() == summary:
            log(f"workstream exists: {issue['key']}")
            return issue["key"]

    if api.dry_run:
        log(f"[dry-run] would create Workstream '{summary}'")
        return None

    res = api.create_issue(
        {
            "project": {"key": key},
            "summary": summary,
            "issuetype": {"name": jira["parent_issue_type"]},
            "labels": jira["labels"],
            "description": adf_doc(
                adf_para(
                    adf_text("Umbrella for automated build and release work on "),
                    adf_link(cfg["repo"]["slug"], cfg["repo"]["web_url"]),
                    adf_text("."),
                ),
                adf_para(
                    adf_text(
                        "Tasks under this Workstream are filed by scripts/atlassian_sync.py, "
                        "one per commit. Mention an existing issue key in a commit message to "
                        "comment on that issue instead of opening a new one."
                    )
                ),
            ),
        }
    )
    created = res.get("key")
    log(f"created workstream: {created}")
    return created


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def decisions_in(commit: dict, trailer: str) -> list[str]:
    """Pull `Decision: ...` lines out of a commit body.

    Decisions are the thing that always evaporates. They get made in a chat
    window or a code review, never written down, and six months later nobody can
    reconstruct why. A commit trailer is the cheapest possible capture point:
    zero ceremony, and it sits next to the change it justifies.
    """
    found: list[str] = []
    for line in commit["body"].splitlines():
        line = line.strip()
        if line.lower().startswith(trailer.lower()):
            text = line[len(trailer):].strip(" :-—")
            if text:
                found.append(text)
    return found


def evidence_gaps(
    api: Atlassian, cfg: dict, all_commits: list[dict]
) -> list[dict]:
    """Tickets marked Done that no commit ever references.

    The inverse of divergence, and the more uncomfortable direction: work
    *claimed* rather than work *unrecorded*. A board full of Done cards with no
    corresponding change is the failure mode that status reporting is famous for.
    Cheap to check once the commits already name their tickets.
    """
    project = cfg["jira"]["project_key"]
    if api.dry_run:
        return []

    referenced = {r for c in all_commits for r in referenced_keys(c, project)}
    try:
        done = api.jql(
            f'project = {project} AND statusCategory = Done '
            f'AND labels = "demo-scope" ORDER BY key ASC'
        )
    except Fail as exc:
        log(f"could not run evidence check (non-fatal): {exc}")
        return []

    return [
        {"key": i["key"], "summary": i["fields"].get("summary", "")}
        for i in done
        if i["key"] not in referenced
    ]


def declared_scope_notes(commit: dict, trailer: str) -> list[str]:
    """`Scope-note:` lines — drift the author declares rather than us inferring.

    Path-based detection is structurally blind to scope creep inside a file the
    ticket already claims: adding a block of CSS to a page the AEO ticket owns
    is real design work, and no amount of prefix matching will see it. In the
    first live run the agent noticed this about itself and said so in the commit
    message while the tooling stayed silent. This makes that channel first-class
    rather than incidental.
    """
    found: list[str] = []
    for line in commit["body"].splitlines():
        line = line.strip()
        if line.lower().startswith(trailer.lower()):
            text = line[len(trailer):].strip(" :-—")
            if text:
                found.append(text)
    return found


def unplanned_areas(commit: dict, refs: list[str], index: dict[str, dict]) -> list[str]:
    """Areas the commit touched that none of its referenced tickets claim.

    This is the divergence signal. Work drifts — you set out to do the AEO pass
    and end up also fixing the nav. That extra scope is real and should land in
    the record, rather than quietly disappearing because the ticket said
    something narrower.
    """
    claimed: set[str] = set()
    for ref in refs:
        claimed.update(index.get(ref, {}).get("labels", []))
    return [a for a in commit["areas"] if slug(a) not in claimed]


def sync_jira(
    api: Atlassian, cfg: dict, commits: list[dict], parent: str | None
) -> tuple[dict[str, dict], list[dict]]:
    """Update the existing plan rather than growing it.

    Returns ({sha: {key, url, action}}, [divergence records]).

    Default mode is "update": a commit advances the tickets it references and
    reports anything outside their scope. It does not mint a ticket per commit —
    that turns a plan into a changelog and makes the board unreadable. Set
    jira.commit_mode to "create" for the old per-commit behaviour.
    """
    jira = cfg["jira"]
    project = jira["project_key"]
    mode = jira.get("commit_mode", "update")
    target = jira.get("done_status", "Done")
    via = jira.get("progress_states", ["In Progress"])
    repo_url = cfg["repo"]["web_url"]

    # A full resync would otherwise post a divergence comment for every commit
    # that predates the ticket-reference convention. Records stay complete; only
    # the commenting is capped.
    comment_budget = int(jira.get("divergence_comment_limit", 5))
    scope_trailer = (cfg.get("docs") or {}).get("scope_trailer", "Scope-note:")

    results: dict[str, dict] = {}
    divergence: list[dict] = []

    all_refs = [r for c in commits for r in referenced_keys(c, project)]
    index = {} if api.dry_run else api.issue_index(project, all_refs)

    for c in commits:
        commit_url = f"{repo_url}/commit/{c['sha']}"
        refs = referenced_keys(c, project)

        # ---- no ticket referenced: entirely unplanned work ----------------
        if not refs:
            if mode == "create":
                results[c["sha"]] = _create_commit_task(api, cfg, c, parent)
                continue

            divergence.append(
                {
                    "sha": c["sha"],
                    "short": c["short"],
                    "subject": c["subject"],
                    "areas": c["areas"],
                    "kind": "no ticket referenced",
                    "refs": [],
                }
            )
            if parent and not api.dry_run and comment_budget > 0:
                comment_budget -= 1
                api.comment(
                    parent,
                    adf_doc(
                        adf_para(
                            adf_text("Unplanned change landed with no ticket reference: "),
                            adf_link(c["short"], commit_url),
                            adf_text(f" — {c['subject']}"),
                        ),
                        adf_para(
                            adf_text(
                                f"Areas: {', '.join(c['areas']) or 'unclassified'} · "
                                f"{len(c['files'])} file(s). Logged here rather than "
                                f"opening a ticket, so the plan stays the plan."
                            )
                        ),
                    ),
                )
            log(f"{c['short']} -> no ticket referenced, noted on {parent or 'workstream'}")
            results[c["sha"]] = {"key": None, "url": None, "action": "divergence"}
            continue

        # ---- tickets referenced: comment and advance them ------------------
        extra = unplanned_areas(c, refs, index)
        declared = declared_scope_notes(c, scope_trailer)
        unknown = c.get("unclassified") or []
        if unknown:
            log(
                f"{c['short']} -> {len(unknown)} unclassified file(s): "
                + ", ".join(unknown[:4])
                + (" …" if len(unknown) > 4 else "")
                + " — add a prefix to atlassian.config.json areas"
            )

        for ref in refs:
            if api.dry_run:
                log(f"[dry-run] {c['short']} -> would advance {ref} to {target}")
                continue

            blocks = [
                adf_para(
                    adf_text("Delivered by "),
                    adf_link(c["short"], commit_url),
                    adf_text(f" — {c['subject']}"),
                ),
                adf_para(
                    adf_text(
                        f"Areas: {', '.join(c['areas']) or 'unclassified'} · "
                        f"{len(c['files'])} file(s) · {c['author']}"
                    )
                ),
            ]
            if extra:
                blocks.append(
                    adf_para(
                        adf_text(
                            "Scope note — this commit also touched "
                            + ", ".join(extra)
                            + ", which this ticket does not cover."
                        )
                    )
                )
            for note in declared:
                blocks.append(
                    adf_para(adf_text(f"Declared scope note — {note}"))
                )
            api.comment(ref, adf_doc(*blocks))

            moved = api.advance_issue(ref, target, via)
            trail = " → ".join(moved) if moved else f"already {target}"
            log(f"{c['short']} -> {ref}: {trail}")

        # Say this out loud. Catching drift is the whole point, and a silent
        # catch is indistinguishable from no catch.
        if extra:
            log(
                f"{c['short']} -> divergence: also touched {', '.join(extra)} "
                f"(outside {', '.join(refs)}) — recorded, not filed"
            )
        for note in declared:
            log(f"{c['short']} -> declared scope note: {note[:80]}")
        related = mentioned_keys(c, project)
        if related:
            log(
                f"{c['short']} -> mentions {', '.join(related)} in a trailer "
                f"— cross-reference only, not advanced"
            )

        if extra or declared:
            detail = ", ".join(extra) if extra else "; ".join(declared)
            divergence.append(
                {
                    "sha": c["sha"],
                    "short": c["short"],
                    "subject": c["subject"],
                    "areas": extra or ["(within a claimed file)"],
                    "kind": (
                        "declared by author"
                        if declared and not extra
                        else "scope beyond the ticket"
                    ),
                    "declared": declared,
                    "refs": refs,
                }
            )
            if parent and not api.dry_run and comment_budget > 0:
                comment_budget -= 1
                api.comment(
                    parent,
                    adf_doc(
                        adf_para(
                            adf_text("Scope divergence on "),
                            adf_link(c["short"], commit_url),
                            adf_text(f" ({', '.join(refs)}): "),
                            adf_text(detail),
                        ),
                        adf_para(
                            adf_text(
                                "Not filed as new work — recorded against the "
                                "existing plan so the record matches what shipped."
                            )
                        ),
                    ),
                )

        results[c["sha"]] = {
            "key": refs[0],
            "url": f"https://{api.site}/browse/{refs[0]}",
            "action": "advanced",
            "refs": refs,
        }

    return results, divergence


def _create_commit_task(
    api: Atlassian, cfg: dict, c: dict, parent: str | None
) -> dict:
    """Legacy per-commit ticket creation. Only used when commit_mode is "create"."""
    jira = cfg["jira"]
    project = jira["project_key"]
    sha_label = f"sha-{c['short']}"

    existing = api.jql(f'project = {project} AND labels = "{sha_label}"')
    if existing:
        found = existing[0]["key"]
        log(f"{c['short']} -> already tracked by {found}")
        return {
            "key": found,
            "url": f"https://{api.site}/browse/{found}",
            "action": "existing",
        }

    if api.dry_run:
        log(f"[dry-run] {c['short']} -> would create Task: {c['subject']}")
        return {"key": None, "url": None, "action": "dry-run"}

    fields = {
        "project": {"key": project},
        "summary": c["subject"][:250] or f"Commit {c['short']}",
        "issuetype": {"name": jira["task_issue_type"]},
        "labels": list(
            dict.fromkeys([*jira["labels"], sha_label, *(slug(a) for a in c["areas"])])
        ),
        "description": commit_description(c, cfg["repo"]["web_url"]),
    }
    if parent:
        fields["parent"] = {"key": parent}

    try:
        res = api.create_issue(fields)
    except Fail as exc:
        if parent and "parent" in str(exc).lower():
            log(f"{c['short']} -> parent rejected, filing without it")
            fields.pop("parent", None)
            res = api.create_issue(fields)
        else:
            raise

    new_key = res.get("key")
    log(f"{c['short']} -> created {new_key}")
    return {
        "key": new_key,
        "url": f"https://{api.site}/browse/{new_key}",
        "action": "created",
    }


# ----------------------------------------------------------------------------
# build-info.json — what the website reads
# ----------------------------------------------------------------------------

def backfill_issue_keys(
    api: Atlassian, cfg: dict, commits: list[dict], jira_map: dict[str, dict]
) -> None:
    """Fill in issue keys for commits synced by an *earlier* run.

    jira_map only covers the current range, so without this the site's table
    shows a blank Jira column for every older commit. One JQL by label covers
    the whole visible window.
    """
    project = cfg["jira"]["project_key"]
    site = api.site

    # Cheapest source first: a commit that names its ticket needs no API call.
    from_message = 0
    for c in commits:
        if c["sha"] in jira_map:
            continue
        refs = referenced_keys(c, project)
        if refs:
            jira_map[c["sha"]] = {
                "key": refs[0],
                "url": f"https://{site}/browse/{refs[0]}",
                "action": "referenced",
            }
            from_message += 1
    if from_message:
        log(f"resolved {from_message} ticket ref(s) from commit messages")

    missing = [c for c in commits if c["sha"] not in jira_map]
    if not missing or api.dry_run:
        return

    labels = ", ".join(f'"sha-{c["short"]}"' for c in missing)
    try:
        issues = api.jql(
            f'project = {cfg["jira"]["project_key"]} AND labels IN ({labels})'
        )
    except Fail as exc:
        log(f"could not backfill issue keys (non-fatal): {exc}")
        return

    by_label: dict[str, str] = {}
    for issue in issues:
        for label in issue["fields"].get("labels", []):
            if label.startswith("sha-"):
                by_label[label] = issue["key"]

    filled = 0
    for c in missing:
        key = by_label.get(f"sha-{c['short']}")
        if key:
            jira_map[c["sha"]] = {
                "key": key,
                "url": f"https://{api.site}/browse/{key}",
                "action": "backfilled",
            }
            filled += 1
    log(f"backfilled {filled} issue key(s) from earlier runs")


def write_release_notes(
    cfg: dict,
    all_commits: list[dict],
    divergence: list[dict],
    synced_at: str,
) -> list[Path]:
    """Generate docs/releases/ from git history.

    Derived state, same contract as the Confluence pages: regenerated in full
    every run, never appended to, so it cannot drift and re-running is free.
    Anything hand-written here will be overwritten.

    Layout is per-ticket rather than per-commit on purpose. One file per commit
    would be a changelog with extra steps; one file per ticket answers the
    question people actually ask — "what shipped for this piece of work?"
    """
    docs_cfg = cfg.get("docs") or {}
    rel_dir = REPO_ROOT / docs_cfg.get("releases_dir", "docs/releases")
    project = cfg["jira"]["project_key"]
    jira_url = cfg["jira"]["project_url"]
    repo_url = cfg["repo"]["web_url"]
    site_base = f"https://{cfg['site']}"
    trailer = docs_cfg.get("decision_trailer", "Decision:")

    rel_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    newest_first = list(reversed(all_commits))

    # Clear previously generated files so a removed commit doesn't leave a
    # stale note behind. Only touch what we generate.
    for old in rel_dir.glob("*.md"):
        old.unlink()

    def commit_line(c: dict) -> str:
        return (
            f"- [`{c['short']}`]({repo_url}/commit/{c['sha']}) "
            f"{c['subject']} — {', '.join(c['areas']) or 'unclassified'}"
        )

    # ---- group commits by ticket -----------------------------------------
    by_ticket: dict[str, list[dict]] = {}
    unplanned: list[dict] = []
    for c in newest_first:
        refs = referenced_keys(c, project)
        if refs:
            for r in refs:
                by_ticket.setdefault(r, []).append(c)
        else:
            unplanned.append(c)

    div_by_sha = {d["sha"]: d for d in divergence}

    # ---- one note per ticket ---------------------------------------------
    for key, commits in sorted(by_ticket.items(), key=lambda kv: kv[0]):
        lines = [
            f"# {key}",
            "",
            f"[{key}]({site_base}/browse/{key}) · "
            f"{len(commits)} commit{'' if len(commits) == 1 else 's'}",
            "",
            "> Generated from git history. Do not edit — regenerated on every sync.",
            "",
            "## What shipped",
            "",
        ]
        lines += [commit_line(c) for c in commits]

        decisions = [
            (c, d) for c in commits for d in decisions_in(c, trailer)
        ]
        if decisions:
            lines += ["", "## Decisions recorded", ""]
            lines += [
                f"- **{d}**  \n  from [`{c['short']}`]({repo_url}/commit/{c['sha']})"
                for c, d in decisions
            ]

        drifted = [c for c in commits if c["sha"] in div_by_sha]
        if drifted:
            lines += ["", "## Scope notes", ""]
            lines += [
                f"- [`{c['short']}`]({repo_url}/commit/{c['sha']}) also touched "
                f"{', '.join(div_by_sha[c['sha']]['areas'])}, outside this ticket"
                for c in drifted
            ]

        lines += ["", "## Files touched", ""]
        touched = sorted({f for c in commits for f in c["files"]})
        lines += [f"- `{f}`" for f in touched[:50]]
        if len(touched) > 50:
            lines.append(f"- … and {len(touched) - 50} more")
        lines += ["", f"_Last synced {synced_at}._", ""]

        path = rel_dir / f"{key}.md"
        path.write_text("\n".join(lines))
        written.append(path)

    # ---- unplanned work gets its own note --------------------------------
    if unplanned:
        lines = [
            "# Unplanned work",
            "",
            "> Generated. Commits that referenced no ticket.",
            "",
            "These landed without a plan entry. That is not automatically wrong —",
            "housekeeping and follow-ups often have no ticket — but it is worth",
            "knowing what shipped outside the plan.",
            "",
        ]
        lines += [commit_line(c) for c in unplanned]
        lines += ["", f"_Last synced {synced_at}._", ""]
        path = rel_dir / "UNPLANNED.md"
        path.write_text("\n".join(lines))
        written.append(path)

    # ---- index ------------------------------------------------------------
    index = [
        "# Release notes",
        "",
        "> Generated from git history on every commit. Do not edit.",
        "",
        f"{len(all_commits)} tracked commit{'' if len(all_commits) == 1 else 's'} · "
        f"{len(by_ticket)} ticket{'' if len(by_ticket) == 1 else 's'} · "
        f"last synced {synced_at}",
        "",
        "| Ticket | Commits | Notes |",
        "|---|---|---|",
    ]
    for key, commits in sorted(by_ticket.items(), key=lambda kv: kv[0]):
        index.append(f"| [{key}]({site_base}/browse/{key}) | {len(commits)} | [{key}.md]({key}.md) |")
    if unplanned:
        index.append(f"| _unplanned_ | {len(unplanned)} | [UNPLANNED.md](UNPLANNED.md) |")

    all_decisions = [
        (c, d) for c in newest_first for d in decisions_in(c, trailer)
    ]
    if all_decisions:
        index += ["", "## Decisions", ""]
        index += [
            f"- **{d}** — [`{c['short']}`]({repo_url}/commit/{c['sha']})"
            for c, d in all_decisions
        ]

    index += [
        "",
        "## Full history",
        "",
    ]
    index += [commit_line(c) for c in newest_first]
    index.append("")

    idx_path = rel_dir / "README.md"
    idx_path.write_text("\n".join(index))
    written.append(idx_path)

    # ---- html index ------------------------------------------------------
    # The markdown files are git-ignored, so GitHub never renders them — the
    # published site is their only home, and a browser shows raw .md as plain
    # text. This is the readable entry point, and it also gives /releases/ a
    # directory index (Pages does not treat README.md as one).
    def esc(s: str) -> str:
        return escape(str(s), quote=True)

    def rows_for(commits: list[dict]) -> str:
        return "".join(
            f"<tr>"
            f"<td><a href='{esc(repo_url)}/commit/{esc(c['sha'])}'><code>{esc(c['short'])}</code></a></td>"
            f"<td>{esc(c['subject'])}</td>"
            f"<td>{esc(', '.join(c['areas']) or '—')}</td>"
            f"<td>{esc(c['date'][:10])}</td>"
            f"</tr>"
            for c in commits
        )

    ticket_sections = "".join(
        f"<h3 id='{esc(key)}'>"
        f"<a href='{esc(site_base)}/browse/{esc(key)}'>{esc(key)}</a></h3>"
        f"<p>{len(commits)} commit{'' if len(commits) == 1 else 's'} · "
        f"<a href='{esc(key)}.md'>raw notes</a></p>"
        f"<table><thead><tr><th>Commit</th><th>Change</th><th>Area</th><th>Date</th></tr></thead>"
        f"<tbody>{rows_for(commits)}</tbody></table>"
        for key, commits in sorted(by_ticket.items(), key=lambda kv: kv[0])
    )

    if unplanned:
        ticket_sections += (
            "<h3 id='unplanned'>Unplanned</h3>"
            "<p>Commits that referenced no ticket · "
            "<a href='UNPLANNED.md'>raw notes</a></p>"
            "<table><thead><tr><th>Commit</th><th>Change</th><th>Area</th><th>Date</th></tr></thead>"
            f"<tbody>{rows_for(unplanned)}</tbody></table>"
        )

    decision_items = "".join(
        f"<li>{esc(d)} — "
        f"<a href='{esc(repo_url)}/commit/{esc(c['sha'])}'><code>{esc(c['short'])}</code></a></li>"
        for c, d in all_decisions
    )
    decisions_html = (
        f"<h2>Decisions</h2><ul>{decision_items}</ul>" if decision_items else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Release notes — {esc(cfg['repo']['slug'])}</title>
<meta name="robots" content="noindex">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 60rem; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.55; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0 1.75rem; font-size: 0.92rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #ddd; vertical-align: top; }}
  th {{ font-weight: 600; border-bottom: 2px solid #999; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }}
  .note {{ background: #f6f6f4; border-left: 3px solid #999; padding: 0.6rem 0.9rem; margin: 1.25rem 0; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #111; color: #eee; }}
    a {{ color: #7ab8ff; }}
    th, td {{ border-color: #333; }}
    .note {{ background: #1a1a1a; border-left-color: #555; }}
  }}
</style>
</head>
<body>
<h1>Release notes</h1>
<p><a href="{esc(repo_url)}">{esc(cfg['repo']['slug'])}</a> ·
   <a href="{esc(jira_url)}">{esc(project)}</a> ·
   <a href="{esc(cfg['confluence']['space_url'])}">Confluence</a> ·
   <a href="../">back to the site</a></p>

<div class="note">
  <p><strong>Generated.</strong> Rebuilt from <code>git log</code> on every commit
  and again at deploy time — never hand-written. One section per ticket, because
  that answers the question people actually ask: what shipped for this piece of
  work?</p>
</div>

<p>{len(all_commits)} tracked commit{'' if len(all_commits) == 1 else 's'} ·
   {len(by_ticket)} ticket{'' if len(by_ticket) == 1 else 's'} ·
   last synced {esc(synced_at)}</p>

{decisions_html}

<h2>By ticket</h2>
{ticket_sections or "<p>Nothing tracked yet.</p>"}

<h2>Full history</h2>
<table><thead><tr><th>Commit</th><th>Change</th><th>Area</th><th>Date</th></tr></thead>
<tbody>{rows_for(newest_first)}</tbody></table>
</body>
</html>
"""
    html_path = rel_dir / "index.html"
    html_path.write_text(html)
    written.append(html_path)

    return written


def write_build_info(
    cfg: dict, all_commits: list[dict], jira_map: dict[str, dict], synced_at: str
) -> Path:
    site_dir = REPO_ROOT / cfg["repo"]["site_dir"]
    site_dir.mkdir(parents=True, exist_ok=True)
    out = site_dir / "build-info.json"

    newest_first = list(reversed(all_commits))
    head = newest_first[0] if newest_first else None

    payload = {
        "generated_by": "scripts/atlassian_sync.py",
        "synced_at": synced_at,
        "commit_count": len(all_commits),
        "sha": head["sha"] if head else None,
        "commit_url": f"{cfg['repo']['web_url']}/commit/{head['sha']}" if head else None,
        "jira_project": cfg["jira"]["project_key"],
        "jira_project_url": cfg["jira"]["project_url"],
        "confluence_space": cfg["confluence"]["space_key"],
        "confluence_url": cfg["confluence"]["space_url"],
        "recent": [
            {
                "sha": c["sha"],
                "subject": c["subject"],
                "areas": c["areas"],
                "author": c["author"],
                "date": c["date"],
                "issue_key": jira_map.get(c["sha"], {}).get("key"),
                "issue_url": jira_map.get(c["sha"], {}).get("url"),
            }
            for c in newest_first[:RECENT_ON_SITE]
        ],
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def resolve_range(args: argparse.Namespace) -> str:
    if args.all:
        return "HEAD"
    if args.range:
        return args.range
    # Hook mode: just the commit that was made. Handles the root commit too.
    has_parent = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD~1"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).returncode == 0
    return "HEAD~1..HEAD" if has_parent else "HEAD"


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync git commits into Jira and Confluence.")
    ap.add_argument("--range", help="git rev range, e.g. abc123..def456")
    ap.add_argument("--all", action="store_true", help="sync the whole branch history")
    ap.add_argument("--dry-run", action="store_true", help="print actions, change nothing")
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify credentials and access, then exit without syncing",
    )
    ap.add_argument("--skip-jira", action="store_true")
    ap.add_argument("--skip-confluence", action="store_true")
    ap.add_argument(
        "--start",
        metavar="KEY",
        help="mark a ticket In Progress and comment that work began, then exit",
    )
    ap.add_argument(
        "--docs-only",
        action="store_true",
        help="regenerate docs/releases and build-info from git alone — no credentials, no network",
    )
    args = ap.parse_args()

    if not CONFIG_PATH.exists():
        raise Fail(f"missing config: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text())

    if load_env_file():
        log("loaded credentials from .atlassian.env")

    site = os.environ.get("ATLASSIAN_SITE") or cfg["site"]
    email = os.environ.get("ATLASSIAN_EMAIL", "").strip()
    token = os.environ.get("ATLASSIAN_API_TOKEN", "").strip()

    if args.check and args.dry_run:
        raise Fail("--check needs real credentials, so it cannot be combined with --dry-run")

    # --- docs only: pure git, no credentials, no network ------------------
    if args.docs_only:
        synced = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        excluded = cfg.get("exclude_subject_prefixes", [])
        gen_paths = cfg.get("exclude_path_prefixes", [])
        commits = collect_commits(
            "HEAD", cfg["areas"], excluded, gen_paths, cfg.get("exclude_shas")
        )

        # Ticket keys come straight from the commit messages, so the release
        # notes and the site's Delivery panel are complete without an API call.
        project = cfg["jira"]["project_key"]
        jira_map = {
            c["sha"]: {
                "key": referenced_keys(c, project)[0],
                "url": f"https://{site}/browse/{referenced_keys(c, project)[0]}",
                "action": "referenced",
            }
            for c in commits
            if referenced_keys(c, project)
        }

        step("Release notes (docs-only)")
        notes = write_release_notes(cfg, commits, [], synced)
        log(f"wrote {len(notes)} file(s)")
        info = write_build_info(cfg, commits, jira_map, synced)
        log(f"wrote {info.relative_to(REPO_ROOT)}")
        print("\n✓ docs regenerated", flush=True)
        return 0

    if not args.dry_run and not (email and token):
        raise Fail(
            "ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN must be set.\n"
            "  Local:  export them in your shell (see docs/SETUP.md)\n"
            "  CI:     set them as repository secrets\n"
            "Run with --dry-run to test without credentials."
        )

    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    api = Atlassian(site, email or "dry@run", token or "dry", dry_run=args.dry_run)

    if not args.dry_run:
        step("Preflight")
        preflight(api, cfg)

    if args.check:
        print("\n✓ credentials and access look good", flush=True)
        return 0

    # --- start work on a ticket -------------------------------------------
    if args.start:
        key = args.start.strip().upper()
        step(f"Starting {key}")
        in_progress = (cfg["jira"].get("progress_states") or ["In Progress"])[0]
        moved = api.advance_issue(key, in_progress, [])
        log(f"status: {' → '.join(moved) if moved else f'already {in_progress}'}")
        api.comment(
            key,
            adf_doc(
                adf_para(
                    adf_text(
                        "Work started. Changes will land in "
                    ),
                    adf_link(cfg["repo"]["slug"], cfg["repo"]["web_url"]),
                    adf_text(
                        f"; reference {key} in the commit message and this ticket "
                        f"moves to {cfg['jira'].get('done_status', 'Done')} automatically."
                    ),
                )
            ),
        )
        print("\n✓ ticket started", flush=True)
        return 0

    rev_range = resolve_range(args)
    step(f"Reading git history ({rev_range})")
    excluded = cfg.get("exclude_subject_prefixes", [])
    gen_paths = cfg.get("exclude_path_prefixes", [])
    dropped_shas = cfg.get("exclude_shas")
    new_commits = collect_commits(rev_range, cfg["areas"], excluded, gen_paths, dropped_shas)
    all_commits = collect_commits("HEAD", cfg["areas"], excluded, gen_paths, dropped_shas)
    log(f"{len(new_commits)} commit(s) in range · {len(all_commits)} in full history")

    if not new_commits:
        log("nothing new to sync")

    # --- Jira -------------------------------------------------------------
    jira_map: dict[str, dict] = {}
    divergence: list[dict] = []
    if args.skip_jira:
        step("Jira — skipped")
    elif new_commits:
        step(f"Jira — {cfg['jira']['project_key']} ({cfg['jira'].get('commit_mode', 'update')} mode)")
        parent = ensure_workstream(api, cfg)
        jira_map, divergence = sync_jira(api, cfg, new_commits, parent)
    else:
        step("Jira — no new commits")

    # --- Confluence -------------------------------------------------------
    if args.skip_confluence:
        step("Confluence — skipped")
    else:
        conf = cfg["confluence"]
        step(f"Confluence — {conf['space_key']}")
        space_id = "" if args.dry_run else (
            conf.get("space_id") or api.space_id(conf["space_key"])
        )
        parent_page = conf.get("homepage_id")

        gaps = [] if args.skip_jira else evidence_gaps(api, cfg, all_commits)
        if gaps:
            log(
                "evidence gap: "
                + ", ".join(g["key"] for g in gaps)
                + " marked Done with no commit referencing them"
            )

        # Stamp the spec pages first — the Release Log reports what this finds.
        stale = sync_spec_pages(api, cfg, all_commits, synced_at)

        rel = api.upsert_page(
            space_id,
            conf["release_log_title"],
            storage_release_log(all_commits, cfg, synced_at, divergence, gaps, stale),
            parent_page,
        )
        log(f"{conf['release_log_title']}: {'created' if rel.get('created') else 'updated'}")

        chg = api.upsert_page(
            space_id,
            conf["changelog_title"],
            storage_changelog(all_commits, cfg, synced_at),
            parent_page,
        )
        log(f"{conf['changelog_title']}: {'created' if chg.get('created') else 'updated'}")

        dec = api.upsert_page(
            space_id,
            conf.get("decision_log_title", "Decision Log"),
            storage_decision_log(all_commits, cfg, synced_at),
            parent_page,
        )
        log(f"{conf.get('decision_log_title', 'Decision Log')}: "
            f"{'created' if dec.get('created') else 'updated'}")

        # Comment on the spec pages whose scope reality left behind. A page body
        # gets rewritten every run; a comment persists, so this is the part that
        # accumulates into an audit trail the plan's owner will actually see.
        if divergence and conf.get("comment_on_specs", True) and not api.dry_run:
            spec_map = conf.get("spec_pages") or {}
            index = api.issue_index(
                cfg["jira"]["project_key"],
                [r for d in divergence for r in d.get("refs", [])],
            )
            targets: dict[str, list[dict]] = {}
            for d in divergence:
                for ref in d.get("refs", []):
                    for label in index.get(ref, {}).get("labels", []):
                        page = spec_map.get(label)
                        if page:
                            targets.setdefault(page, []).append(d)
                            break
            for page_id, items in targets.items():
                api.footer_comment(
                    page_id,
                    storage_divergence_comment(items, cfg, synced_at),
                )
                log(f"commented divergence on spec page {page_id}")

    # --- auto-docs --------------------------------------------------------
    step("Release notes")
    notes = write_release_notes(cfg, all_commits, divergence, synced_at)
    rel_dir = (cfg.get("docs") or {}).get("releases_dir", "docs/releases")
    log(f"wrote {len(notes)} file(s) under {rel_dir}/")

    # --- website state ----------------------------------------------------
    step("Website")
    if not args.skip_jira:
        backfill_issue_keys(api, cfg, all_commits[-RECENT_ON_SITE:], jira_map)
    info = write_build_info(cfg, all_commits, jira_map, synced_at)
    log(f"wrote {info.relative_to(REPO_ROOT)}")

    print("\n✓ sync complete", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as err:
        print(f"\n✗ {err}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
