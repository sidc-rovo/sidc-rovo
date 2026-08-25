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

FIELD_SEP = "\x1f"
REC_SEP = "\x1e"


class Fail(RuntimeError):
    """Something went wrong that the user needs to read."""


def log(msg: str) -> None:
    print(f"    {msg}", flush=True)


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


def classify(paths: list[str], area_rules: list[dict[str, str]]) -> list[str]:
    """Map changed paths to human-readable areas. First matching prefix wins."""
    found: list[str] = []
    for path in paths:
        for rule in area_rules:
            if path.startswith(rule["prefix"]):
                if rule["area"] not in found:
                    found.append(rule["area"])
                break
    return found


def collect_commits(rev_range: str, area_rules: list[dict[str, str]]) -> list[dict[str, Any]]:
    fmt = FIELD_SEP.join(["%H", "%h", "%s", "%b", "%an", "%ae", "%aI"]) + REC_SEP
    raw = git("log", f"--pretty=format:{fmt}", "--no-merges", rev_range)

    commits: list[dict[str, Any]] = []
    for chunk in raw.split(REC_SEP):
        if not chunk.strip():
            continue
        parts = chunk.strip("\n").split(FIELD_SEP)
        if len(parts) < 7:
            continue
        sha, short, subject, body, author, email, date = parts[:7]

        files = [
            f for f in git("show", "--name-only", "--pretty=format:", sha).splitlines() if f
        ]
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
                "areas": classify(files, area_rules),
            }
        )

    commits.reverse()  # oldest first, so Jira issue order matches history
    return commits


def referenced_keys(commit: dict[str, Any], project_key: str) -> list[str]:
    """Explicit SIDC-123 references in the commit message."""
    text = f"{commit['subject']} {commit['body']}"
    return sorted(set(re.findall(rf"\b{re.escape(project_key)}-\d+\b", text)))


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

def storage_release_log(commits: list[dict], cfg: dict, synced_at: str) -> str:
    repo_url = cfg["repo"]["web_url"]
    jira_url = cfg["jira"]["project_url"]
    newest_first = list(reversed(commits))

    by_area: dict[str, int] = {}
    for c in commits:
        for a in c["areas"] or ["Unclassified"]:
            by_area[a] = by_area.get(a, 0) + 1

    rows = "".join(
        f"<tr>"
        f"<td><a href='{escape(repo_url)}/commit/{escape(c['sha'])}'>"
        f"<code>{escape(c['short'])}</code></a></td>"
        f"<td>{escape(c['subject'])}</td>"
        f"<td>{escape(', '.join(c['areas']) or '—')}</td>"
        f"<td>{escape(c['author'])}</td>"
        f"<td>{escape(c['date'][:10])}</td>"
        f"</tr>"
        for c in newest_first
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

<h2>Release history</h2>
<table>
  <thead>
    <tr><th>Commit</th><th>Change</th><th>Area</th><th>Author</th><th>Date</th></tr>
  </thead>
  <tbody>{rows or "<tr><td colspan='5'>No commits yet.</td></tr>"}</tbody>
</table>
""".strip()


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


def sync_jira(api: Atlassian, cfg: dict, commits: list[dict], parent: str | None) -> dict[str, dict]:
    """Returns {sha: {"key":..., "url":..., "action":...}}"""
    jira = cfg["jira"]
    key = jira["project_key"]
    repo_url = cfg["repo"]["web_url"]
    results: dict[str, dict] = {}

    for c in commits:
        sha_label = f"sha-{c['short']}"

        # 1. Explicit reference in the message wins — comment, don't duplicate.
        refs = referenced_keys(c, key)
        if refs:
            for ref in refs:
                api.comment(
                    ref,
                    adf_doc(
                        adf_para(
                            adf_text("Commit "),
                            adf_link(c["short"], f"{repo_url}/commit/{c['sha']}"),
                            adf_text(f" — {c['subject']}"),
                        ),
                        adf_para(
                            adf_text(
                                f"Areas: {', '.join(c['areas']) or 'unclassified'} · "
                                f"{len(c['files'])} file(s) · {c['author']}"
                            )
                        ),
                    ),
                )
                log(f"{c['short']} -> commented on {ref}")
            results[c["sha"]] = {
                "key": refs[0],
                "url": f"https://{api.site}/browse/{refs[0]}",
                "action": "commented",
            }
            continue

        # 2. Already filed? Label lookup is the dedupe key.
        existing = api.jql(f'project = {key} AND labels = "{sha_label}"')
        if existing:
            found = existing[0]["key"]
            log(f"{c['short']} -> already tracked by {found}")
            results[c["sha"]] = {
                "key": found,
                "url": f"https://{api.site}/browse/{found}",
                "action": "existing",
            }
            continue

        # 3. File a new Task.
        if api.dry_run:
            log(f"[dry-run] {c['short']} -> would create Task: {c['subject']}")
            results[c["sha"]] = {"key": None, "url": None, "action": "dry-run"}
            continue

        area_labels = [
            re.sub(r"[^A-Za-z0-9]+", "-", a).strip("-").lower() for a in c["areas"]
        ]
        fields = {
            "project": {"key": key},
            "summary": c["subject"][:250] or f"Commit {c['short']}",
            "issuetype": {"name": jira["task_issue_type"]},
            "labels": list(dict.fromkeys([*jira["labels"], sha_label, *area_labels])),
            "description": commit_description(c, repo_url),
        }
        if parent:
            fields["parent"] = {"key": parent}

        try:
            res = api.create_issue(fields)
        except Fail as exc:
            # Parenting is the most likely thing to be rejected; retry flat
            # rather than losing the issue entirely.
            if parent and "parent" in str(exc).lower():
                log(f"{c['short']} -> parent rejected, filing without it")
                fields.pop("parent", None)
                res = api.create_issue(fields)
            else:
                raise

        new_key = res.get("key")
        log(f"{c['short']} -> created {new_key}")
        results[c["sha"]] = {
            "key": new_key,
            "url": f"https://{api.site}/browse/{new_key}",
            "action": "created",
        }

    return results


# ----------------------------------------------------------------------------
# build-info.json — what the website reads
# ----------------------------------------------------------------------------

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
    args = ap.parse_args()

    if not CONFIG_PATH.exists():
        raise Fail(f"missing config: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text())

    site = os.environ.get("ATLASSIAN_SITE") or cfg["site"]
    email = os.environ.get("ATLASSIAN_EMAIL", "").strip()
    token = os.environ.get("ATLASSIAN_API_TOKEN", "").strip()

    if args.check and args.dry_run:
        raise Fail("--check needs real credentials, so it cannot be combined with --dry-run")

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

    rev_range = resolve_range(args)
    step(f"Reading git history ({rev_range})")
    new_commits = collect_commits(rev_range, cfg["areas"])
    all_commits = collect_commits("HEAD", cfg["areas"])
    log(f"{len(new_commits)} commit(s) in range · {len(all_commits)} in full history")

    if not new_commits:
        log("nothing new to sync")

    # --- Jira -------------------------------------------------------------
    jira_map: dict[str, dict] = {}
    if args.skip_jira:
        step("Jira — skipped")
    elif new_commits:
        step(f"Jira — {cfg['jira']['project_key']}")
        parent = ensure_workstream(api, cfg)
        jira_map = sync_jira(api, cfg, new_commits, parent)
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

        rel = api.upsert_page(
            space_id,
            conf["release_log_title"],
            storage_release_log(all_commits, cfg, synced_at),
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

    # --- website state ----------------------------------------------------
    step("Website")
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
