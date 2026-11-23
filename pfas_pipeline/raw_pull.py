"""The worker's pull: copies a run's raw data from the instrument's share,
reads it, and hands it to the worker as a raw run.

A run is pulled from the raw data folder of its worksheet's instrument (the
instrument's equipment record, in the export System keeps for the worker), else
from the folder System names for an instrument without its own; a run with
neither waits, saying which is missing (<stem>.rawstatus.json). Every folder
must be a path inside a mount of this worker (docs/RAW_DATA.md).

The Run Builder writes <stem>.rawexpect.json into the watch folder for a
method set to integrate from raw data (raw_expect.py). Each tick:

  1. ready     every expected injection's raw folder (<FILE_NAME>.raw) is on
               the share and unchanged for the settle time (System) as
               this server watched it; otherwise the run waits, saying what
               for (<stem>.rawstatus.json);
  2. pull      the folders are copied into the run's data area, each file's
               name, size, checksum and time recorded, and converted to mzML
               with the fixed conversion profile (CONVERT_ARGS: every MRM
               chromatogram kept) - except a MassLynx folder, which is read
               as it is (masslynx_raw) and recorded as the injection's file;
  3. hand over <stem>_extraction.json (the run record) and then <stem>.rawrun
               are written into the watch folder, which the worker imports.

A failure (a conversion error, a folder that cannot be read) writes
<stem>.rawfail and is recorded once in the import log that Data Review and
the Run Builder show: a run is never retried blindly. Deleting the .rawfail
file asks for it again.

The converter is ProteoWizard's msconvert, run by the pfas-convert service
from the image the lab names (PFAS_PWIZ_IMAGE) once it has accepted the
vendor licences it carries, with no network and only the raw-runs volume;
nothing of it is in this repository. PFAS_CONVERTER unset: Waters folders are
read natively and any other folder fails its run; "service": the same, with
pfas-convert for the folders that are not MassLynx; "native": mzML converted
on a Windows PC, in place of the reader for every folder.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone

from . import masslynx_raw
from .raw_run import _checksums, _sha256, folder_digest, safe_join

logger = logging.getLogger(__name__)

# msconvert's profile: mzML, 64-bit, zlib; chromatograms kept (no
# --srmAsSpectra, no filter that drops them)
CONVERT_ARGS = ["--mzML", "--64", "--zlib"]
RAW_SUFFIX = ".raw"


class ConversionError(Exception):
    pass


class _Native(object):
    """The run converted on a Windows PC (PFAS_CONVERTER=native,
    tools/convert/convert_native.ps1): each injection's <name>.mzML is on the
    share beside its raw folder, and is pulled as it is."""
    mode = "native"

    def __repr__(self):
        return "NATIVE"


NATIVE = _Native()
MZML_SUFFIX = ".mzML"


def masslynx_reader(fallback=None):
    """convert(src_folder, out_dir) -> the folder itself when it is a MassLynx
    folder that reads; any other folder goes to `fallback`, and fails the run
    when there is none."""
    def convert(src_folder, out_dir):
        name = os.path.basename(src_folder.rstrip("/"))
        if masslynx_raw.is_masslynx(src_folder):
            # a damaged MassLynx folder is not repaired by a converter: no
            # fallback. Every function is read here, so a short or
            # disagreeing index or data file fails the pull, not the import.
            try:
                masslynx_raw.read_chromatograms(src_folder)
            except masslynx_raw.MassLynxError as exc:
                raise ConversionError("%s: is a MassLynx folder but cannot be read: %s" % (name, exc))
            return src_folder
        if fallback is not None:
            return fallback(src_folder, out_dir)
        raise ConversionError("%s: not a MassLynx folder and no converter is set up "
                              "(PFAS_CONVERTER, docs/RAW_DATA.md)" % name)
    convert.mode = "masslynx"
    convert.fallback = fallback
    return convert

def listing(share, names=None):
    """{raw folder name: {"mtime": newest file time, "size": total bytes}} for
    the folders `names` (all raw folders when None): only what a run waits
    for is looked at on the share."""
    out = {}
    if not share or not os.path.isdir(share):
        return out
    for name in (names if names is not None else os.listdir(share)):
        folder = os.path.join(share, name)
        if name.endswith(MZML_SUFFIX) and os.path.isfile(folder):
            st = os.stat(folder)                     # a natively converted injection
            out[name] = {"mtime": st.st_mtime, "size": st.st_size}
            continue
        if not (name.lower().endswith(RAW_SUFFIX) and os.path.isdir(folder)):
            continue
        mtime, size = os.path.getmtime(folder), 0
        for root, _dirs, files in os.walk(folder):
            for f in files:
                st = os.stat(os.path.join(root, f))
                mtime, size = max(mtime, st.st_mtime), size + st.st_size
        out[name] = {"mtime": mtime, "size": size}
    return out


def _folder(inj):
    return (inj.get("file") or inj["name"]) + RAW_SUFFIX


def _item(inj, native=False):
    """What a run waits for on the share per injection: its raw folder, or
    its natively converted mzML."""
    return (inj.get("file") or inj["name"]) + MZML_SUFFIX if native else _folder(inj)


def ready(expectation, listing, now, settle_minutes, seen, native=False):
    """{"ready", "missing", "unsettled", "seen"}: a folder is settled once its
    size and file times are unchanged for the settle time as this server has
    watched them (`seen`: {folder: {"sig", "since"}} from the last pass), so
    the instrument PC's clock does not matter; one first seen is unsettled."""
    missing, unsettled, now_seen = [], [], {}
    for inj in expectation.get("injections") or []:
        folder = _item(inj, native)
        got = listing.get(folder)
        if got is None:
            missing.append(inj["name"])
            continue
        sig = [got["size"], got["mtime"]]
        before = (seen or {}).get(folder) or {}
        since = before.get("since") if before.get("sig") == sig else now
        now_seen[folder] = {"sig": sig, "since": since}
        if now - since < settle_minutes * 60:
            unsettled.append(inj["name"])
    return {"ready": not missing and not unsettled, "missing": missing, "unsettled": unsettled,
            "seen": now_seen}


class Shares(object):
    """Where each run is pulled from: the folder of the run's instrument, else
    `default`. `instruments`: {instrument uid: {"name", "folder"}}."""

    def __init__(self, default=None, instruments=None):
        self.default = default or None
        self.instruments = instruments or {}

    def for_run(self, expectation):
        """(folder, setup message): the folder to pull the run from, or None
        and what is missing."""
        uid = (expectation.get("run_record") or {}).get("instrument_uid") or ""
        if not uid:
            if self.default:
                return self.default, None
            return None, ("The run's worksheet has no instrument, so there is no folder to pull from. "
                          "Choose the instrument on the worksheet, or set a default folder on System. "
                          "Nothing is pulled.")
        known = self.instruments.get(uid)
        if known is None:
            if self.default:
                return self.default, None
            return None, ("The run's instrument is not an active analytical instrument on the Equipment "
                          "page, so there is no folder to pull from. Nothing is pulled.")
        if known.get("folder"):
            return known["folder"], None
        if self.default:
            return self.default, None
        return None, ("Instrument %s has no raw data folder: set one on its equipment record, or set a "
                      "default folder on System. Nothing is pulled." % (known.get("name") or uid))


def _shares(share):
    """`share` as Shares: a plain folder (or None) is the one folder every run
    is pulled from."""
    return share if isinstance(share, Shares) else Shares(share)


def _acquired(mzml_path):
    """The injection's acquisition time from the mzML run's startTimeStamp."""
    with open(mzml_path, "rb") as fh:
        head = fh.read(1 << 16).decode("utf-8", "replace")
    m = re.search(r'<run [^>]*startTimeStamp="([^"]+)"', head)
    return m.group(1).rstrip("Z") if m else None


def pull(expectation, share, run_dir, convert):
    """Copy and checksum every injection and read it: a MassLynx folder is
    the injection's file as copied; any other is converted to mzML (or, converted
    natively, its mzML is copied beside its raw folder when the share holds
    it). The raw run's manifest."""
    native = convert is NATIVE
    raw_dir, mzml_dir = os.path.join(run_dir, "raw"), os.path.join(run_dir, "mzml")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(mzml_dir, exist_ok=True)
    injections, modes = [], set()
    for inj in expectation.get("injections") or []:
        folder = _folder(inj)
        dst = safe_join(raw_dir, folder)
        if dst is None or safe_join(share, folder) is None:
            raise ConversionError("%s: the raw folder name %s is not a plain name" % (inj["name"], folder))
        if os.path.exists(dst):
            shutil.rmtree(dst)
        source = []
        if os.path.isdir(os.path.join(share, folder)):
            shutil.copytree(os.path.join(share, folder), dst)
            source = _checksums(dst)
        elif not native:
            raise ConversionError("%s: the raw folder %s is not on the share" % (inj["name"], folder))
        try:
            if native:
                mzml = os.path.join(mzml_dir, _item(inj, True))
                shutil.copy(os.path.join(share, _item(inj, True)), mzml)
            else:
                mzml = convert(dst, mzml_dir)
        except Exception as exc:                            # noqa: BLE001
            raise ConversionError("%s: %s" % (inj["name"], exc))
        out = dict((k, v) for k, v in inj.items() if k != "file")
        # the file is named inside the run's folder, never by an absolute path
        if os.path.isdir(mzml):
            mode = "masslynx"
            out.update(file=os.path.relpath(mzml, run_dir), sha256=folder_digest(source), source=source,
                       source_folder=folder)
            acquired = masslynx_raw.acquired(mzml)
        else:
            mode = getattr(getattr(convert, "fallback", None) or convert, "mode", "") or ""
            out.update(file=os.path.relpath(mzml, run_dir), sha256=_sha256(mzml), source=source,
                       source_folder=folder if source else "")
            acquired = _acquired(mzml)
        out["mode"] = mode
        modes.add(mode)
        if acquired:
            out["acquired"] = acquired
        injections.append(out)
    # the run's mode is how its injections were read, not the reader's name:
    # under "service" the reader is the MassLynx one whether or not it converted
    run_mode = (sorted(modes)[0] if len(modes) == 1 else "mixed" if modes
                else getattr(convert, "mode", "") or "")
    return {"run": expectation.get("run"),
            "instrument": (expectation.get("run_record") or {}).get("instrument_uid") or "",
            "run_dir": os.path.abspath(run_dir), "injections": injections,
            "converter": {"mode": run_mode, "args": CONVERT_ARGS,
                          "image": os.environ.get("PFAS_PWIZ_IMAGE", "") if "service" in modes else "",
                          "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}}


def _write(path, data):
    with open(path + ".part", "w") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.rename(path + ".part", path)


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def run_once(watch_dir, share, now, settle_minutes, run_root, convert, record_failure):
    """One pass over the expected runs; the stems handed over. A run waiting
    says what for in <stem>.rawstatus.json (Data Review's Instrument Report)."""
    done = []
    shares = _shares(share)
    for name in sorted(os.listdir(watch_dir)):
        if not name.endswith(".rawexpect.json"):
            continue
        stem = name[:-len(".rawexpect.json")]
        base = os.path.join(watch_dir, stem)
        if os.path.exists(base + ".rawrun") or os.path.exists(base + ".rawfail"):
            continue
        expectation = _read(os.path.join(watch_dir, name))
        share, setup = shares.for_run(expectation)
        if setup is None and not settle_minutes:
            setup = "The settle time is not set: set it on System. Nothing is pulled."
        if setup is None and not os.path.isdir(share):
            setup = ("The folder %s is not visible to the worker. Mount it in the worker "
                     "(docs/RAW_DATA.md) and check the path. Nothing is pulled." % share)
        if setup is not None:
            _write(base + ".rawstatus.json", {"setup": setup, "checked": now})
            continue
        native = convert is NATIVE
        items = [_item(inj, native) for inj in expectation.get("injections") or []]
        state = ready(expectation, listing(share, items), now, settle_minutes,
                      _read(base + ".rawstatus.json").get("seen"), native)
        if not state["ready"]:
            _write(base + ".rawstatus.json", {"missing": state["missing"], "unsettled": state["unsettled"],
                                              "seen": state["seen"], "checked": now})
            continue
        batch = (expectation.get("run_record") or {}).get("batch_id") or ""
        try:
            manifest = pull(expectation, share, os.path.join(run_root, stem), convert)
        except Exception as exc:                            # noqa: BLE001
            error = "The raw run %s was not pulled: %s" % (stem, exc)
            logger.error(error)
            _write(base + ".rawfail", {"error": error, "at": now})
            if record_failure is not None:
                record_failure(stem, batch, error)
            continue
        _write(base + "_extraction.json", expectation.get("run_record") or {})
        _write(base + ".rawrun", manifest)
        logger.info("Raw run %s pulled and read (%d injections)", stem, len(manifest["injections"]))
        done.append(stem)
    return done


def service_converter(queue_dir, timeout=1800.0, poll=0.5, keep=False):
    """convert(src_folder, out_dir) -> mzML path, by the converter service
    (pfas-convert, tools/convert/convert_loop.sh): a request in the queue,
    its answer awaited. `keep` leaves the request (tests)."""
    import time

    def convert(src_folder, out_dir):
        os.makedirs(queue_dir, exist_ok=True)
        name = "%s__%s" % (os.path.basename(os.path.dirname(os.path.abspath(out_dir))),
                           os.path.basename(src_folder.rstrip("/")))
        base = os.path.join(queue_dir, name)
        for old in (".done", ".failed"):
            if os.path.exists(base + old):
                os.remove(base + old)
        with open(base + ".request.part", "w") as fh:
            fh.write("%s\n%s\n%s\n" % (src_folder, out_dir, " ".join(CONVERT_ARGS)))
        os.rename(base + ".request.part", base + ".request")
        waited = 0.0
        try:
            while waited < timeout:
                if os.path.exists(base + ".done"):
                    with open(base + ".done") as fh:
                        return fh.read().strip()
                if os.path.exists(base + ".failed"):
                    with open(base + ".failed") as fh:
                        raise ConversionError("msconvert: %s" % " ".join(fh.read().split())[-400:])
                time.sleep(poll)
                waited += poll
            raise ConversionError("The converter service (pfas-convert, started with docker compose "
                                  "--profile raw-data) did not answer within %d s" % timeout)
        finally:
            if not keep:
                for ext in (".request", ".done", ".failed"):
                    if os.path.exists(base + ext):
                        os.remove(base + ext)
    convert.mode = "service"
    return convert


def converter_from_env(queue_dir):
    """The reader the worker is set up with (PFAS_CONVERTER): MassLynx folders
    read natively; "service" adds pfas-convert for any other folder; "native"
    takes the mzML a Windows PC converted."""
    mode = os.environ.get("PFAS_CONVERTER")
    if mode == "service":
        return masslynx_reader(service_converter(
            queue_dir, timeout=float(os.environ.get("PFAS_CONVERT_TIMEOUT") or 1800)))
    if mode == "native":
        return NATIVE
    return masslynx_reader()


def settings(path=None):
    """(Shares, settle minutes) from the System page's export, or (Shares(),
    None). An export that holds no instruments (written before instruments
    held their own folders) is the one folder for every run."""
    from .addon import load
    path = path or load("raw_share").EXPORT
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return Shares(), None
    return Shares(data.get("share_path"), data.get("instruments")), data.get("settle_minutes")


def tick(watch_dir, run_root, now=None):
    """The worker's pass: the site's share and settle time, the converter it
    is set up with, failures into the import log."""
    import time
    from . import import_log
    share, settle = settings()

    def record(stem, batch, error):
        import_log.record(stem + ".rawrun", batch, "failed", 1, error)
    return run_once(watch_dir, share, now or time.time(), settle, run_root,
                    converter_from_env(os.path.join(run_root, "queue")), record)
