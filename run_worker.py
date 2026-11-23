"""PFAS worker entry point — starts the instrument directory watcher and,
beside it, the raw-data converter service, the report package build, the
records seal (the signing thread) and the timed retry of certificate
e-mails that waited."""
import logging, os, threading
from pfas_pipeline.pipeline import start_watcher
from pfas_pipeline.senaite_connector import SenaiteConnector, credentials_from_env

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

_user, _password = credentials_from_env(os.environ)
senaite = SenaiteConnector(
    base_url=os.environ.get("SENAITE_URL", "http://senaite:8080/senaite"),
    username=_user,
    password=_password,
)



def _raw_pull_loop(watch_dir, run_root, every=60):
    """The converter service (raw_pull): pulls each run the Run Builder
    expects from the instrument's share once it is complete and settled."""
    import time
    from pfas_pipeline import raw_pull
    while True:
        try:
            raw_pull.tick(watch_dir, run_root)
        except Exception:                                   # noqa: BLE001
            logging.exception("raw-data pull failed")
        time.sleep(every)


threading.Thread(target=_raw_pull_loop, name="raw-pull", daemon=True, args=(
    os.environ.get("WATCH_DIR", "/data/instrument_output"),
    os.environ.get("RAW_RUN_DIR", "/data/raw_runs"))).start()


def _trace_pages(job, scope):
    """The chromatogram pages of a package job, drawn from the review traces
    in the QC database; the run's pages are kept under the package
    folder's traces/ for every sample of the worksheet."""
    from pfas_pipeline import trace_pages
    return trace_pages.pages_for_job(
        job, scope, os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db"),
        os.path.join(os.environ.get("PFAS_PACKAGE_DIR", "/data/qc/packages"), "traces"))


def _package_loop():
    """The report package build: one package per report whose certificate
    was stored at a tier beyond the certificate alone."""
    from pfas_pipeline import report_packages
    report_packages.loop(os.environ.get("PFAS_PACKAGE_DIR", "/data/qc/packages"), senaite,
                         every=int(os.environ.get("PACKAGE_POLL_SECONDS", "30")),
                         trace_pages_fn=_trace_pages,
                         timeout=int(os.environ.get("PACKAGE_TIMEOUT_SECONDS", "1200")))


threading.Thread(target=_package_loop, name="package-build", daemon=True).start()


def _signing_loop():
    """The records seal: every signature-ledger row sealed with the lab key,
    the head file rewritten, and each certificate stored without a package
    sealed from its queue. The key is read from the worker's secrets at
    every poll."""
    from pfas_pipeline import esig_seal, report_packages
    package_dir = os.environ.get("PFAS_PACKAGE_DIR", "/data/qc/packages")
    session = report_packages.thread_session(senaite)
    esig_seal.loop(os.environ.get("PFAS_SIGNATURES_DB", "/data/qc/signatures.db"),
                   esig_seal.signer_from_env,
                   every=int(os.environ.get("SIGNING_POLL_SECONDS", "30")),
                   certs_dir=os.environ.get("PFAS_SIGNATURE_CERTS", "/data/qc/signatures_certs"),
                   after=lambda signer: report_packages.seal_tick(package_dir, session, senaite.base, signer))


threading.Thread(target=_signing_loop, name="signing", daemon=True).start()


def _delivery_retry_loop():
    """Certificate e-mails that waited are sent again every few minutes,
    through SENAITE's own resend; nothing is tried while no mail server is
    named, and the wait grows while they keep failing."""
    from pfas_pipeline import delivery_retry, report_packages
    delivery_retry.loop(report_packages.thread_session(senaite), senaite.base,
                        every=int(os.environ.get("DELIVERY_RETRY_SECONDS", "300")),
                        most=int(os.environ.get("DELIVERY_RETRY_MAX_SECONDS", "3600")))


threading.Thread(target=_delivery_retry_loop, name="delivery-retry", daemon=True).start()

start_watcher(
    watch_dir=os.environ.get("WATCH_DIR", "/data/instrument_output"),
    output_dir=os.environ.get("OUTPUT_DIR", "/data/reports"),
    extraction_log_dir=os.environ.get("EXTRACTION_LOG_DIR"),
    senaite=senaite,
)
