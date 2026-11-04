# -*- coding: utf-8 -*-
"""Control charts' lab overlay: which readings are
drawn with the chart and how.

Several readings may be chosen at once, each a switch (ov.<value>; a form
list would keep only its first value); a link's single ?overlay= is read
too. They show Stacked -- a strip per reading under the chart, on the same
run axis -- or as a Relative overlay: the analyte in standard deviations
from its mean, each reading in its own units. Each run's reading is that run day's mean (the points carry no
time of day).

    selected(form, option_values) -> [value]
    show(form)                    -> "stacked" | "relative"

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

SHOW = (u"stacked", u"relative")


def selected(form, option_values):
    form = form or {}
    chosen = [v for v in option_values or [] if form.get(u"ov.%s" % v)]
    legacy = form.get("overlay")
    if not chosen and legacy in (option_values or []):
        chosen = [legacy]
    return chosen


def show(form):
    v = (form or {}).get("show")
    return v if v in SHOW else u"stacked"
