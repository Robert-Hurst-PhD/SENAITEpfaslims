# pfas-scan (report text reader)

Reads the text of each page of an uploaded instrument report so SENAITE can
find the pages carrying the lab's manual-integration heading.
pdfminer.six (MIT) behind `POST /text`; internal `render` network only, no
published port, non-root, 150 MB / 120 s limits.

It is a separate container because pdfminer.six's last Python 2 release needs
pycryptodome, a C build the SENAITE image (Python 2.7, no compiler) cannot do.

`licence_check.py` runs at build and fails on any package whose licence is not
GPL-2.0-compatible. `cryptography` is dual-licensed and taken under
BSD-3-Clause.

    docker compose build pfas-scan && docker compose up -d pfas-scan

Reports uploaded before the scanner existed:

    docker exec -u senaite senaite_pfas-senaite-1 python /addon/tools/scan_instrument_reports.py
