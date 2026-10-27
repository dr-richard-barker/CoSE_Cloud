"""The HTTP API: sign-in, org isolation, data routes, exports, and the agent routes."""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from cose_care_agent.agent.providers.base import LLMResult, Usage
from fastapi.testclient import TestClient

from cose_cloud import auth
from cose_cloud.agent import tools

from conftest import PASSWORD, add_device, ingest, series_payloads

pytestmark = pytest.mark.db


@pytest.fixture
def client(db_url):
    from cose_cloud import api
    with TestClient(api.app) as c:
        yield c


def signed_in(client, org) -> TestClient:
    r = client.post("/api/auth/login", json={"email": org["email"], "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def data(conn, make_org, contract_payload):
    org = make_org()
    uuid = f"xs-{org['n']}"
    add_device(conn, org, uuid)
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)
    for p in series_payloads(contract_payload, start, [20.0, 21.0, 22.0, 23.0], step_s=600):
        p["alerts"] = []
        ingest(conn, uuid, p)
    return {"org": org, "uuid": uuid}


def test_sign_in_required(client):
    assert client.get("/api/devices").status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.org", "password": "x" * 12}).status_code == 401


def test_wrong_password(client, make_org):
    org = make_org()
    assert client.post("/api/auth/login", json={"email": org["email"], "password": "wrong-password-1"}).status_code == 401


def test_me_and_devices(client, data):
    c = signed_in(client, data["org"])
    me = c.get("/api/me").json()
    assert me["org"]["id"] == data["org"]["id"] and me["entitlements"]["llm_mode"] == "off"
    devs = c.get("/api/devices").json()
    assert [d["device_uuid"] for d in devs] == [data["uuid"]] and devs[0]["provenance"] == "simulated"
    latest = c.get(f"/api/devices/{data['uuid']}/latest", params={"metrics": "sensors.dome_temp_c"}).json()
    assert latest["readings"][0]["value"] == 23.0


def test_another_org_gets_404(client, data, make_org):
    other = make_org()
    c = signed_in(client, other)
    assert c.get("/api/devices").json() == []
    after = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for path in (f"/api/devices/{data['uuid']}", f"/api/devices/{data['uuid']}/latest",
                 f"/api/devices/{data['uuid']}/series?metrics=sensors.dome_temp_c",
                 f"/api/devices/{data['uuid']}/chart?metrics=sensors.dome_temp_c",
                 f"/api/devices/{data['uuid']}/since?metrics=sensors.dome_temp_c&after={after}",
                 f"/api/devices/{data['uuid']}/alerts",
                 f"/api/devices/{data['uuid']}/export?metrics=sensors.dome_temp_c"):
        assert c.get(path).status_code == 404, path


def test_another_orgs_dataset_gets_404(client, data, conn, make_org):
    org = data["org"]
    ctx = tools.ToolContext(conn, org["id"], org["user_id"], None)
    start = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    out, err = tools.run(ctx, "query_timeseries", {"device_uuid": data["uuid"], "metrics": ["sensors.dome_temp_c"],
                                                   "day": None, "start": start, "end": None, "bucket_minutes": 0})
    assert not err, out
    path = f"/api/datasets/{json.loads(out)['dataset_id']}/export"
    assert signed_in(client, org).get(path).status_code == 200
    client.post("/api/auth/logout")
    assert signed_in(client, make_org()).get(path).status_code == 404


def test_a_conversation_is_visible_only_to_its_starter(client, data, conn, make_org):
    org = data["org"]
    cid = signed_in(client, org).post("/api/agent/conversations", json={"edition": "xseed"}).json()["id"]
    assert client.get(f"/api/agent/conversations/{cid}").status_code == 200
    colleague = {"email": f"colleague{org['n']}-{os.getpid()}@example.org"}
    with conn.transaction():
        auth.create_user(conn, email=colleague["email"], password=PASSWORD, org_id=org["id"], role="analyst")
    for someone_else in (colleague, make_org()):
        client.post("/api/auth/logout")
        c = signed_in(client, someone_else)
        assert c.get(f"/api/agent/conversations/{cid}").status_code == 404
        assert c.post(f"/api/agent/conversations/{cid}/ask", json={"question": "hi"}).status_code == 404


def test_the_catalog_is_per_organisation(client, conn, make_org):
    owner, other = make_org(), make_org()
    slug = f"own-{owner['n']}"
    with conn.transaction():
        src = conn.execute("insert into catalog_sources (org_id, kind, slug, title) values (%s,'ec5',%s,'Owned') "
                           "returning id", (owner["id"], slug)).fetchone()
        conn.execute("insert into catalog_items (source_id, external_id, title, species, fields) values "
                     "(%s,'e1','Owned run','Brassica oleracea','[]')", (src["id"],))
    c = signed_in(client, owner)
    assert [s["slug"] for s in c.get("/api/catalog/sources").json()] == [slug]
    assert c.get("/api/catalog/items").json()["total"] == 1
    assert c.get("/api/catalog/species").json() == [{"species": "Brassica oleracea", "n": 1}]
    client.post("/api/auth/logout")
    c = signed_in(client, other)
    assert c.get("/api/catalog/sources").json() == []
    assert c.get("/api/catalog/items").json() == {"total": 0, "items": []}
    assert c.get("/api/catalog/species").json() == []


def test_series_and_since(client, data):
    c = signed_in(client, data["org"])
    s = c.get(f"/api/devices/{data['uuid']}/series", params={"metrics": "sensors.dome_temp_c", "bucket_s": 0}).json()
    assert [p["value"] for p in s["points"]] == [20.0, 21.0, 22.0, 23.0]
    after = s["points"][1]["ts"]
    rows = c.get(f"/api/devices/{data['uuid']}/since", params={"metrics": "sensors.dome_temp_c", "after": after}).json()
    assert [r["value"] for r in rows["rows"]] == [22.0, 23.0]
    bad = c.get(f"/api/devices/{data['uuid']}/series", params={"metrics": "nope"})
    assert bad.status_code == 400


def test_dashboard_chart(client, data):
    c = signed_in(client, data["org"])
    r = c.get(f"/api/devices/{data['uuid']}/chart", params={"metrics": "sensors.dome_temp_c,sensors.vpd_kpa"}).json()
    spec = r["spec"]
    assert spec["usermeta"]["provenance"] == ["simulated"] and spec["title"]["subtitle"][0].startswith("SIMULATED")
    assert set(spec["usermeta"]["series_by_metric"]) == {"sensors.dome_temp_c", "sensors.vpd_kpa"}
    assert len(spec["vconcat"]) == 2


def test_csv_export_is_labelled(client, data):
    c = signed_in(client, data["org"])
    r = c.get(f"/api/devices/{data['uuid']}/export", params={"metrics": "sensors.dome_temp_c", "bucket_s": 0})
    assert r.status_code == 200 and "_SIMULATED.csv" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].endswith(",provenance") and all(line.endswith(",simulated") for line in lines[1:])


def test_rocrate_export(client, data):
    c = signed_in(client, data["org"])
    r = c.get(f"/api/devices/{data['uuid']}/export",
              params={"metrics": "sensors.dome_temp_c,sensors.vpd_kpa", "format": "rocrate", "bucket_s": 0})
    assert r.status_code == 200 and "_SIMULATED.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["calibration.json", "events.csv", "metadata.json", "ro-crate-metadata.json",
                                    "samples.csv"]
    crate = json.loads(z.read("ro-crate-metadata.json"))
    root = next(e for e in crate["@graph"] if e["@id"] == "./")
    assert "GeneLab-aligned (unconfirmed)" in root["description"] and "simulated" in root["description"]
    meta = json.loads(z.read("metadata.json"))
    assert meta["provenance"] == ["simulated"] and meta["device"]["data_origin"] == "simulator"


def test_editions_are_public(client):
    eds = client.get("/api/editions").json()
    assert [e["id"] for e in eds] == ["hq", "xseed", "rover", "drone", "sense"]


def test_agent_off_returns_503(client, data):
    c = signed_in(client, data["org"])
    cid = c.post("/api/agent/conversations", json={"edition": "xseed"}).json()["id"]
    st = c.get("/api/agent/status").json()
    assert st["llm_mode"] == "off" and st["available"] is False
    assert c.post(f"/api/agent/conversations/{cid}/ask", json={"question": "hi"}).status_code == 503


def test_agent_route_with_a_scripted_local_model(client, data, conn, monkeypatch):
    from cose_cloud import api

    class OneLiner:
        model = "fake-local"

        def complete(self, system, tools_, messages):
            return LLMResult([], "Hello from a local model.", [{"type": "text", "text": "Hello from a local model."}],
                             Usage(10, 5, 0, 0), "fake-local", "end_turn")

    with conn.transaction():
        conn.execute("update entitlements set llm_mode = 'local' where org_id = %s", (data["org"]["id"],))
    monkeypatch.setattr("cose_cloud.agent.loop.provider_for", lambda cfg, mode: ("local", OneLiner()))
    c = signed_in(client, data["org"])
    cid = c.post("/api/agent/conversations", json={"edition": "hq"}).json()["id"]
    reply = c.post(f"/api/agent/conversations/{cid}/ask", json={"question": "Say hello"}).json()
    assert reply["text"] == "Hello from a local model." and reply["provider"] == "local"
    turns = c.get(f"/api/agent/conversations/{cid}").json()["turns"]
    assert len(turns) == 1 and turns[0]["question"] == "Say hello"
    other = client.post("/api/auth/logout")
    assert other.status_code == 200 and client.get(f"/api/agent/conversations/{cid}").status_code == 401
