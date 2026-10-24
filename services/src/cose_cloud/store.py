"""Writes: the device registry, metric rows, and ingest results. Reads that the API serves live in queries.py."""

from __future__ import annotations

import json
from typing import Optional

import psycopg
from psycopg.types.json import Jsonb

from cose_ingest_core import BY_PRODUCT, Accepted, DeviceRecord, Rejected

RESERVED_UUIDS = ("cose-cloud-ingest", "cose-care-agent-host")
PRODUCTS = ("xseed", "ground-rover", "drone", "sense", "soilsense", "algaflux", "cmbs", "magbio", "scispinner")


def device_record(conn: psycopg.Connection, device_uuid: str) -> Optional[DeviceRecord]:
    row = conn.execute("select device_uuid, product, data_origin from devices where device_uuid = %s",
                       (device_uuid,)).fetchone()
    return DeviceRecord(**row) if row else None


def seed_metrics(conn: psycopg.Connection) -> int:
    n = 0
    for product, metrics in BY_PRODUCT.items():
        for m in metrics:
            conn.execute(
                "insert into metrics (product, key, label, unit, kind, null_meaning) values (%s,%s,%s,%s,%s,%s) "
                "on conflict (product, key) do update set label = excluded.label, unit = excluded.unit, "
                "kind = excluded.kind, null_meaning = excluded.null_meaning",
                (product, m.key, m.label, m.unit, m.kind, m.null_meaning))
            n += 1
    return n


def register_device(conn: psycopg.Connection, *, device_uuid: str, org_id: int, product: str, data_origin: str,
                    site_id: Optional[int] = None, label: Optional[str] = None, variant: Optional[str] = None,
                    sim_meta: Optional[dict] = None, fitted_sensors: Optional[list[str]] = None) -> None:
    if product not in PRODUCTS:
        raise ValueError(f"unknown product {product!r}; known: {', '.join(PRODUCTS)}")
    if device_uuid in RESERVED_UUIDS:
        raise ValueError(f"{device_uuid!r} is a broker user name; the ACL's per-device patterns would apply to it")
    conn.execute(
        "insert into devices (device_uuid, org_id, site_id, product, variant, label, data_origin, sim_meta, "
        "fitted_sensors) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (device_uuid) do update set "
        "site_id = excluded.site_id, label = excluded.label, variant = excluded.variant, sim_meta = excluded.sim_meta, "
        "fitted_sensors = excluded.fitted_sensors",
        (device_uuid, org_id, site_id, product, variant, label, data_origin,
         Jsonb(sim_meta) if sim_meta is not None else None, fitted_sensors))


def write(conn: psycopg.Connection, result: Accepted | Rejected, topic: str, payload: bytes) -> Optional[int]:
    """Store one normalise() result. Returns the message id, or None for a duplicate or a reject.
    Runs inside the caller's transaction."""
    if isinstance(result, Rejected):
        excerpt = payload[:512].decode("utf-8", "replace")
        conn.execute("insert into ingest_rejects (topic, reason, detail, payload_bytes, payload_excerpt) "
                     "values (%s,%s,%s,%s,%s)", (topic[:512], result.reason, result.detail, len(payload), excerpt))
        return None
    m = result.message
    row = conn.execute(
        "insert into messages (device_uuid, leaf, ts, received_at, seq, shape, schema_uri, provenance, experiment_id, "
        "payload_device_id, mode, ingest_path, body, sha256) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "on conflict (device_uuid, leaf, sha256) do nothing returning id",
        (m.device_uuid, m.leaf, m.ts, m.received_at, m.seq, m.shape, m.schema_uri, m.provenance, m.experiment_id,
         m.payload_device_id, m.mode, m.ingest_path, Jsonb(m.body), m.sha256)).fetchone()
    if row is None:
        return None
    mid = row["id"]
    if result.readings:
        with conn.cursor() as cur:
            cur.executemany(
                "insert into readings (device_uuid, metric, ts, value, quality, provenance, message_id) "
                "values (%s,%s,%s,%s,%s,%s,%s) on conflict (device_uuid, metric, ts) do nothing",
                [(m.device_uuid, r.metric, r.ts, r.value, r.quality, m.provenance, mid) for r in result.readings])
    conn.execute("update devices set first_seen = least(coalesce(first_seen, %s), %s), "
                 "last_seen = greatest(coalesce(last_seen, %s), %s) where device_uuid = %s",
                 (m.ts, m.ts, m.ts, m.ts, m.device_uuid))
    return mid


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)
