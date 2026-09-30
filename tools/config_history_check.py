#!/usr/bin/env python3
"""Prove each change-history hook FIRES: one real edit per writer (GAPS §52).

tools/config_save_audit.py proves an unchanged save records nothing -- but every
hook is wrapped so history can never block a save, which means a broken hook
also records nothing and that audit would still pass. Only a real edit shows a
hook works. For each case this makes one visible change in a real browser,
requires the newest history entry to name the expected store, then puts the
value back (History-page revert where the store supports it, otherwise the
case's own undo), and finally requires the whole configuration to equal the
snapshot taken before it started.

Run on the host against the running stack, after a backup:
    python3 tools/config_history_check.py OUT_DIR
Leaves real history entries behind -- that is what a trail is for.
"""
from __future__ import print_function

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_save_audit as audit          # noqa: E402  (login, snapshot, diff)

B = audit.BASE


def newest(pg, n=6):
    pg.goto(B + "@@pfas-config-history")
    pg.wait_for_load_state("networkidle")
    return pg.locator("table.pfas-table tbody tr").all()[:n]


def find_row(pg, text):
    for row in newest(pg, 10):
        if text in row.inner_text():
            return row
    return None


def revert(pg, text):
    row = find_row(pg, text)
    if row is None:
        return "NO ENTRY"
    btn = row.locator("button:has-text('Revert')")
    if not btn.count():
        return "not revertable"
    btn.click()
    pg.wait_for_load_state("networkidle")
    return pg.locator(".alert").first.inner_text().strip()


def save_profile_form(pg):
    with pg.expect_navigation(timeout=90000):
        pg.click("button:has-text('Save & Export')")
    pg.wait_for_load_state("networkidle")


def open_profile(pg, mid, pane):
    pg.goto(B + "@@pfas-method-profile-edit?method_id=" + mid)
    pg.wait_for_load_state("networkidle")
    pg.click("#method-profile-tabs [data-pane=%s]" % pane)
    pg.evaluate("p => document.querySelectorAll('#' + p + ' details').forEach(d => d.open = true)", pane)


def case_tier(pg):
    open_profile(pg, "EPA_537_1", "pane-rt")
    f = pg.locator("#recoveryTiersContainer .tier-max").first
    f.fill(str(float(f.input_value()) + 1)); f.dispatch_event("input")
    save_profile_form(pg)
    return "recovery_max", True, None


def case_toggle(pg):
    open_profile(pg, "EPA_537_1", "pane-toggles")
    pg.locator(".rule-toggle-cb").first.evaluate("e => e.click()")   # a styled switch hides the box
    save_profile_form(pg)
    return "method_rule_toggles", True, None


def case_surrogate(pg):
    open_profile(pg, "EPA_537_1", "pane-sur")
    sel = pg.locator("#pane-sur select[name^='t__sur__']").first
    original = sel.input_value()
    options = [o for o in sel.locator("option").evaluate_all("os => os.map(o => o.value)") if o and o != original]
    sel.select_option(options[0])
    save_profile_form(pg)
    # Each method owns its map (DECISIONS 2026-09-30): the change is a
    # method-profile entry, reverted from history like any other.
    return "surrogate_map", True, None


def case_cal_section(pg):
    """Calibration & CCV tab: its own form and save (R2)."""
    open_profile(pg, "EPA_537_1", "pane-cal")
    f = pg.locator("[name=f__ccv__recovery_max]")
    f.fill(str(float(f.input_value()) + 1))
    save_profile_form(pg)                       # the button now submits this tab
    return "ccv / recovery_max", True, None


def case_rl_table(pg):
    """Reporting Limits tab: a declared table, its own form (R2). Enters an RL
    on the second matrix's first colon-keyword analyte (or first row), which
    also proves hidden sub-tab cells and encoded keys reach the server."""
    open_profile(pg, "FDA_32PFAS", "pane-rl")
    pane = pg.locator("#section-rl-g1")
    cells = pane.locator("input[name$='__rl']")
    names = cells.evaluate_all("es => es.map(e => e.name)")
    pick = next((n for n in names if "_3a" in n), names[0])   # "_3a" = an encoded ":"
    pg.evaluate("n => { var e = document.querySelector('[name=\"' + n + '\"]'); e.value = '5'; "
                "e.dispatchEvent(new Event('input', {bubbles: true})); }", pick)
    save_profile_form(pg)
    return "reporting_limits", True, None


def case_matrices(pg):
    """Matrices & Units: a declared collection, its own form (R2)."""
    open_profile(pg, "EPA_537_1", "pane-mtx")
    f = pg.locator("#pane-mtx input[name$='__holding_5fdays']").first
    f.fill(str(int(float(f.input_value() or 14)) + 1))
    save_profile_form(pg)
    return "holding_times", True, None


def case_corrections(pg):
    """Sample Corrections: two declared tables saved by one form (R2)."""
    open_profile(pg, "FDA_32PFAS", "pane-corr")
    f = pg.locator("#pane-corr input[name^='t__mf__Milk__']")
    f.fill(str(float(f.input_value()) + 1))
    save_profile_form(pg)
    return "matrix_factors", True, None


def case_eis(pg):
    """EIS Limits (1633A): declared collections on one tab form (R2)."""
    open_profile(pg, "EPA_1633A", "pane-eis")
    f = pg.locator("[name='c__eis__0__recovery_5fmax']")
    f.fill(str(float(f.input_value()) + 1))
    save_profile_form(pg)
    return "eis_overrides", True, None


def case_edd_profile(pg):
    pg.goto(B + "@@pfas-egad-config#profiles"); pg.wait_for_load_state("networkidle")
    pg.evaluate("() => document.querySelectorAll('#pane-profiles details').forEach(d => d.open = true)")
    form = pg.locator("#pane-profiles form:has(input[name=edd_action][value=save])").first
    name = form.locator("input[name=name]")
    name.fill(name.input_value() + " (test)")
    with pg.expect_navigation(timeout=90000):
        form.locator("button[type=submit]").click()
    pg.wait_for_load_state("networkidle")
    return "EDD profile", True, None


def case_client_edd(pg):
    pg.goto(B + "clients"); pg.wait_for_load_state("networkidle")
    href = pg.locator("a[href*='/clients/client-']").first.get_attribute("href")
    url = re.match(r"(.*/clients/client-[^/?]+)", href).group(1) + "/@@pfas-egad-client-config"
    pg.goto(url); pg.wait_for_load_state("networkidle")
    f = pg.locator("[name=project_site]"); original = f.input_value()
    f.fill(original + " (test)")
    with pg.expect_navigation(): pg.click("button:has-text('Save Client EDD Settings')")

    def undo():
        pg.goto(url); pg.wait_for_load_state("networkidle")
        pg.fill("[name=project_site]", original)
        with pg.expect_navigation(): pg.click("button:has-text('Save Client EDD Settings')")
    return "Client EDD settings", False, undo


CASES = [("recovery tier", case_tier), ("rule toggle", case_toggle),
         ("cal section", case_cal_section), ("RL table", case_rl_table),
         ("matrices", case_matrices), ("corrections", case_corrections),
         ("EIS", case_eis),
         ("surrogate link", case_surrogate), ("EDD profile", case_edd_profile),
         ("client EDD", case_client_edd)]


def stale_toggle(browser, password):
    """Two sessions: A changes only a RULE TOGGLE, B saves from its stale page."""
    def session():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.goto(B + "login"); pg.fill("input[name=__ac_name]", "admin")
        pg.fill("input[name=__ac_password]", password)
        pg.click("button[type=submit], input[type=submit]"); pg.wait_for_load_state("networkidle")
        return pg
    a, b = session(), session()
    open_profile(a, "EPA_537_1", "pane-toggles"); open_profile(b, "EPA_537_1", "pane-toggles")
    a.locator(".rule-toggle-cb").first.evaluate("e => e.click()")
    save_profile_form(a)
    save_profile_form(b)
    err = b.locator(".alert-error")
    verdict = err.first.inner_text().strip()[:120] if err.count() else "NOT REFUSED"
    print("stale save after a toggle-only change:", verdict)
    print("  undo:", revert(a, "method_rule_toggles"))


def stale_section(browser, password):
    """Two sessions on the Calibration & CCV tab: A saves a change, B saves
    the same tab from its stale page and must be refused."""
    def session():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.goto(B + "login"); pg.fill("input[name=__ac_name]", "admin")
        pg.fill("input[name=__ac_password]", password)
        pg.click("button[type=submit], input[type=submit]"); pg.wait_for_load_state("networkidle")
        return pg
    a, b = session(), session()
    open_profile(a, "EPA_537_1", "pane-cal"); open_profile(b, "EPA_537_1", "pane-cal")
    f = a.locator("[name=f__ccv__recovery_max]")
    f.fill(str(float(f.input_value()) + 1))
    save_profile_form(a)
    save_profile_form(b)
    err = b.locator(".alert-error")
    print("stale section save:", err.first.inner_text().strip()[:140] if err.count() else "NOT REFUSED")
    print("  undo:", revert(a, "ccv / recovery_max"))


def main(out_dir):
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    start = audit.snapshot(os.path.join(out_dir, "check_before.json"))
    pw = audit.password()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
        pg.goto(B + "login"); pg.fill("input[name=__ac_name]", "admin")
        pg.fill("input[name=__ac_password]", pw)
        pg.click("button[type=submit], input[type=submit]"); pg.wait_for_load_state("networkidle")
        for name, fn in CASES:
            try:
                expect, revertable, undo = fn(pg)
                row = find_row(pg, expect)
                seen = row.inner_text().replace("\n", " ").replace("\t", " | ")[:120] if row else "NO ENTRY"
                back = revert(pg, expect) if revertable else (undo() or "undone in its editor")
                print("%-16s entry: %s\n%-16s -> %s" % (name, seen, "", back))
            except Exception as exc:                                    # noqa: BLE001
                print("%-16s FAILED: %s" % (name, str(exc).splitlines()[0][:140]))
        try:
            stale_toggle(browser, pw)
        except Exception as exc:                                        # noqa: BLE001
            print("stale toggle test FAILED:", str(exc).splitlines()[0][:140])
        try:
            stale_section(browser, pw)
        except Exception as exc:                                        # noqa: BLE001
            print("stale section test FAILED:", str(exc).splitlines()[0][:140])
        print("js errors:", errors or "none")
        browser.close()
    end = audit.snapshot(os.path.join(out_dir, "check_after.json"))
    start.pop("history_entries", None); end.pop("history_entries", None)
    left = [c for c in audit.diff(start, end) if not c[0].endswith(("updated_at", "updated_by"))]
    print("configuration afterwards equals before:", "YES" if not left else left[:5])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
