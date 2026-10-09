"""Fail the image build if an installed package's licence is not allowed.

senaite.pfas is GPL-2.0. Every package in this image must be under a licence
compatible with it, or be dual-licensed with such an option (taken under that
option, recorded in TAKEN_UNDER). Apache-2.0 alone is refused.
"""
import sys
from importlib import metadata

ALLOWED = {"MIT", "MIT-0", "BSD-3-Clause", "BSD", "ISC", "PSF-2.0", "Python-2.0", "MIT License", "BSD License"}
# dual-licensed packages: the option taken
TAKEN_UNDER = {"cryptography": "BSD-3-Clause"}
# the base image's own tooling, not used by the scanner
IGNORE = {"pip", "setuptools", "wheel"}


def licence(dist):
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return " / ".join(classifiers) or (meta.get("License") or "").strip()


bad = []
for dist in metadata.distributions():
    name = (dist.metadata["Name"] or "").lower()
    if name in IGNORE:
        continue
    lic = licence(dist)
    if name in TAKEN_UNDER:
        ok = TAKEN_UNDER[name] in lic
    else:
        ok = lic in ALLOWED or any(part.strip() in ALLOWED for part in lic.replace(" OR ", "/").split("/"))
        ok = ok and "Apache" not in lic
    print("%-22s %-30s %s" % (name, lic, "ok" if ok else "REFUSED"))
    if not ok:
        bad.append(name)
if bad:
    sys.exit("licence check failed: %s" % ", ".join(bad))
