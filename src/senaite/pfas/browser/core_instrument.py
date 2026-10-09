# -*- coding: utf-8 -*-
"""The PFAS instrument data interfaces, registered in SENAITE core's own
per-instrument lists ("register ours in core").

A core Instrument names an import interface and an export interface; core's
screens use them -- a worksheet's Export button, Setup's "Import instrument
results". These two make those screens go through the PFAS pipeline, never
around it:

    PFASPipelineImport   the uploaded export goes to the pipeline worker
                         exactly as a Run Builder upload does (run record,
                         Import Studio mapping, QC, rounding, push log);
                         core's direct-to-analysis importer is not used
    PFASSequenceExport   the worksheet's built run (Run Builder) as the
                         instrument's injection list, in the format kept in
                         Import Studio for the instrument (Waters MassLynx)

Core identifies an interface as "<module>.<class>", stored on the
Instrument. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
import re

from zope.interface import implementer

from senaite.core.exportimport.instruments import IInstrumentExportInterface
from senaite.core.exportimport.instruments import IInstrumentImportInterface

logger = logging.getLogger("senaite.pfas.core_instrument")

IMPORT_ID = "senaite.pfas.browser.core_instrument.PFASPipelineImport"
EXPORT_ID = "senaite.pfas.browser.core_instrument.PFASSequenceExport"


def match_worksheet(text, candidates):
    """(worksheet, hits) whose members' injection names the file names most;
    (None, 0) when none, or when two tie (never guessed). `candidates` =
    [(worksheet, [injection names])]. Pure."""
    scored = []
    for ws, names in candidates:
        hits = len([n for n in set(names) if n and re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(n), text)])
        if hits:
            scored.append((hits, ws))
    if not scored:
        return None, 0
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, 0
    return scored[0][1], scored[0][0]


@implementer(IInstrumentImportInterface)
class PFASPipelineImport(object):
    """Core's "Import instrument results" for a PFAS LC-MS: hands the file to
    the pipeline worker for the extraction batch whose LIMS-issued injection
    names it carries."""

    title = "PFAS pipeline (Import Studio mapping, QC, rounding)"
    __name__ = "PFASPipelineImport"

    def __init__(self, context):
        self.context = context

    def Import(self, context, request):
        from bika.lims import api
        from senaite.pfas import extraction_batch
        from senaite.pfas.browser.run_builder import PFASRunBuilderView
        form = request.form
        infile = form.get("instrument_results_file")
        if isinstance(infile, list):
            infile = infile[0]
        if not hasattr(infile, "filename"):
            return json.dumps({"errors": ["No file selected"], "log": [], "warns": []})
        data = infile.read()
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
        instrument_uid = form.get("instrument") or u""
        candidates = []
        for brain in api.search({"portal_type": "Worksheet", "review_state": "open"},
                                "senaite_catalog_worksheet"):
            ws = api.get_object(brain)
            inst = ws.getInstrument() if hasattr(ws, "getInstrument") else None
            if instrument_uid and inst is not None and api.get_uid(inst) != instrument_uid:
                continue
            names = [m.get("injection") for m in extraction_batch.load(ws)]
            if names:
                candidates.append((ws, names))
        ws, hits = match_worksheet(text, candidates)
        if ws is None:
            return json.dumps({"errors": [
                "No single extraction batch's injection names were found in this file. "
                "Upload it from the Run Builder for its worksheet."], "log": [], "warns": []})
        view = PFASRunBuilderView(api.get_portal(), request)
        note, error = view.deliver(ws.getId(), infile.filename, data)
        if error:
            return json.dumps({"errors": [error], "log": [], "warns": []})
        return json.dumps({"errors": [], "warns": [], "log": [
            "%s: %d of its injection names found." % (ws.getId(), hits), note,
            "Results are written by the pipeline after its QC; review them in Data Review."]})


@implementer(IInstrumentExportInterface)
class PFASSequenceExport(object):
    """Core's worksheet Export for a PFAS LC-MS: the worksheet's built run as
    the instrument's injection list."""

    title = "PFAS injection list (Run Builder, Import Studio format)"
    __name__ = "PFASSequenceExport"

    def __init__(self, context):
        self.context = context

    def Export(self, context, request):
        return _Exporter(context, request)


class _Exporter(object):

    def __init__(self, context, request):
        self.context, self.request = context, request

    def __call__(self, analyses):
        from senaite.pfas.browser.run_builder import PFASRunBuilderView
        from bika.lims import api
        ws = self.context
        view = PFASRunBuilderView(api.get_portal(), self.request)
        self.request.form["batch_id"] = ws.getId()
        m = view.manifest()
        resp = self.request.response
        if not m:
            ws.plone_utils.addPortalMessage(
                u"Build the run in the Run Builder first: the injection list is its sequence.", "info")
            resp.redirect(u"%s/@@pfas-run-builder?batch_id=%s" % (api.get_portal().absolute_url(), ws.getId()))
            return u""
        resp.setHeader("Content-Type", "text/csv")
        resp.setHeader("Content-Disposition", "attachment; filename=%s-injections.csv" % ws.getId())
        resp.write(view.masslynx_csv(m, ws))
        return u""
