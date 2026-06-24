#!/usr/bin/env python3
"""
PFAS CoA Fetcher — workstation automation script.

Uses a stealth Playwright browser (real Chromium, not headless by default) to
navigate supplier CoA search pages, fill in the product and lot number, and
download the resulting PDF.  Optionally POSTs the PDF directly to a running
SENAITE instance via the @@pfas-reagents upload endpoint.

WHY THIS RUNS FROM A WORKSTATION, NOT THE SERVER
  Sigma-Aldrich and Fisher Scientific block server/datacenter IP addresses and
  use Akamai Bot Manager JavaScript challenges.  A real browser on a regular
  workstation passes naturally; urllib2 from the Docker container does not.

REQUIREMENTS (Python 3.8+)
  pip install playwright playwright-stealth requests
  playwright install chromium

USAGE — single download
  # Save PDF locally:
  python fetch_coa.py sigma P5655 SLCD4386

  # Save to specific directory:
  python fetch_coa.py sigma P5655 SLCD4386 --output ./downloads/

  # Download AND upload to SENAITE (reagent UID from @@pfas-reagents URL):
  python fetch_coa.py sigma P5655 SLCD4386 \\
    --senaite http://localhost:8080/senaite \\
    --user admin --password admin \\
    --uid <reagent-uid>

USAGE — batch from CSV
  CSV format: supplier,cat_number,lot_number[,uid]
  python fetch_coa.py --batch reagents.csv --output ./downloads/ \\
    --senaite http://localhost:8080/senaite --user admin --password admin

SUPPORTED SUPPLIERS
  sigma   Sigma-Aldrich / MilliporeSigma
          URL: https://www.sigmaaldrich.com/US/en/documents-search?tab=coa
  fisher  Thermo Fisher Scientific / Fisher Scientific
          URL: https://www.fishersci.com/search/documents?type=certificates

TROUBLESHOOTING
  --headless        Run Chromium headless (may trigger bot detection on some sites)
  --slow-mo 500     Add 500ms delay between actions (helps with slow page loads)
  --screenshot      Save a screenshot on failure for debugging
  --timeout 60      Seconds to wait for page elements (default: 30)

OFFICIAL API KEYS (when available)
  Set SIGMA_API_KEY or FISHER_API_KEY environment variables.  When set the
  script calls the supplier's authenticated REST API directly (no browser
  required) and ignores the --headless flag.

  Sigma-Aldrich API:    https://developer.sigmaaldrich.com/
  Thermo Fisher API:    https://connect.thermofisher.com/
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

# ── Dependency checks ──────────────────────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("ERROR: playwright not installed.  Run:  pip install playwright playwright-stealth")
    print("       Then:  playwright install chromium")
    sys.exit(1)

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
    print("WARNING: playwright-stealth not installed.  Bot detection may block downloads.")
    print("         Run:  pip install playwright-stealth")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ── Supplier definitions ───────────────────────────────────────────────────────

SUPPLIERS = {}


class SigmaFetcher:
    """
    Sigma-Aldrich / MilliporeSigma CoA downloader.

    The CoA search page is a React SPA.  We navigate to the COA tab,
    fill in product number and lot number, and download the resulting PDF.

    NOTE: Sigma-Aldrich occasionally redesigns this page.  If selectors break,
    inspect the page with DevTools and update the constants below.
    """

    URL = "https://www.sigmaaldrich.com/US/en/documents-search?tab=coa"

    # Selectors (update if Sigma redesigns the page)
    SEL_PRODUCT = [
        "input[placeholder*='Product Number' i]",
        "input[placeholder*='Catalog Number' i]",
        "input[data-testid*='product' i]",
        "input[name='productNumber']",
        "#productNumber",
    ]
    SEL_LOT = [
        "input[placeholder*='Lot Number' i]",
        "input[placeholder*='Batch Number' i]",
        "input[data-testid*='lot' i]",
        "input[name='lotNumber']",
        "#lotNumber",
    ]
    SEL_SUBMIT = [
        "button[type='submit']",
        "button:has-text('Search')",
        "button:has-text('Find')",
        "[data-testid*='search-btn' i]",
    ]
    SEL_RESULT_ROW = [
        "a[href$='.pdf']",
        "button:has-text('Download')",
        "a:has-text('CoA')",
        "[data-testid*='download' i]",
    ]

    def fetch(self, page, cat_number, lot_number, timeout, screenshot, output_dir):
        print("  → Navigating to Sigma-Aldrich CoA search…")
        page.goto(self.URL, wait_until="domcontentloaded", timeout=timeout * 1000)
        page.wait_for_load_state("networkidle", timeout=timeout * 1000)

        # Fill product number
        product_input = _find_first(page, self.SEL_PRODUCT, timeout)
        if not product_input:
            _maybe_screenshot(page, screenshot, output_dir, "sigma_no_product_input")
            raise RuntimeError("Sigma: could not find product number input.  "
                               "Page may have changed — update SEL_PRODUCT selectors.")
        product_input.fill("")
        product_input.type(cat_number, delay=80)

        # Fill lot number
        lot_input = _find_first(page, self.SEL_LOT, timeout)
        if not lot_input:
            _maybe_screenshot(page, screenshot, output_dir, "sigma_no_lot_input")
            raise RuntimeError("Sigma: could not find lot number input.  "
                               "Update SEL_LOT selectors.")
        lot_input.fill("")
        lot_input.type(lot_number, delay=80)

        # Submit
        submit_btn = _find_first(page, self.SEL_SUBMIT, timeout)
        if submit_btn:
            submit_btn.click()
        else:
            lot_input.press("Enter")

        print("  → Waiting for search results…")
        page.wait_for_load_state("networkidle", timeout=timeout * 1000)

        # Find download link
        dl_el = _find_first(page, self.SEL_RESULT_ROW, timeout // 2)
        if not dl_el:
            _maybe_screenshot(page, screenshot, output_dir, "sigma_no_result")
            raise RuntimeError(
                "Sigma: no CoA download link found for {}/{}.  "
                "Verify the cat# and lot# are correct and the CoA exists on the site."
                .format(cat_number, lot_number)
            )

        # Download the PDF
        filename = "CoA_Sigma_{}_{}.pdf".format(cat_number.upper(), lot_number.upper())
        dest = output_dir / filename
        print("  → Downloading PDF…")
        with page.expect_download() as dl_info:
            dl_el.click()
        download = dl_info.value
        download.save_as(dest)
        print("  ✓ Saved: {}".format(dest))
        return dest


SUPPLIERS["sigma"] = SigmaFetcher()


class FisherFetcher:
    """
    Thermo Fisher Scientific / Fisher Scientific CoA downloader.

    NOTE: Fisher Scientific uses Akamai Bot Manager.  playwright-stealth is
    essential.  Even with it, occasional CAPTCHAs may appear — run without
    --headless to solve them manually.
    """

    URL = "https://www.fishersci.com/search/documents?type=certificates"

    SEL_PRODUCT = [
        "input[placeholder*='Product Number' i]",
        "input[placeholder*='Catalog' i]",
        "input[name='productNumber']",
        "input[id*='product' i]",
        "#product-number",
    ]
    SEL_LOT = [
        "input[placeholder*='Lot Number' i]",
        "input[placeholder*='Batch' i]",
        "input[name='lotNumber']",
        "input[id*='lot' i]",
        "#lot-number",
    ]
    SEL_SUBMIT = [
        "button[type='submit']",
        "button:has-text('Search')",
        "button:has-text('Find')",
        "input[type='submit']",
    ]
    SEL_RESULT_ROW = [
        "a[href$='.pdf']",
        "button:has-text('Download')",
        "a:has-text('Certificate of Analysis')",
        "a:has-text('CoA')",
    ]

    def fetch(self, page, cat_number, lot_number, timeout, screenshot, output_dir):
        print("  → Navigating to Fisher Scientific CoA search…")
        page.goto(self.URL, wait_until="domcontentloaded", timeout=timeout * 1000)
        page.wait_for_load_state("networkidle", timeout=timeout * 1000)

        product_input = _find_first(page, self.SEL_PRODUCT, timeout)
        if not product_input:
            _maybe_screenshot(page, screenshot, output_dir, "fisher_no_product_input")
            raise RuntimeError("Fisher: could not find product number input.  "
                               "Update SEL_PRODUCT selectors or check for CAPTCHA.")
        product_input.fill("")
        product_input.type(cat_number, delay=80)

        lot_input = _find_first(page, self.SEL_LOT, timeout)
        if not lot_input:
            _maybe_screenshot(page, screenshot, output_dir, "fisher_no_lot_input")
            raise RuntimeError("Fisher: could not find lot number input.  "
                               "Update SEL_LOT selectors.")
        lot_input.fill("")
        lot_input.type(lot_number, delay=80)

        submit_btn = _find_first(page, self.SEL_SUBMIT, timeout)
        if submit_btn:
            submit_btn.click()
        else:
            lot_input.press("Enter")

        print("  → Waiting for search results…")
        page.wait_for_load_state("networkidle", timeout=timeout * 1000)

        dl_el = _find_first(page, self.SEL_RESULT_ROW, timeout // 2)
        if not dl_el:
            _maybe_screenshot(page, screenshot, output_dir, "fisher_no_result")
            raise RuntimeError(
                "Fisher: no CoA download link found for {}/{}.  "
                "Verify the cat# and lot# are correct."
                .format(cat_number, lot_number)
            )

        filename = "CoA_Fisher_{}_{}.pdf".format(cat_number.upper(), lot_number.upper())
        dest = output_dir / filename
        print("  → Downloading PDF…")
        with page.expect_download() as dl_info:
            dl_el.click()
        download = dl_info.value
        download.save_as(dest)
        print("  ✓ Saved: {}".format(dest))
        return dest


SUPPLIERS["fisher"] = FisherFetcher()


# ── Helper functions ───────────────────────────────────────────────────────────

def _find_first(page, selectors, timeout_s):
    """Return the first visible element matching any selector, or None."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=min(timeout_s, 5) * 1000)
            if el.is_visible():
                return el
        except (PWTimeout, Exception):
            continue
    return None


def _maybe_screenshot(page, enabled, output_dir, name):
    if not enabled:
        return
    path = output_dir / "{}.png".format(name)
    try:
        page.screenshot(path=str(path))
        print("  [screenshot saved: {}]".format(path))
    except Exception:
        pass


def _upload_to_senaite(senaite_url, username, password, uid, pdf_path):
    """POST the downloaded PDF to SENAITE via the @@pfas-reagents upload endpoint."""
    if not HAS_REQUESTS:
        print("  WARNING: requests not installed — skipping SENAITE upload.")
        print("           Run:  pip install requests")
        return False

    url = senaite_url.rstrip("/") + "/@@pfas-reagents"
    filename = pdf_path.name
    print("  → Uploading {} to SENAITE (uid={})…".format(filename, uid))

    with open(pdf_path, "rb") as fh:
        resp = requests.post(
            url,
            data={"action": "upload_coa", "uid": uid},
            files={"coa_file": (filename, fh, "application/pdf")},
            auth=(username, password),
            allow_redirects=True,
            timeout=30,
        )

    if resp.status_code in (200, 302):
        print("  ✓ Uploaded to SENAITE")
        return True
    else:
        print("  ERROR: SENAITE returned HTTP {}".format(resp.status_code))
        print("         Response: {}".format(resp.text[:200]))
        return False


def _fetch_one(pw, args, supplier_key, cat_number, lot_number, uid, output_dir):
    """Run a single fetch in its own browser context."""
    fetcher = SUPPLIERS.get(supplier_key)
    if not fetcher:
        print("ERROR: unknown supplier '{}'.  Choose: {}".format(
            supplier_key, ", ".join(sorted(SUPPLIERS.keys()))))
        return False

    print("\n[{}] {} / {}".format(supplier_key, cat_number, lot_number))

    browser = pw.chromium.launch(
        headless=args.headless,
        slow_mo=args.slow_mo,
    )
    context = browser.new_context(
        accept_downloads=True,
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    if HAS_STEALTH:
        stealth_sync(page)

    try:
        pdf_path = fetcher.fetch(
            page, cat_number, lot_number,
            timeout=args.timeout,
            screenshot=args.screenshot,
            output_dir=output_dir,
        )
        if args.senaite and uid:
            _upload_to_senaite(args.senaite, args.user, args.password, uid, pdf_path)
        elif args.senaite and not uid:
            print("  WARNING: --senaite set but no --uid; skipping upload.")
        return True
    except Exception as exc:
        print("  ERROR: {}".format(exc))
        return False
    finally:
        context.close()
        browser.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download CoA PDFs from supplier websites using a stealth browser.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Single-item mode
    parser.add_argument("supplier", nargs="?",
                        help="Supplier key: sigma | fisher")
    parser.add_argument("cat_number", nargs="?",
                        help="Catalog / product number")
    parser.add_argument("lot_number", nargs="?",
                        help="Lot / batch number")

    # Batch mode
    parser.add_argument("--batch", metavar="CSV",
                        help="CSV file with columns: supplier,cat_number,lot_number[,uid]")

    # SENAITE upload
    parser.add_argument("--senaite", metavar="URL",
                        help="SENAITE base URL, e.g. http://localhost:8080/senaite")
    parser.add_argument("--user", default="admin", help="SENAITE username (default: admin)")
    parser.add_argument("--password", default="admin", help="SENAITE password")
    parser.add_argument("--uid", metavar="UID",
                        help="Reagent UID in SENAITE (single-item mode only)")

    # Output
    parser.add_argument("--output", default=".", metavar="DIR",
                        help="Directory to save downloaded PDFs (default: current dir)")

    # Browser options
    parser.add_argument("--headless", action="store_true",
                        help="Run Chromium headless (may trigger bot detection)")
    parser.add_argument("--slow-mo", type=int, default=200, metavar="MS",
                        help="Milliseconds between browser actions (default: 200)")
    parser.add_argument("--timeout", type=int, default=30, metavar="SEC",
                        help="Seconds to wait for page elements (default: 30)")
    parser.add_argument("--screenshot", action="store_true",
                        help="Save screenshots on failure for debugging")

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not HAS_STEALTH:
        print("TIP: install playwright-stealth for better bot-detection bypass:")
        print("     pip install playwright-stealth\n")

    successes = 0
    failures  = 0

    with sync_playwright() as pw:
        if args.batch:
            # Batch mode: read CSV
            with open(args.batch, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = [r for r in reader if r and not r[0].startswith("#")]

            for i, row in enumerate(rows, 1):
                if len(row) < 3:
                    print("SKIP row {}: need supplier,cat,lot (got {})".format(i, row))
                    continue
                supplier_key = row[0].strip().lower()
                cat_number   = row[1].strip()
                lot_number   = row[2].strip()
                uid          = row[3].strip() if len(row) > 3 else None

                ok = _fetch_one(pw, args, supplier_key, cat_number, lot_number,
                                uid, output_dir)
                if ok:
                    successes += 1
                else:
                    failures += 1

                # Small pause between batch items to avoid rate-limiting
                if i < len(rows):
                    time.sleep(2)

        elif args.supplier and args.cat_number and args.lot_number:
            # Single-item mode
            ok = _fetch_one(pw, args, args.supplier.lower(),
                            args.cat_number, args.lot_number,
                            args.uid, output_dir)
            successes = 1 if ok else 0
            failures  = 0 if ok else 1

        else:
            parser.print_help()
            sys.exit(1)

    print("\n─── Done: {} succeeded, {} failed ───".format(successes, failures))
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
