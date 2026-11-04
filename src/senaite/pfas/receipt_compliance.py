# -*- coding: utf-8 -*-
"""A sample received out of compliance with its method's requirements.

Its results carry the receipt qualifier (qc_qualification, failure type
"receipt": code H by default, the QAO's wording) -- the sample was not
received as the method requires, so the accuracy of its results cannot be
guaranteed. A compliance sample (marked on its CoC row) is also held from
publishing, and a resample is requested from the client: re-running the
same sample cannot change how it arrived.

The method requirements are the receipt flags (coc_records.receipt_problems)
that are the method's: the sample's own receipt temperature, or the
cooler's temperature blank, out of the method's range; holding time
exceeded; the shipment answered not compliant. Custody seals and labels are
recorded on the CoC but are not the method's requirements.

    breaches(flags, sample_names)       -> the flags that breach for a sample
    resample_required(compliance, breaches) -> bool
    compliance_value(raw)               -> bool

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

TEMP_PREFIX = u"temperature out of range: "
TEMP_BLANK = u"temperature blank"
SHIPMENT_FLAGS = (u"holding time exceeded", u"received not compliant")


def breaches(flags, sample_names):
    names = set(n for n in sample_names or () if n)
    out = []
    for f in flags or []:
        if f.startswith(TEMP_PREFIX):
            rest = f[len(TEMP_PREFIX):]
            if rest.startswith(TEMP_BLANK + u" ") or rest.split(u" ", 1)[0] in names:
                out.append(f)
        elif f in SHIPMENT_FLAGS:
            out.append(f)
    return out


def resample_required(compliance, found):
    return bool(compliance) and bool(found)


def compliance_value(raw):
    return (u"%s" % (raw if raw is not None else u"")).strip().lower() in (u"yes", u"on", u"true", u"1")
