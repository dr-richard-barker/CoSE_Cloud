"""Downloads: CSV, and an RO-Crate 1.1 bundle in the shape DATA_INTEGRATION_SPEC.md §3.4 proposes
(samples.csv, events.csv, calibration.json, metadata.json + ro-crate-metadata.json, SHA-256 per file).

Labels travel with the data: every CSV row has a provenance column, a simulated export's filename ends in
_SIMULATED, and the bundle says "GeneLab-aligned (unconfirmed)" until a GeneLab curator confirms the mapping.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from cose_cloud import __version__

GENELAB_LABEL = "GeneLab-aligned (unconfirmed)"
CSV_COLUMNS = ("ts_utc", "device_uuid", "metric", "label", "unit", "value", "n_readings", "provenance")


def filename(dataset: dict, ext: str) -> str:
    q = dataset["query"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    sim = "_SIMULATED" if "simulated" in dataset["provenance"] else ""
    return f"cose_{q['device_uuid']}_{stamp}{sim}.{ext}"


def samples_csv(dataset: dict) -> bytes:
    q = dataset["query"]
    reg = {m["key"]: m for m in q["registry"]}
    prov = ";".join(dataset["provenance"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for p in dataset["rows"]:
        m = reg.get(p["metric"], {"label": p["metric"], "unit": ""})
        w.writerow([p["ts"], q["device_uuid"], p["metric"], m["label"], m["unit"],
                    "" if p["value"] is None else p["value"], p.get("n", ""), prov])
    return buf.getvalue().encode()


def events_csv(events: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(("ts_utc", "alert", "event"))
    for e in events:
        w.writerow((e["ts"].isoformat() if hasattr(e["ts"], "isoformat") else e["ts"], e["alert"], e["event"]))
    return buf.getvalue().encode()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def rocrate_zip(dataset: dict, *, device: dict, experiment: dict | None, events: list[dict]) -> bytes:
    q = dataset["query"]
    files: dict[str, bytes] = {
        "samples.csv": samples_csv(dataset),
        "events.csv": events_csv(events),
        "calibration.json": json.dumps({
            "device_uuid": q["device_uuid"], "calibration_ids": device.get("calibration_ids") or [],
            "note": ("simulated device: there is no physical calibration" if device["data_origin"] == "simulator"
                     else "calibration records are not yet linked in CoSE Cloud M1")}, indent=1).encode(),
        "metadata.json": json.dumps({
            "generator": f"CoSE Cloud {__version__}", "generated_at": datetime.now(timezone.utc).isoformat(),
            "provenance": dataset["provenance"], "provenance_note": q.get("provenance_note"),
            "osdr_mapping": GENELAB_LABEL,
            "device": {k: device.get(k) for k in ("device_uuid", "product", "variant", "label", "data_origin",
                                                  "sim_meta", "fitted_sensors", "site", "timezone")},
            "experiment": experiment, "window": q.get("window"), "window_utc": q.get("window_utc"),
            "bucket_s": q.get("bucket_s"), "metrics": q["registry"]}, indent=1, default=str).encode(),
    }
    descriptions = {"samples.csv": "Time series (bucketed means), one row per metric and bucket",
                    "events.csv": "Device alerts raised and cleared in the window",
                    "calibration.json": "Calibration records for the device",
                    "metadata.json": "Device, experiment, metric registry and provenance"}
    graph: list[dict[str, Any]] = [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
         "about": {"@id": "./"}},
        {"@id": "./", "@type": "Dataset",
         "name": f"CoSE {q['product']} data: {q.get('device_label') or q['device_uuid']} ({q.get('window')})",
         "description": " ".join(x for x in [
             f"Exported from CoSE Cloud {__version__}.", f"Provenance: {', '.join(dataset['provenance'])}.",
             q.get("provenance_note") or "", f"OSDR mapping: {GENELAB_LABEL}."] if x),
         "datePublished": datetime.now(timezone.utc).date().isoformat(),
         "license": {"@id": "https://creativecommons.org/licenses/by/4.0/"},
         "hasPart": [{"@id": n} for n in files]},
    ]
    graph += [{"@id": n, "@type": "File", "name": n, "description": descriptions[n],
               "encodingFormat": "text/csv" if n.endswith(".csv") else "application/json",
               "contentSize": str(len(b)), "sha256": _sha(b)} for n, b in files.items()]
    files["ro-crate-metadata.json"] = json.dumps({"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph},
                                                 indent=1).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()
