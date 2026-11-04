# -*- coding: utf-8 -*-
"""One name per QC type: the full name with its abbreviation, wherever QC
types are listed. Counts and column heads use the abbreviation alone. The
continuing check is CCV throughout.

    QC_NAMES            {code: name}
    qc_name(code)       -> the name, else the code itself

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

QC_NAMES = {
    u"LFSM": u"Laboratory Fortified Sample Matrix (LFSM)",
    u"LFSMD": u"LFSM Duplicate (LFSMD)",
    u"MB": u"Method Blank (MB)",
    u"LRB": u"Laboratory Reagent Blank (LRB)",
    u"LFB": u"Laboratory Fortified Blank (LFB)",
    u"LCS": u"Laboratory Control Sample (LCS)",
    u"MxB": u"Matrix Blank (MxB)",
    u"Dup": u"Sample Duplicate (Dup)",
    u"CCB": u"Solvent Blank (CCB)",
    u"FRB": u"Field Reagent Blank (FRB)",
    u"TB": u"Trip Blank",
}


# what each QC type is judged on, and where its limits are set
QC_JUDGED = {
    u"LFSM": u"Recovery of each analyte against the LFSM recovery tier for its matrix and spike level, on Recovery Tiers.",
    u"LFSMD": u"RPD between the LFSM and its duplicate against the LFSMD RPD tier, on Recovery Tiers.",
    u"MB": u"Each analyte's result against the MB limit, a multiple of its RL, below.",
    u"LRB": u"Each analyte's result against the LRB limit, a multiple of its RL, below.",
    u"MxB": u"Each analyte's result against the MxB limit, below.",
    u"LFB": u"Recovery of each analyte against the LFB recovery tier, on Recovery Tiers.",
    u"LCS": u"Recovery of each analyte against the LCS recovery tier, on Recovery Tiers.",
    u"Dup": u"RPD between a sample and its duplicate against the Dup RPD limit, on Recovery Tiers.",
}


def qc_name(code):
    return QC_NAMES.get(code) or code
