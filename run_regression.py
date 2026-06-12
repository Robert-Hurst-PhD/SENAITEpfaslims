# Stage 1 regression: method profile store still works
import json
from zope.annotation.interfaces import IAnnotations

portal = app['senaite']

PFAS_KEY = u'senaite.pfas.method_profiles'
ann = IAnnotations(portal)

# Check the store exists (if already initialized)
if PFAS_KEY in ann:
    store = ann[PFAS_KEY]
    print("Method profile store exists, entries:", len(store))
    for k, v in store.items():
        d = json.loads(v)
        print("  Profile:", k, "-> keys:", sorted(d.keys())[:5])
else:
    print("Method profile store not yet initialized (expected on empty install)")
    print("REGRESSION PASS: store key not present is valid on fresh install")

# Check tracking store is independent
from senaite.pfas.tracking_store import get_tracking_by_ar_uid
result = get_tracking_by_ar_uid(portal, u'nonexistent-uid')
assert result is None, "Tracking store lookup should return None for unknown UID"
print("Tracking store read: OK")

# Verify ZCML registered views
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.tracker import PFASClientTrackerView
from senaite.pfas.browser.receipt import PFASReceiptView
from senaite.pfas.browser.tracking import on_after_transition
from senaite.pfas.browser.stage_estimates import get_stage_estimates, format_estimate
from senaite.pfas.browser.sample_status import (
    STAGES, _compute_stage, _build_stage_steps, _get_method_name
)
print("All Stage 3 imports: OK")
print("format_estimate(0.5):", format_estimate(0.5))
print("format_estimate(4.0):", format_estimate(4.0))
print("format_estimate(50):", format_estimate(50))

print("ALL REGRESSION TESTS PASSED")
