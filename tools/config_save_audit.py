#!/usr/bin/env python3
"""Prove that saving each configuration form UNCHANGED changes nothing (GAPS §51).

For every save form in the curated list, in order: submit it as the lab would,
without touching a field; snapshot every configuration store
(tools/config_snapshot.py, run inside the instance); diff against the snapshot
taken before that form. Each difference is attributed to exactly one form and
classified:

  equivalent        None vs missing
  representational  missing vs {} / [] (shape only)
  DEFECT            anything else -- a value the save changed

Run on the host against the running stack, AFTER a repozo backup:
    python3 tools/config_save_audit.py OUT_DIR [--only=name,name]
Writes OUT_DIR/audit.json and prints a table. It does not restore anything:
restore from the "before" snapshots it leaves, or from the backup.
"""
from __future__ import print_function

import json
import os
import re
import subprocess
import sys

BASE = os.environ.get("PFAS_BASE", "http://localhost:8080/senaite/")
CONTAINER = os.environ.get("PFAS_CONTAINER", "senaite_pfas-senaite-1")

# (name, url, how) -- how: ("button", text) submits the form owning that button;
# ("js", code) runs code that triggers the save (AJAX sections, edit modals).
STEPS = [
    ("method profile EPA 537.1", "@@pfas-method-profile-edit?method_id=EPA_537_1", ("button", "Save & Export")),
    ("method profile EPA 1633A", "@@pfas-method-profile-edit?method_id=EPA_1633A", ("button", "Save & Export")),
    ("method profile FDA 32-PFAS", "@@pfas-method-profile-edit?method_id=FDA_32PFAS", ("button", "Save & Export")),
    # @@pfas-qc-rules redirects to Method Profiles: the rule toggles are a tab
    # of the profile editor, whose saves write qc_rules.json (covered above).
    ("QC type grid", "@@pfas-qc-type-grid", ("button", "Save Grid")),
    ("EDD config: lab", "@@pfas-egad-config", ("js", "saveSection('lab')")),
    ("EDD config: methods", "@@pfas-egad-config", ("js", "saveSection('methods')")),
    ("EDD config: CAS", "@@pfas-egad-config", ("js", "saveSection('cas')")),
    ("EDD config: profile", "@@pfas-egad-config#profiles", ("button", "Save profile")),
    ("print settings", "@@pfas-print-settings", ("button", "Save Print Settings")),
    ("print settings: qualifiers", "@@pfas-print-settings", ("button", "Save QC Qualifiers")),
    ("facility defaults", "@@pfas-facility-units", ("button", "Save Facility Defaults")),
    ("facility API key", "@@pfas-facility-units", ("form_action", "save_api_key")),
    ("reagent expiry defaults", "@@pfas-reagents", ("button", "Save Defaults")),
    ("logbook admin: sequence 1", "@@pfas-logbook-admin", ("nth_action", "save_method_config", 0)),
    ("logbook admin: sequence 2", "@@pfas-logbook-admin", ("nth_action", "save_method_config", 1)),
    ("logbook admin: sequence 3", "@@pfas-logbook-admin", ("nth_action", "save_method_config", 2)),
    ("prep logbook definition (edit)", "@@pfas-prep-logbooks",
     ("click_then_click", "[data-edit-uid]:visible", "#lbModal button[type=submit]:visible")),
    ("reference definition method", "@@pfas-setup-references", ("button", "Save")),
    ("run template", "@@pfas-run-builder?batch_id=B-002", ("button", "Save run template")),
    ("regulatory limits", "@@pfas-regulatory-limits", ("button", "Save limits")),
]


def password():
    out = subprocess.run(["docker", "exec", CONTAINER, "cat", "adminPassword.txt"],
                         capture_output=True, text=True).stdout
    m = re.search(r"password:\s*(\S+)", out, re.I)
    return m.group(1) if m else "admin"


def snapshot(path):
    inner = "/tmp/" + os.path.basename(path)
    subprocess.run(["docker", "exec", CONTAINER, "bin/instance", "run",
                    "/addon/tools/config_snapshot.py", inner],
                   capture_output=True, text=True, check=True)
    subprocess.run(["docker", "cp", "%s:%s" % (CONTAINER, inner), path], check=True)
    with open(path) as fh:
        return json.load(fh)


_MISSING = object()


def diff(a, b, path=""):
    """[(path, kind, before, after)] for every difference."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k, _MISSING), b.get(k, _MISSING), path + "/" + k)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, "%s[%d]" % (path, i))
        return out
    if a == b:
        return out
    pair = (a, b)
    if _MISSING in pair and None in pair:
        kind = "equivalent"
    elif _MISSING in pair and ({} in pair or [] in pair):
        kind = "representational"
    else:
        kind = "DEFECT"
    show = lambda v: "<missing>" if v is _MISSING else v          # noqa: E731
    out.append((path, kind, show(a), show(b)))
    return out


def run_step(page, url, how):
    page.goto(BASE + url, timeout=90000)
    page.wait_for_load_state("networkidle", timeout=60000)
    kind = how[0]
    if kind == "button":
        btn = page.locator("button[type=submit], button:not([type])", has_text=how[1]).first
        form_submit(page, btn)
    elif kind == "css":
        form_submit(page, page.locator(how[1]).first)
    elif kind == "form_action":
        form_submit(page, page.locator("form:has(input[name=action][value=%s]) button[type=submit]" % how[1]).first)
    elif kind == "nth_action":
        form_submit(page, page.locator("form:has(input[name=action][value=%s]) button[type=submit]" % how[1]).nth(how[2]))
    elif kind == "js":
        with page.expect_response(lambda r: r.request.method == "POST", timeout=60000):
            page.evaluate(how[1])
        page.wait_for_timeout(800)
    elif kind == "click":
        # a real click, so the page's own onclick handlers run (QC Rules
        # serialises its table in prepareSubmit()).
        with page.expect_navigation(timeout=90000):
            page.locator(how[1]).first.click()
        page.wait_for_load_state("networkidle", timeout=60000)
    elif kind == "click_then_click":
        page.locator(how[1]).first.click()
        page.wait_for_timeout(600)
        with page.expect_navigation(timeout=90000):
            page.locator(how[2]).first.click()
        page.wait_for_load_state("networkidle", timeout=60000)
    elif kind == "js_then_button":
        page.evaluate(how[1])
        page.wait_for_timeout(500)
        form_submit(page, page.locator("button[type=submit]:visible", has_text=how[2]).first)


def form_submit(page, button):
    """Submit the button's form even when it sits in a hidden tab/pane."""
    with page.expect_navigation(timeout=90000):
        button.evaluate("b => (b.form || b.closest('form')).requestSubmit(b.form ? b : undefined)")
    page.wait_for_load_state("networkidle", timeout=60000)


def main(out_dir, only=None):
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    results = []
    before = snapshot(os.path.join(out_dir, "snap_00_before.json"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        page.goto(BASE + "login")
        page.fill("input[name=__ac_name]", "admin")
        page.fill("input[name=__ac_password]", password())
        page.click("button[type=submit], input[type=submit]")
        page.wait_for_load_state("networkidle")
        for i, (name, url, how) in enumerate(STEPS, 1):
            if only and not any(o.lower() in name.lower() for o in only):
                continue
            del errors[:]
            status = "ok"
            try:
                run_step(page, url, how)
            except Exception as exc:                                  # noqa: BLE001
                status = "NOT RUN: %s" % str(exc).splitlines()[0][:120]
            after = snapshot(os.path.join(out_dir, "snap_%02d_%s.json" % (
                i, re.sub(r"[^a-z0-9]+", "_", name.lower()))))
            h_after = after.pop("history_entries", 0) or 0
            new_history = h_after - (before.pop("history_entries", 0) or 0)
            changes = diff(before, after)
            after["history_entries"] = h_after
            defects = [c for c in changes if c[1] == "DEFECT"]
            results.append({"step": name, "status": status, "js_errors": list(errors),
                            "new_history_entries": new_history,
                            "changes": [list(map(lambda v: v if isinstance(v, (str, int, float, bool, type(None))) else json.dumps(v)[:300], c)) for c in changes]})
            print("%-34s %-8s changes=%-3d defects=%-3d history+%d %s" % (
                name, status[:8], len(changes), len(defects), new_history, errors[:1] or ""))
            for c in defects[:6]:
                print("      DEFECT %s: %s -> %s" % (c[0], json.dumps(c[2])[:90], json.dumps(c[3])[:90]))
            before = after
        browser.close()
    with open(os.path.join(out_dir, "audit.json"), "w") as fh:
        json.dump(results, fh, indent=1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    only = [a[len("--only="):] for a in sys.argv[2:] if a.startswith("--only=")]
    main(sys.argv[1], [o for x in only for o in x.split(",")] or None)
