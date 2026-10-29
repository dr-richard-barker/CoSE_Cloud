"""The ingest service: subscribe to every device's reporting leaves, normalise, store.

    cose-cloud-ingest            (settings from COSE_* environment variables)

It connects with the read-only `cose-cloud-ingest` certificate: the broker's access rules let it read device
reports and nothing else, so no CoSE Cloud process can publish a command (deploy/compose/mosquitto/acl).
"""

from __future__ import annotations

import logging
import signal
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt
import psycopg

from cose_cloud import store
from cose_cloud.config import Settings, settings
from cose_cloud.db import connect
from cose_ingest_core import DeviceRecord, normalise

log = logging.getLogger("cose_cloud.ingest")
CLIENT_ID = "cose-cloud-ingest"
LEAVES = ("telemetry", "state", "alerts", "acks")
QOS = 1
REGISTRY_TTL_S = 30.0


class Ingest:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.conn: Optional[psycopg.Connection] = None
        self._registry: dict[str, tuple[float, Optional[DeviceRecord]]] = {}
        self.stored = self.duplicates = self.rejected = 0

    def db(self) -> psycopg.Connection:
        if self.conn is None or self.conn.closed:
            self.conn = connect(self.cfg.database_url)
        return self.conn

    def device(self, uuid: str) -> Optional[DeviceRecord]:
        hit = self._registry.get(uuid)
        if hit and time.monotonic() - hit[0] < REGISTRY_TTL_S:
            return hit[1]
        rec = store.device_record(self.db(), uuid)
        self.db().commit()
        self._registry[uuid] = (time.monotonic(), rec)
        return rec

    def handle(self, topic: str, payload: bytes, received_at: Optional[datetime] = None) -> None:
        received_at = received_at or datetime.now(timezone.utc)
        for attempt in (1, 2):
            try:
                uuid = topic.split("/")[3] if topic.count("/") >= 4 else ""
                result = normalise(topic, payload, received_at, self.device(uuid) if uuid else None)
                conn = self.db()
                with conn.transaction():
                    mid = store.write(conn, result, topic, payload)
                if mid is not None:
                    self.stored += 1
                elif hasattr(result, "reason"):
                    self.rejected += 1
                    log.warning("rejected %s: %s %s", topic, result.reason, result.detail)
                else:
                    self.duplicates += 1
                return
            except psycopg.OperationalError as e:
                log.error("database error (attempt %d): %s", attempt, e)
                self.conn = None
                time.sleep(1.0)
        log.error("dropped a message on %s after two database errors", topic)


def _tls(cfg: Settings) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(cfg.mqtt_ca))
    ctx.load_cert_chain(str(cfg.mqtt_cert), str(cfg.mqtt_key))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def run(cfg: Settings, stop: threading.Event) -> Ingest:
    ing = Ingest(cfg)
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, clean_session=False)
    c.tls_set_context(_tls(cfg))

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("broker refused the connection: %s", reason_code)
            return
        client.subscribe([(f"cose/v1/devices/+/{leaf}", QOS) for leaf in LEAVES])
        log.info("connected to %s:%d, subscribed to %s", cfg.mqtt_host, cfg.mqtt_port, ", ".join(LEAVES))

    c.on_connect = on_connect
    c.on_message = lambda client, userdata, msg: ing.handle(msg.topic, msg.payload)
    c.reconnect_delay_set(min_delay=1, max_delay=30)
    c.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=30)
    c.loop_start()
    last = time.monotonic()
    while not stop.wait(1.0):
        if time.monotonic() - last >= 300:
            log.info("stored %d, duplicates %d, rejected %d", ing.stored, ing.duplicates, ing.rejected)
            last = time.monotonic()
    c.loop_stop()
    c.disconnect()
    return ing


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(settings(), stop)


if __name__ == "__main__":
    main()
