#!/usr/bin/env python3
"""Screenshot and measure every PFAS page, for before/after UI comparisons.

GAPS §49. Logs in as admin, walks every link in the rendered sidebar plus the
pages the sidebar does not reach (role landings, editors, one level of deep
links), and for each page records a 1440x900 screenshot and the geometry that
should be identical everywhere:

  sidebar_top / sidebar_row  -- where the sidebar starts and its row pitch
  left / right / width       -- the real content edges inside the frame
  buttons                    -- distinct (height|font-size|radius|bg) styles
                                inside the content area only
  scroll_h                   -- height of the content scroller

Run on the host (needs the playwright package + chromium) against the running
stack:

    python3 tools/ui_audit.py OUT_DIR            # screenshots + audit.json
    python3 tools/ui_audit.py OUT_DIR --summary  # also print the frame table

Compare two runs by eye (screenshots share file names) or by diffing the
audit.json frame/sidebar fields. Host-only tooling: Python 3, not add-on code.
"""
from __future__ import print_function

import collections
import json
import os
import re
import subprocess
import sys

BASE = os.environ.get("PFAS_BASE", "http://localhost:8080/senaite")
CONTAINER = os.environ.get("PFAS_CONTAINER", "senaite_pfas-senaite-1")

EXTRA = [
    "@@pfas-home", "@@pfas-qc-management", "@@pfas-bench",
    "@@pfas-data-review-home", "@@pfas-method-profile-edit?method_id=EPA_1633A",
    "@@pfas-method-wizard", "@@pfas-qc-rules", "@@pfas-qc-type-grid",
    "@@pfas-sample-status", "@@pfas-logbook-index",
]
# (page, CSS selector for links to follow from its content area, how many)
DEEP = [
    ("@@pfas-data-review", "a[href*='WS-'], a[href*=worksheet]", 2),
    ("@@pfas-logbook-batches", "a[href*=logbook]", 2),
]

MEASURE = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const main = document.querySelector('.pfas-content-area') || document.querySelector('#portal-column-content');
  const kind = document.querySelector('.pfas-content-area') ? 'pfas' : 'core';
  const out = {kind, title: document.title};
  const si = Array.from(document.querySelectorAll('.pfas-sidebar .pfas-si')).filter(vis);
  out.sidebar_top = si.length ? Math.round(si[0].getBoundingClientRect().top) : null;
  out.sidebar_row = si.length > 1 ? Math.round(si[1].getBoundingClientRect().top - si[0].getBoundingClientRect().top) : null;
  if (!main) return out;
  out.scroll_h = main.scrollHeight;
  let L = 1e9, R = 0;
  main.querySelectorAll('table, h1, h2, h3, p, form, section, fieldset, [class*=card], [class*=panel], [class*=section]').forEach(e => {
    const r = e.getBoundingClientRect(); if (r.width < 150 || r.height < 8 || r.top > 3000) return;
    L = Math.min(L, r.left); R = Math.max(R, r.right); });
  if (L < 1e9) { out.left = Math.round(L); out.right = Math.round(R); out.width = Math.round(R - L); }
  const b = {};
  main.querySelectorAll('button, input[type=submit], input[type=button], a.btn, .btn').forEach(e => {
    if (!vis(e)) return; const s = getComputedStyle(e);
    const k = [Math.round(e.getBoundingClientRect().height), s.fontSize, s.borderRadius, s.backgroundColor].join('|');
    b[k] = (b[k] || 0) + 1; });
  out.buttons = b;
  return out; }"""


def _password():
    try:
        text = subprocess.check_output(
            ["docker", "exec", CONTAINER, "cat", "adminPassword.txt"],
            universal_newlines=True)
    except Exception:
        return os.environ.get("PFAS_ADMIN_PASSWORD", "admin")
    m = re.search(r"password:\s*(\S+)", text, re.I)
    return m.group(1) if m else "admin"


def _slug(url):
    return re.sub(r"[^a-z0-9]+", "-", url[len(BASE):].lower()).strip("-") or "root"


def crawl(out_dir):
    from playwright.sync_api import sync_playwright
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.goto(BASE + "/login")
        page.fill("input[name=__ac_name]", "admin")
        page.fill("input[name=__ac_password]", _password())
        page.click("button[type=submit], input[type=submit]")
        page.wait_for_load_state("networkidle")
        page.goto(BASE + "/senaite-dashboard")
        page.wait_for_load_state("networkidle")
        targets = page.eval_on_selector_all(
            ".pfas-sidebar a[href]",
            "els => els.map(a => { const g = a.closest('.pfas-sg');"
            " const h = g ? g.querySelector('.pfas-sg-label') : null;"
            " return [h ? h.innerText.trim() : '', a.innerText.trim(), a.href]; })")
        targets += [["EXTRA", x, BASE + "/" + x] for x in EXTRA]
        for src, sel, n in DEEP:
            try:
                page.goto(BASE + "/" + src)
                page.wait_for_load_state("networkidle")
                scoped = ", ".join(".pfas-content-area " + s.strip() for s in sel.split(","))
                links = page.eval_on_selector_all(
                    scoped, "els => els.map(a => [a.innerText.trim().slice(0, 40), a.href])")
                links = [l for l in links if l[1].split("#")[0] != BASE + "/" + src][:n]
                targets += [["DEEP", src + " > " + t, h] for t, h in links]
            except Exception as exc:
                print("could not follow", src, exc, file=sys.stderr)
        seen = set()
        for group, label, href in targets:
            url = href.split("#")[0]
            if not url.startswith(BASE) or url in seen or "logout" in url:
                continue
            seen.add(url)
            slug = _slug(url)
            try:
                page.goto(url, timeout=60000)
                page.wait_for_load_state("networkidle", timeout=30000)
                data = page.evaluate(MEASURE)
                page.screenshot(path=os.path.join(out_dir, slug + ".png"))
            except Exception as exc:
                data = {"error": str(exc)[:200]}
            data.update(group=group, label=label, url=url, slug=slug)
            rows.append(data)
            print("{0:22} {1:34} {2}".format(group[:22], label[:34],
                                             data.get("left", data.get("error", "-"))),
                  file=sys.stderr)
        browser.close()
    with open(os.path.join(out_dir, "audit.json"), "w") as fh:
        json.dump(rows, fh, indent=1)
    return rows


def summary(rows):
    frames = collections.defaultdict(list)
    sidebars = collections.Counter()
    buttons = collections.Counter()
    for r in rows:
        if "left" in r:
            frames[(r["kind"], r["left"], r["right"])].append(r["label"][:26])
        sidebars[(r.get("kind"), r.get("sidebar_top"), r.get("sidebar_row"))] += 1
        for k, v in (r.get("buttons") or {}).items():
            buttons[(r.get("kind"), k)] += v
    print("\nContent frames ({0} distinct):".format(len(frames)))
    for (kind, left, right), labels in sorted(frames.items(), key=lambda kv: -len(kv[1])):
        print("  {0:3} {1:4} x={2:<4} w={3:<5} {4}".format(
            len(labels), kind, left, right - left, ", ".join(labels[:5])))
    print("\nSidebar geometry (kind, top, row pitch):")
    for k, v in sidebars.most_common():
        print("  {0:3} {1}".format(v, k))
    pfas_btn = [k for k in buttons if k[0] == "pfas"]
    print("\nButton styles inside PFAS content: {0} distinct".format(len(pfas_btn)))
    for (kind, k), v in buttons.most_common():
        if kind == "pfas":
            print("  {0:4} {1}".format(v, k))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    result = crawl(sys.argv[1])
    print("{0} pages".format(len(result)))
    if "--summary" in sys.argv:
        summary(result)
