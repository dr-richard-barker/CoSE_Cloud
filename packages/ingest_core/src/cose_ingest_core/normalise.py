"""normalise(topic, payload, received_at, device) -> Accepted | Rejected. Pure: no I/O, no clock, never raises.

Rules (docs/DATA_MODEL.md has the reasoning):

- Device identity comes from the topic, which the broker ties to the client certificate. A device id inside the
  payload is kept as `payload_device_id` and never trusted (the simulator's says `sim-xseed-0`). An envelope whose
  `device_uuid` disagrees with its topic is rejected.
- Unknown devices are rejected: there is no auto-registration.
- Provenance comes from the device registry (`data_origin`), never from the payload: hardware -> measured,
  simulator -> simulated, replay -> replay.
- Three telemetry shapes are accepted: the envelope (proposal v0.1), the XSeed firmware payload, and the
  Care-Agent contract v0.2 payload (firmware payload + seq/mode/active_overrides, what the simulator sends; the
  firmware schema rejects it because of `additionalProperties: false`).
- A JSON null becomes a reading with the metric's null meaning as its quality; an omitted field becomes no row.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files
from typing import Any, Optional, Union

from jsonschema import Draft202012Validator

from cose_ingest_core.metrics import BY_SCHEMA, XSEED, Metric

MAX_PAYLOAD_BYTES = 128 * 1024          # AWS IoT Core's message size limit; the same cap on Mosquitto keeps us portable
MAX_CLOCK_AHEAD = timedelta(days=1)     # a device clock this far ahead of the cloud is wrong, not early
EARLIEST = datetime(2000, 1, 1, tzinfo=timezone.utc)
PROVENANCE = {"hardware": "measured", "simulator": "simulated", "replay": "replay"}
INGEST_PATHS = ("live", "backfill", "replay")

_TOPIC = re.compile(r"cose/v1/devices/([A-Za-z0-9._-]{1,64})/([a-z][a-z0-9_]*(?:/[a-z0-9_]+)?)")
CLOUD_TO_DEVICE = ("commands", "ota")   # never ingested: the cloud does not read what it would send
CONTRACT_KEYS = ("seq", "mode", "active_overrides")


@dataclass(frozen=True)
class DeviceRecord:
    device_uuid: str
    product: str
    data_origin: str      # hardware | simulator | replay


@dataclass(frozen=True)
class Message:
    device_uuid: str
    leaf: str
    ts: datetime
    received_at: datetime
    seq: Optional[int]
    shape: str            # envelope | xseed_fw | xseed_contract | raw
    schema_uri: Optional[str]
    provenance: str
    experiment_id: Optional[str]
    payload_device_id: Optional[str]
    mode: Optional[str]
    ingest_path: str
    body: dict
    sha256: str


@dataclass(frozen=True)
class Reading:
    metric: str
    ts: datetime
    value: Optional[float]
    quality: str          # ok | read_failed | not_valid


@dataclass(frozen=True)
class Accepted:
    message: Message
    readings: tuple[Reading, ...]


@dataclass(frozen=True)
class Rejected:
    reason: str           # short code, stored in ingest_rejects
    detail: str = ""


Result = Union[Accepted, Rejected]


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    schema = json.loads(files("cose_ingest_core").joinpath("schemas", name).read_text())
    return Draft202012Validator(schema)


ENVELOPE = "envelope-v0.1.schema.json"
XSEED_FW = "xseed-telemetry-v1.schema.json"
XSEED_CONTRACT = "careagent-contract-telemetry-v0.2.schema.json"


def parse_topic(topic: str) -> Optional[tuple[str, str]]:
    m = _TOPIC.fullmatch(topic)
    return (m.group(1), m.group(2)) if m else None


def _first_error(v: Draft202012Validator, obj: Any) -> Optional[str]:
    err = next(iter(sorted(v.iter_errors(obj), key=lambda e: list(e.absolute_path))), None)
    if err is None:
        return None
    where = "/".join(str(p) for p in err.absolute_path) or "(root)"
    return f"{where}: {err.message[:200]}"


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def _get(obj: Any, path: tuple[str, ...]) -> tuple[bool, Any]:
    for part in path:
        if not isinstance(obj, dict) or part not in obj:
            return False, None
        obj = obj[part]
    return True, obj


def extract(metrics: tuple[Metric, ...], body: dict, ts: datetime) -> tuple[Reading, ...]:
    out = []
    for m in metrics:
        present, value = _get(body, m.path())
        if not present:
            continue
        if value is None:
            out.append(Reading(m.key, ts, None, m.null_meaning))
        elif isinstance(value, bool):
            out.append(Reading(m.key, ts, 1.0 if value else 0.0, "ok"))
        elif isinstance(value, (int, float)):
            out.append(Reading(m.key, ts, float(value), "ok"))
        elif isinstance(value, str) and m.enum is not None and value in m.enum:
            out.append(Reading(m.key, ts, float(m.enum[value]), "ok"))
    return tuple(out)


def normalise(topic: str, payload: bytes, received_at: datetime, device: Optional[DeviceRecord],
              ingest_path: str = "live") -> Result:
    if ingest_path not in INGEST_PATHS:
        return Rejected("bad_ingest_path", ingest_path)
    if received_at.tzinfo is None:
        return Rejected("naive_received_at")
    parsed = parse_topic(topic)
    if parsed is None:
        return Rejected("bad_topic", topic[:200])
    uuid, leaf = parsed
    if leaf.split("/")[0] in CLOUD_TO_DEVICE:
        return Rejected("cloud_to_device_leaf", leaf)
    if device is None:
        return Rejected("unknown_device", uuid)
    if device.device_uuid != uuid:
        return Rejected("registry_mismatch", f"{device.device_uuid} != {uuid}")
    provenance = PROVENANCE.get(device.data_origin)
    if provenance is None:
        return Rejected("bad_data_origin", device.data_origin)
    if len(payload) > MAX_PAYLOAD_BYTES:
        return Rejected("too_large", str(len(payload)))
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return Rejected("not_utf8")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return Rejected("bad_json", str(e)[:200])
    if not isinstance(obj, dict):
        return Rejected("not_object")

    digest = hashlib.sha256(payload).hexdigest()
    readings: tuple[Reading, ...] = ()
    seq = mode = experiment_id = payload_device_id = schema_uri = None

    if "schema" in obj and "body" in obj:
        shape = "envelope"
        err = _first_error(validator(ENVELOPE), obj)
        if err:
            return Rejected("envelope_invalid", err)
        if obj["device_uuid"] != uuid:
            return Rejected("uuid_mismatch", f"envelope {obj['device_uuid']} on topic {uuid}")
        ts = _parse_iso(obj["ts"])
        if ts is None:
            return Rejected("bad_ts", str(obj["ts"])[:64])
        schema_uri, seq, mode = obj["schema"], obj["seq"], obj.get("mode")
        experiment_id = obj.get("experiment_id")
        metrics = BY_SCHEMA.get(schema_uri)
        if metrics is XSEED:
            if device.product != "xseed":
                return Rejected("shape_product_mismatch", f"xseed body from a {device.product}")
            err = _first_error(validator(XSEED_FW), obj["body"])
            if err:
                return Rejected("body_invalid", err)
            payload_device_id = obj["body"].get("device_id")
        if metrics:
            readings = extract(metrics, obj["body"], ts)
    elif {"device_id", "timestamp", "sensors"} <= obj.keys():
        if device.product != "xseed":
            return Rejected("shape_product_mismatch", f"xseed payload from a {device.product}")
        contract = any(k in obj for k in CONTRACT_KEYS)
        shape = "xseed_contract" if contract else "xseed_fw"
        err = _first_error(validator(XSEED_CONTRACT if contract else XSEED_FW), obj)
        if err:
            return Rejected("payload_invalid", err)
        ts = datetime.fromtimestamp(obj["timestamp"], timezone.utc)
        seq, mode = obj.get("seq"), obj.get("mode")
        payload_device_id = obj["device_id"]
        schema_uri = validator(XSEED_CONTRACT if contract else XSEED_FW).schema["$id"]
        readings = extract(XSEED, obj, ts)
    elif leaf == "telemetry":
        return Rejected("unknown_shape", ",".join(sorted(obj)[:12]))
    else:
        shape, ts = "raw", received_at   # state / alerts / acks without an envelope: stored, no readings

    if ts < EARLIEST:
        return Rejected("ts_too_old", ts.isoformat())
    if ts - received_at > MAX_CLOCK_AHEAD:
        return Rejected("clock_ahead", f"{ts.isoformat()} vs received {received_at.isoformat()}")

    msg = Message(device_uuid=uuid, leaf=leaf, ts=ts, received_at=received_at, seq=seq, shape=shape,
                  schema_uri=schema_uri, provenance=provenance, experiment_id=experiment_id,
                  payload_device_id=payload_device_id, mode=mode, ingest_path=ingest_path, body=obj, sha256=digest)
    return Accepted(msg, readings)
