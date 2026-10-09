# -*- coding: utf-8 -*-
"""What a manager must act on, for the QC Management landing: the downstream effects of configuration, in one queue.

    items(facts) -> [{"level": "bad" | "warn", "title", "detail",
                      "actions": [(label, path)], "help": entry id}]

`facts` is gathered by the landing view (browser/workspace_home.py):
    template      report_templates.status(...) or None
    held          {reason: [sample ids]} -- samples verified / published that
                  cannot be (re)published, by reason
    edd_missing   {EDD profile title: [internal codes without a state code]}
    unverified    number of regulatory limits not verified
    methods_changed  [method titles changed since their last issued revision]

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

HELD_TEXT = {
    "method": "method not identified",
    "legacy": "run stored before verdicts were kept",
    "unrounded": "run judged before rounding applied",
    "rule_changed": "rounding rule changed since the run",
    "unjudged": "nothing judged for the injection",
    "error": "the QC data could not be read",
}


def _ids(ids, limit=5):
    shown = ", ".join(ids[:limit])
    return shown + (" and %d more" % (len(ids) - limit) if len(ids) > limit else "")


def items(facts):
    out = []
    tpl = facts.get("template")
    if tpl is not None and tpl.get("none_issued"):
        out.append({"level": "bad", "title": "No reporting template issued",
                    "detail": "Nothing can be published until the first revision is issued.",
                    "actions": [("Reporting Template", "@@pfas-report-template")],
                    "help": "reporting-template"})
    elif tpl is not None and tpl.get("unissued"):
        out.append({"level": "warn", "title": "Reporting template has unissued changes",
                    "detail": "Certificates still use revision %s." % tpl.get("rev"),
                    "actions": [("Reporting Template", "@@pfas-report-template")],
                    "help": "reporting-template"})
    for reason, ids in sorted((facts.get("held") or {}).items()):
        if not ids:
            continue
        reprocess = reason in ("legacy", "unrounded", "rule_changed", "unjudged")
        out.append({"level": "bad",
                    "title": "%d sample%s held from publishing" % (len(ids), "" if len(ids) == 1 else "s"),
                    "detail": "%s: %s." % (HELD_TEXT.get(reason, reason).capitalize(), _ids(ids)),
                    "actions": ([("Run Builder", "@@pfas-run-builder")] if reprocess else [])
                               + [("Data Review", "@@pfas-data-review")],
                    "help": "reprocess" if reprocess else "publishing-holds"})
    for profile, codes in sorted((facts.get("edd_missing") or {}).items()):
        if codes:
            out.append({"level": "warn", "title": "EDD codes missing in %s" % profile,
                        "detail": "No state code for %s: EDDs carrying them are refused." % ", ".join(codes),
                        "actions": [("EDD Export", "@@pfas-edd-config")],
                        "help": "edd-qualifiers"})
    n = facts.get("unverified") or 0
    if n:
        out.append({"level": "warn", "title": "%d regulatory limit%s not verified" % (n, "" if n == 1 else "s"),
                    "detail": "An unverified limit never reaches a certificate.",
                    "actions": [("Regulatory Limits", "@@pfas-regulatory-limits")],
                    "help": "action-level"})
    for title in facts.get("methods_changed") or []:
        out.append({"level": "warn", "title": "%s changed since its last issued revision" % title,
                    "detail": "Issue a new method revision to record the change.",
                    "actions": [("Method Profiles", "@@pfas-method-profiles")],
                    "help": "method-profile"})
    return out
