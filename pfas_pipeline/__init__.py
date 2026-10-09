"""
SENAITE PFAS Pipeline
The out-of-process worker: imports an instrument export, applies the method
profile's corrections and QC checks, builds the summary and batch report, and
pushes results to SENAITE. Method criteria come from the method profiles the
lab configures (sources:).
"""
