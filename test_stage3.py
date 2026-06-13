import transaction
from senaite.pfas.tracking_store import (
    get_or_assign_tracking, get_ar_uid_by_tracking, get_tracking_by_ar_uid,
    generate_tracking_number
)

portal = app['senaite']

# --- Test generate_tracking_number format ---
tn = generate_tracking_number()
import re
assert re.match(r'^PF-\d{6}-[A-Z0-9]{4}$', tn), "Bad format: " + tn
print("Format OK:", tn)

# --- Test idempotency with a fake AR stub ---
class FakeAR(object):
    def UID(self):
        return u'test-ar-uid-001'
    def getId(self):
        return 'SA-001'

fake_ar = FakeAR()

# First call: should mint a new number
tn1 = get_or_assign_tracking(portal, fake_ar)
print("Minted:", tn1)
assert tn1 is not None
assert re.match(r'^PF-\d{6}-[A-Z0-9]{4}$', tn1)

# Second call: should return the SAME number (idempotency)
tn2 = get_or_assign_tracking(portal, fake_ar)
assert tn1 == tn2, "Idempotency failed: {0} != {1}".format(tn1, tn2)
print("Idempotency OK:", tn2)

# Reverse lookup
found = get_tracking_by_ar_uid(portal, u'test-ar-uid-001')
assert found == tn1, "Reverse lookup failed"
print("Reverse lookup OK:", found)

# Forward lookup
found_uid = get_ar_uid_by_tracking(portal, tn1)
assert found_uid == u'test-ar-uid-001', "Forward lookup failed"
print("Forward lookup OK:", found_uid)

# Not found case
missing = get_ar_uid_by_tracking(portal, u'PF-999999-ZZZZ')
assert missing is None
print("Not-found case OK")

transaction.commit()
print("ALL TRACKING STORE TESTS PASSED")
