/* sidc.ai — progressive enhancement only. The page works without this file. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ---------- footer year ---------- */
  const year = $("#year");
  if (year) year.textContent = String(new Date().getFullYear());

  /* ---------- sticky nav shadow ---------- */
  const nav = $("#nav");
  if (nav) {
    const onScroll = () => nav.setAttribute("data-stuck", String(window.scrollY > 8));
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* ---------- reveal on scroll ---------- */
  const targets = $$("[data-reveal]");
  if (targets.length) {
    if (!("IntersectionObserver" in window)) {
      targets.forEach((el) => el.classList.add("is-in"));
    } else {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              e.target.classList.add("is-in");
              io.unobserve(e.target);
            }
          });
        },
        { rootMargin: "0px 0px -8% 0px", threshold: 0.06 }
      );
      targets.forEach((el) => io.observe(el));
    }
  }

  /* ---------- active section in nav ---------- */
  const links = $$('.nav__links a[href^="#"]');
  const sections = links
    .map((a) => document.getElementById(a.getAttribute("href").slice(1)))
    .filter(Boolean);

  if (sections.length && "IntersectionObserver" in window) {
    const spy = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          links.forEach((a) => a.removeAttribute("aria-current"));
          const match = links.find((a) => a.getAttribute("href") === `#${e.target.id}`);
          if (match) match.setAttribute("aria-current", "true");
        });
      },
      { rootMargin: "-45% 0px -50% 0px" }
    );
    sections.forEach((s) => spy.observe(s));
  }

  /* ============================================================
     Delivery panel — read build-info.json written by the sync.
     Absent file is the normal state before the first sync, so it
     degrades quietly rather than shouting an error.
     ============================================================ */
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));

  const fmt = (iso) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  };

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  const setHTML = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = value;
  };

  fetch("build-info.json", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then((bi) => {
      const bar = $("#build-bar");
      if (bar) bar.setAttribute("data-state", "ok");
      const n = bi.commit_count;
      setText(
        "build-status",
        typeof n === "number"
          ? `synced — ${n} commit${n === 1 ? "" : "s"} tracked`
          : "synced"
      );

      const sha = String(bi.sha || "");
      setHTML(
        "bi-sha",
        sha
          ? `<a href="${esc(bi.commit_url || "#")}" rel="noopener"><code>${esc(sha.slice(0, 7))}</code></a>`
          : "—"
      );
      setText("bi-time", bi.synced_at ? fmt(bi.synced_at) : "—");

      setHTML(
        "bi-jira",
        bi.jira_project_url
          ? `<a href="${esc(bi.jira_project_url)}" rel="noopener">${esc(bi.jira_project || "SIDC")}</a>`
          : "—"
      );
      setHTML(
        "bi-conf",
        bi.confluence_url
          ? `<a href="${esc(bi.confluence_url)}" rel="noopener">${esc(bi.confluence_space || "SIDC")}</a>`
          : "—"
      );

      const rows = Array.isArray(bi.recent) ? bi.recent : [];
      if (rows.length) {
        setHTML(
          "bi-log",
          rows
            .map((c) => {
              const jira = c.issue_key
                ? `<a href="${esc(c.issue_url || "#")}" rel="noopener">${esc(c.issue_key)}</a>`
                : "—";
              return `<tr>
                <td><code>${esc(String(c.sha || "").slice(0, 7))}</code></td>
                <td>${esc(c.subject || "")}</td>
                <td>${esc((c.areas || []).join(", ") || "—")}</td>
                <td>${jira}</td>
              </tr>`;
            })
            .join("")
        );
      }
    })
    .catch(() => {
      setText("build-status", "build-info.json — not generated yet");
    });
})();

/* rehearsal */
