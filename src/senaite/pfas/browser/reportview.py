# -*- coding: utf-8 -*-
"""Render the per-result QC qualifier code beside the value on the certificate.

WHY THIS EXISTS
---------------
A qualified release means a failing QC criterion was released anyway because the
QAO's library says the failure is attributable to the sample. ISO 17025 §7.8.4
permits that only when the deviation is authorised, justified and RECORDED — and
the certificate is where the client's half of that record lives.

`data_review._stamp_qualifier_remarks` writes the code onto each affected
analysis at approve time. It was written believing that Remarks is "the one
per-analysis field core already prints". It is not. `senaite/impress/
analysisrequest/templates/results.pt` has no remarks cell at all, and
`remarks.pt` renders SAMPLE-level `model.getRemarks()` — a different field. Both
were verified against a real published certificate: 14 stamped analyses on
FEED-0002, and `QC: M` absent from the rendered HTML both with `show_remarks`
off AND on. The stamps were being written into a void.

HOW IT HOOKS IN, WITHOUT FORKING CORE
-------------------------------------
CLAUDE.md §6C forbids forking core templates, so the results table stays core's.
`results.pt` reads its rows from `view.collection` and formats each value with
`model.get_formatted_result(analysis)` — so the value formatter is reachable by
supplying our own models, without touching the template.

`PublishView.get_report_view_controller` queries a THREE-way multiadapter on
`(context, model_or_collection, request)` before falling back to impress's own
two-way one. Impress never registers a three-way adapter itself; its comment
says it exists "to allow 3rd party overriding with a browser layer". That is the
sanctioned seam, and it is layer-scoped — so this affects PFAS certificates only,
unlike overriding the `ISuperModel` adapter, which is registered `for="*"` with
no request and would have to be replaced site-wide.

WHY NOT READ THE QC SUMMARY DIRECTLY
------------------------------------
Because the stamp is the record. It was written at approve time by a named user
against the QC summary as it stood then; recomputing at render time would let a
certificate drift from the review that authorised it. The format is owned by
`qc_qualification.REMARK_PREFIX`, with `format_remark_codes` writing and
`parse_remark_codes` reading, so the two ends cannot drift apart either.
"""
from __future__ import absolute_import

from senaite.impress.analysisrequest.model import SuperModel as ImpressSuperModel
from senaite.impress.analysisrequest.reportview import MultiReportView as BaseMulti
from senaite.impress.analysisrequest.reportview import SingleReportView as BaseSingle

from senaite.pfas import logger
from senaite.pfas.qc_qualification import parse_remark_codes


class PFASSuperModel(ImpressSuperModel):
    """Impress' AnalysisRequest model, with the qualifier code on the value."""

    def get_formatted_result(self, analysis):
        """`12.4` becomes `12.4 [M]` when the result was qualified.

        Never raises: a formatting problem here would blank a RESULT on a
        certificate, which is far worse than a missing marker. On any failure
        the core value is returned unchanged.
        """
        formatted = super(PFASSuperModel, self).get_formatted_result(analysis)
        try:
            codes = parse_remark_codes(analysis.getRemarks() or u"")
        except Exception as exc:                                # noqa: BLE001
            logger.warning("qualifier marker: cannot read remarks: %s", exc)
            return formatted
        if not codes:
            return formatted
        return u'{0} <span class="qc-qualifier">[{1}]</span>'.format(
            formatted, u",".join(codes))


def _as_pfas_model(model):
    """Re-wrap an impress SuperModel as ours, keyed on the same UID.

    SuperModel is a thin lazy wrapper over a UID, so this is a re-adaptation,
    not a copy of the object graph.
    """
    if isinstance(model, PFASSuperModel):
        return model
    try:
        return PFASSuperModel(model.uid)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("qualifier marker: cannot wrap model %r: %s", model, exc)
        return model


class PFASSingleReportView(BaseSingle):
    """Single-sample certificate. Adapts (context, model, request).

    `context` is accepted because the three-way adapter passes it, and then
    deliberately DISCARDED. Core's `ReportView.__init__` sets
    `self.context = api.get_portal()`, and Five binds TAL `context` to
    `view.context` — which the CoA hands to every core section
    (`render_css`, `render_alerts`, `render_results`) and to
    `@@pfas-coa-attestation`. Assigning the traversed object here would change
    what all of them receive, differently depending on whether the user
    published from a sample, a client folder or the samples listing. Only
    `get_formatted_result` may differ from core.
    """

    def __init__(self, context, model, request):
        super(PFASSingleReportView, self).__init__(_as_pfas_model(model),
                                                   request)


class PFASMultiReportView(BaseMulti):
    """Multi-sample certificate. Adapts (context, collection, request).

    NOT currently exercised: impress selects the multi view by template name
    (a `Multi*` prefix), and this add-on ships only `CertificateOfAnalysis.pt`
    and `QCReviewReport.pt`. Two samples rendered together produce two SINGLE
    reports, each going through `PFASSingleReportView` — verified. Registered so
    that adding a multi template later does not silently lose the qualifier
    markers, which is precisely how they were lost the first time.

    `context` is discarded for the same reason as in the single view above.
    """

    def __init__(self, context, collection, request):
        super(PFASMultiReportView, self).__init__(
            [_as_pfas_model(m) for m in (collection or [])], request)
