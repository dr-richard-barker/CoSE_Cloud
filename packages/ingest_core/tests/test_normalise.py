"""normalise(): shapes, identity, provenance, null vs omitted, and every rejection path."""

from __future__ import annotations

import base64
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cose_ingest_core import XSEED, XSEED_SCHEMA_ID, Accepted, DeviceRecord, Rejected, normalise, parse_topic
from cose_ingest_core.aws import BadEvent, event_to_args
from cose_ingest_core.normalise import XSEED_FW, extract, validator

FIX = Path(__file__).parent / "fixtures"
CONTRACT = json.loads((FIX / "xseed_contract_h72.json").read_text())   # what the simulator publishes
UUID = "xseed-sim-0001"
TOPIC = f"cose/v1/devices/{UUID}/telemetry"
SIM = DeviceRecord(UUID, "xseed", "simulator")
NOW = datetime.fromtimestamp(CONTRACT["timestamp"] + 2, timezone.utc)
ENV_TS = "2026-09-24T14:05:00.000Z"   # before NOW


def b(obj) -> bytes:
    return json.dumps(obj).encode()


def firmware_payload() -> dict:
    fw = copy.deepcopy(CONTRACT)
    for k in ("seq", "mode", "active_overrides"):
        fw.pop(k)
    return fw


def envelope(body: dict, uuid: str = UUID) -> dict:
    return {"schema": XSEED_SCHEMA_ID, "device_uuid": uuid, "product": "xseed", "fw": body["firmware_version"],
            "seq": 7, "ts": ENV_TS, "mode": "recipe", "experiment_id": "exp-1", "body": body}


def accept(topic=TOPIC, payload=None, device=SIM, **kw) -> Accepted:
    r = normalise(topic, payload if payload is not None else b(CONTRACT), NOW, device, **kw)
    assert isinstance(r, Accepted), r
    return r


def reject(topic=TOPIC, payload=None, device=SIM, now=NOW) -> Rejected:
    r = normalise(topic, payload if payload is not None else b(CONTRACT), now, device)
    assert isinstance(r, Rejected), r
    return r


def test_contract_shape_from_the_simulator():
    r = accept()
    m = r.message
    assert m.shape == "xseed_contract" and m.seq == CONTRACT["seq"] and m.mode == "RUN"
    assert m.ts == datetime.fromtimestamp(CONTRACT["timestamp"], timezone.utc)
    assert m.schema_uri == "cose-care-agent/contract/telemetry.schema.json"
    assert {x.metric for x in r.readings} == {mt.key for mt in XSEED}
    temp = next(x for x in r.readings if x.metric == "sensors.dome_temp_c")
    assert temp.value == CONTRACT["sensors"]["dome_temp_c"] and temp.quality == "ok"


def test_firmware_shape():
    r = accept(payload=b(firmware_payload()))
    assert r.message.shape == "xseed_fw" and r.message.seq is None
    assert r.message.schema_uri == XSEED_SCHEMA_ID


def test_firmware_schema_rejects_the_contract_payload():
    # additionalProperties: false at the top level: why the contract schema is needed for the simulator
    assert list(validator(XSEED_FW).iter_errors(CONTRACT))


def test_envelope_shape():
    r = accept(payload=b(envelope(firmware_payload())))
    m = r.message
    assert m.shape == "envelope" and m.seq == 7 and m.experiment_id == "exp-1" and m.mode == "recipe"
    assert m.ts == datetime(2026, 9, 24, 14, 5, tzinfo=timezone.utc)
    assert len(r.readings) == len(XSEED)


def test_envelope_body_must_be_a_valid_xseed_payload():
    assert reject(payload=b(envelope(CONTRACT))).reason == "body_invalid"


def test_topic_uuid_wins_over_payload_device_id():
    assert CONTRACT["device_id"] == "sim-xseed-0"
    m = accept().message
    assert m.device_uuid == UUID and m.payload_device_id == "sim-xseed-0"


def test_envelope_uuid_must_match_topic():
    assert reject(payload=b(envelope(firmware_payload(), uuid="someone-else-01"))).reason == "uuid_mismatch"


@pytest.mark.parametrize("origin, provenance", [("hardware", "measured"), ("simulator", "simulated"),
                                                ("replay", "replay")])
def test_provenance_comes_from_the_registry(origin, provenance):
    r = accept(device=DeviceRecord(UUID, "xseed", origin))
    assert r.message.provenance == provenance


def test_null_is_a_failed_read_and_omitted_is_no_row():
    p = copy.deepcopy(CONTRACT)
    p["sensors"]["dome_temp_c"] = None
    p["biometrics_3d"]["canopy_height_avg_mm"] = None
    r = accept(payload=b(p))
    by = {x.metric: x for x in r.readings}
    assert by["sensors.dome_temp_c"].value is None and by["sensors.dome_temp_c"].quality == "read_failed"
    assert by["biometrics_3d.canopy_height_avg_mm"].quality == "not_valid"
    body = copy.deepcopy(firmware_payload())
    del body["sensors"]["vpd_kpa"]           # schemas require it, so test the extractor directly
    rows = extract(XSEED, body, NOW)
    assert "sensors.vpd_kpa" not in {x.metric for x in rows}


def test_flags_and_enums_become_numbers():
    by = {x.metric: x.value for x in accept().readings}
    assert by["sensors.water_level_ok"] in (0.0, 1.0)
    assert by["actuators.pump_state"] == (1.0 if CONTRACT["actuators"]["pump_state"] == "FLOOD" else 0.0)


def test_same_bytes_same_digest():
    assert accept().message.sha256 == accept().message.sha256


@pytest.mark.parametrize("topic", [
    "cose/v1/devices/+/telemetry", "cose/v1/devices/#", f"cose/v1/devices/{UUID}/telemetry/x/y",
    f"cose/v2/devices/{UUID}/telemetry", f"cose/v1/devices/{UUID}/", "cose/v1/devices/bad id/telemetry",
])
def test_bad_topics(topic):
    assert reject(topic=topic).reason == "bad_topic"


@pytest.mark.parametrize("leaf", ["commands", "ota"])
def test_cloud_to_device_leaves_are_never_ingested(leaf):
    assert reject(topic=f"cose/v1/devices/{UUID}/{leaf}").reason == "cloud_to_device_leaf"


def test_unknown_device():
    assert reject(device=None).reason == "unknown_device"


def test_registry_mismatch():
    assert reject(device=DeviceRecord("other-0001", "xseed", "simulator")).reason == "registry_mismatch"


def test_xseed_payload_from_another_product():
    assert reject(device=DeviceRecord(UUID, "drone", "hardware")).reason == "shape_product_mismatch"


@pytest.mark.parametrize("payload, reason", [
    (b"\xff\xfe\x00", "not_utf8"), (b"{not json", "bad_json"), (b"[1, 2]", "not_object"),
    (b'{"hello": 1}', "unknown_shape"), (b"x" * (128 * 1024 + 1), "too_large"),
])
def test_malformed_payloads(payload, reason):
    assert reject(payload=payload).reason == reason


def test_invalid_payload_names_the_field():
    p = copy.deepcopy(CONTRACT)
    p["sensors"]["dome_temp_c"] = "warm"
    r = reject(payload=b(p))
    assert r.reason == "payload_invalid" and "sensors/dome_temp_c" in r.detail


def test_device_clock_far_ahead_is_rejected():
    assert reject(now=NOW - timedelta(days=2)).reason == "clock_ahead"


def test_state_without_envelope_is_stored_raw():
    r = accept(topic=f"cose/v1/devices/{UUID}/state", payload=b'{"recipe": "broccoli"}')
    assert r.message.shape == "raw" and r.message.ts == NOW and r.readings == ()


def test_parse_topic():
    assert parse_topic(f"cose/v1/devices/{UUID}/link/cmbs") == (UUID, "link/cmbs")


def test_lambda_event_gives_the_same_result_as_the_mqtt_path():
    raw = b(CONTRACT)
    event = {"topic": TOPIC, "payload_b64": base64.b64encode(raw).decode(), "received_ms": int(NOW.timestamp() * 1000)}
    topic, payload, received_at = event_to_args(event)
    assert (topic, payload, received_at) == (TOPIC, raw, NOW)
    assert normalise(topic, payload, received_at, SIM) == normalise(TOPIC, raw, NOW, SIM)


@pytest.mark.parametrize("event", [{}, {"topic": TOPIC, "payload_b64": "!!", "received_ms": 1},
                                   {"topic": 5, "payload_b64": "", "received_ms": 1}])
def test_bad_lambda_events(event):
    with pytest.raises(BadEvent):
        event_to_args(event)
