"""AWS IoT Core rule -> Lambda -> the same normalise() and store as the Mosquitto path. Not deployed in M1.

The rule (docs/AWS_PORTABILITY.md, to verify when M7 is built):
    SELECT encode(*, 'base64') AS payload_b64, topic() AS topic, timestamp() AS received_ms
    FROM 'cose/v1/devices/+/+'
Environment: COSE_DATABASE_URL (RDS Postgres with the same migrations). One connection per warm container.
"""

from __future__ import annotations

from cose_cloud import store
from cose_cloud.config import settings
from cose_cloud.db import connect
from cose_ingest_core import normalise, parse_topic
from cose_ingest_core.aws import BadEvent, event_to_args

_conn = None


def handler(event: dict, context=None) -> dict:
    global _conn
    try:
        topic, payload, received_at = event_to_args(event)
    except BadEvent as e:
        return {"stored": False, "reason": f"bad_event: {e}"}
    if _conn is None or _conn.closed:
        _conn = connect(settings().database_url)
    parsed = parse_topic(topic)
    device = store.device_record(_conn, parsed[0]) if parsed else None
    result = normalise(topic, payload, received_at, device)
    with _conn.transaction():
        mid = store.write(_conn, result, topic, payload)
    return {"stored": mid is not None, "reason": getattr(result, "reason", None)}
