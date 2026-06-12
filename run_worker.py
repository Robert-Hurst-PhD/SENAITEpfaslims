"""PFAS worker entry point — starts the instrument directory watcher."""
import logging, os
from pfas_pipeline.pipeline import start_watcher
from pfas_pipeline.senaite_connector import SenaiteConnector

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

senaite = SenaiteConnector(
    base_url=os.environ.get("SENAITE_URL", "http://senaite:8080/senaite"),
    username=os.environ.get("SENAITE_USER", "admin"),
    password=os.environ.get("SENAITE_PASS", "admin"),
)

start_watcher(
    watch_dir=os.environ.get("WATCH_DIR", "/data/instrument_output"),
    output_dir=os.environ.get("OUTPUT_DIR", "/data/reports"),
    extraction_log_dir=os.environ.get("EXTRACTION_LOG_DIR"),
    senaite=senaite,
)
