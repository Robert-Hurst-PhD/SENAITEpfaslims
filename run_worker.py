"""PFAS worker entry point — starts the instrument directory watcher and,
beside it, the raw-data converter service."""
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

start_watcher(
    watch_dir=os.environ.get("WATCH_DIR", "/data/instrument_output"),
    output_dir=os.environ.get("OUTPUT_DIR", "/data/reports"),
    extraction_log_dir=os.environ.get("EXTRACTION_LOG_DIR"),
    senaite=senaite,
)
