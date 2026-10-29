"""Storage, the labelling trigger, org isolation, time windows and statistics."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
import pytest

from cose_cloud import queries
from cose_cloud.db import migrate

from conftest import add_device, ingest, series_payloads

pytestmark = pytest.mark.db


def test_migrations_are_idempotent(conn):
    assert migrate(conn) == []


def test_write_stores_message_and_readings_once(conn, make_org, contract_payload):
    org = make_org()
    add_device(conn, org, f"xs-{org['n']}")
    uuid = f"xs-{org['n']}"
    mid = ingest(conn, uuid, contract_payload)
    assert mid is not None
    assert ingest(conn, uuid, contract_payload) is None          # QoS 1 redelivery: same bytes, stored once
    n_msg = conn.execute("select count(*) n from messages where device_uuid = %s", (uuid,)).fetchone()["n"]
    n_read = conn.execute("select count(*) n from readings where device_uuid = %s", (uuid,)).fetchone()["n"]
    assert (n_msg, n_read) == (1, 24)
    row = conn.execute("select provenance, payload_device_id, shape from messages where id = %s", (mid,)).fetchone()
    assert row == {"provenance": "simulated", "payload_device_id": "sim-xseed-0", "shape": "xseed_contract"}
    dev = conn.execute("select first_seen, last_seen from devices where device_uuid = %s", (uuid,)).fetchone()
    assert dev["first_seen"] == dev["last_seen"] == datetime.fromtimestamp(contract_payload["timestamp"], timezone.utc)


def test_rejects_are_recorded(conn, make_org):
    from cose_cloud import store
    from cose_ingest_core import normalise
    topic = "cose/v1/devices/nobody-0001/telemetry"
    with conn.transaction():
        assert store.write(conn, normalise(topic, b"{}", datetime.now(timezone.utc), None), topic, b"{}") is None
    row = conn.execute("select reason, payload_bytes from ingest_rejects where topic = %s", (topic,)).fetchone()
    assert row == {"reason": "unknown_device", "payload_bytes": 2}


def test_trigger_keeps_simulated_data_labelled(conn, make_org, contract_payload):
    org = make_org()
    uuid = f"xs-{org['n']}"
    add_device(conn, org, uuid)
    mid = ingest(conn, uuid, contract_payload)
    with pytest.raises(psycopg.errors.RaiseException, match="does not match device"):
        with conn.transaction():
            conn.execute("insert into readings (device_uuid, metric, ts, value, quality, provenance, message_id) "
                         "values (%s, 'sensors.dome_temp_c', now(), 20, 'ok', 'measured', %s)", (uuid, mid))
    with pytest.raises(psycopg.errors.RaiseException):
        with conn.transaction():
            conn.execute("update readings set provenance = 'measured' where device_uuid = %s", (uuid,))


def test_value_and_quality_agree(conn, make_org, contract_payload):
    org = make_org()
    uuid = f"xs-{org['n']}"
    add_device(conn, org, uuid)
    mid = ingest(conn, uuid, contract_payload)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("insert into readings (device_uuid, metric, ts, value, quality, provenance, message_id) "
                         "values (%s, 'x', now(), null, 'ok', 'simulated', %s)", (uuid, mid))


def test_org_isolation(conn, make_org, contract_payload):
    a, b = make_org(), make_org()
    uuid = f"xs-{a['n']}"
    add_device(conn, a, uuid)
    ingest(conn, uuid, contract_payload)
    assert [d["device_uuid"] for d in queries.list_devices(conn, a["id"])] == [uuid]
    assert queries.list_devices(conn, b["id"]) == []
    for call in (lambda: queries.device(conn, b["id"], uuid), lambda: queries.latest(conn, b["id"], uuid),
                 lambda: queries.alerts(conn, b["id"], uuid, datetime(2000, 1, 1, tzinfo=timezone.utc),
                                        datetime.now(timezone.utc))):
        with pytest.raises(queries.NotFound):
            call()


@pytest.mark.parametrize("day, hours", [("2026-11-01", 25), ("2026-03-08", 23), ("2026-10-20", 24)])
def test_local_days_follow_daylight_saving(day, hours):
    start, end, label = queries.day_window(day, "America/Chicago")
    assert (end - start) == timedelta(hours=hours)
    assert start.astimezone(ZoneInfo("America/Chicago")).hour == 0 and label.startswith(day)


def test_yesterday_is_the_local_day():
    now = datetime(2026, 11, 2, 3, 30, tzinfo=timezone.utc)      # 21:30 on 1 Nov in Chicago (CST)
    start, end, _ = queries.day_window("yesterday", "America/Chicago", now)
    assert start == datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)   # 31 Oct 00:00 CDT
    assert end == datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)


def test_stats_match_a_hand_computed_fixture(conn, make_org, contract_payload):
    org = make_org()
    uuid = f"xs-{org['n']}"
    add_device(conn, org, uuid)
    start = datetime(2026, 9, 1, 5, 0, tzinfo=timezone.utc)      # 00:00 CDT
    values = [20.0, 21.5, 19.0, 22.25, 20.5]
    for p in series_payloads(contract_payload, start, values):
        ingest(conn, uuid, p)
    failed = series_payloads(contract_payload, start + timedelta(minutes=5), [0.0])[0]
    failed["sensors"]["dome_temp_c"] = None
    ingest(conn, uuid, failed)
    s, e, _ = queries.day_window("2026-09-01", "America/Chicago")
    st = queries.stats(conn, org["id"], uuid, "sensors.dome_temp_c", s, e)
    assert st["n"] == 5 and st["read_failed"] == 1 and st["not_valid"] == 0
    assert st["mean"] == pytest.approx(statistics.mean(values))
    assert st["sd"] == pytest.approx(statistics.stdev(values), abs=1e-4)
    assert (st["min"], st["max"]) == (19.0, 22.25)
    assert st["median_interval_s"] == 60 and st["provenance"] == "simulated"
    with pytest.raises(queries.BadRequest):
        queries.stats(conn, org["id"], uuid, "sensors.not_a_metric", s, e)


def test_series_buckets_and_limits(conn, make_org, contract_payload):
    org = make_org()
    uuid = f"xs-{org['n']}"
    add_device(conn, org, uuid)
    start = datetime(2026, 9, 2, 5, 0, tzinfo=timezone.utc)
    for p in series_payloads(contract_payload, start, [10.0, 20.0, 30.0, 40.0]):
        ingest(conn, uuid, p)
    out = queries.series(conn, org["id"], uuid, ["sensors.dome_temp_c"], start, start + timedelta(minutes=4), 120)
    assert [p["value"] for p in out["points"]] == [15.0, 35.0]
    with pytest.raises(queries.BadRequest):
        queries.window("2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z", None, "America/Chicago")


def test_alert_transitions(conn, make_org, contract_payload):
    org = make_org()
    uuid = f"xs-{org['n']}"
    add_device(conn, org, uuid)
    start = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)
    ps = series_payloads(contract_payload, start, [20.0, 20.0, 20.0])
    ps[0]["alerts"], ps[1]["alerts"], ps[2]["alerts"] = [], ["water_low"], []
    for p in ps:
        ingest(conn, uuid, p)
    ev = queries.alerts(conn, org["id"], uuid, start, start + timedelta(minutes=5))
    assert [(e["alert"], e["event"]) for e in ev] == [("water_low", "raised"), ("water_low", "cleared")]
