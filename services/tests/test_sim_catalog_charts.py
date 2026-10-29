"""Simulator backfill and continuity, catalog mapping and harvest (no network), chart rules, editions, broker rules."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from cose_care_agent.contract.profile import load_profile
from cose_care_agent.eval.runner import load_scenarios
from cose_care_agent.sim.world import SimPod

from cose_cloud import catalog, editions, sim
from cose_cloud.agent import charts
from cose_cloud.broker_acl import acl_text

REPO = Path(__file__).resolve().parents[2]
START = datetime(2026, 9, 1, 5, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ simulator
def _run(hours: float) -> list[bytes]:
    out: list[bytes] = []
    sim.simulate("s0_nominal", 0, START, START + timedelta(hours=hours), 300, out.append)
    return out


def test_backfill_is_deterministic():
    assert _run(6) == _run(6)


def test_backfill_timestamps_follow_the_crop_clock_and_stop_at_until():
    msgs = [json.loads(b) for b in _run(2)]
    ts = [m["timestamp"] for m in msgs]
    assert ts[0] == int(START.timestamp()) + 300 and ts[-1] <= int((START + timedelta(hours=2)).timestamp())
    assert all(b - a == 300 for a, b in zip(ts, ts[1:]))


def test_live_stream_continues_the_backfilled_run():
    """simdevice runs a fresh pod to start_h with the same seed: its state must equal the backfill's."""
    hours = 30.0
    pod_a = sim.simulate("s0_nominal", 0, START, START + timedelta(hours=hours), 3600, lambda b: None)
    pod_b = SimPod(load_profile("xseed_v1"), load_scenarios(["s0_nominal"])[0], seed=0)
    pod_b.device.epoch = START.timestamp()
    pod_b.run_until(hours * 3600)
    assert pod_a.t == pod_b.t
    a, b = pod_a.device.telemetry(pod_a.t), pod_b.device.telemetry(pod_b.t)
    assert a.sensors == b.sensors and a.biometrics_3d == b.biometrics_3d and a.timestamp == b.timestamp


def test_crop_start_is_local_midnight():
    now = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)
    assert sim.crop_start(6, "America/Chicago", now) == datetime(2026, 10, 18, 5, 0, tzinfo=timezone.utc)


@pytest.mark.db
def test_backfill_into_the_database(conn, make_org):
    org = make_org()
    slug = conn.execute("select slug from orgs where id = %s", (org["id"],)).fetchone()["slug"]
    now = datetime.now(timezone.utc)
    out = sim.backfill(conn, org_slug=slug, device_uuid=f"xseed-sim-{org['n']}", scenario="s0_nominal", seed=0,
                       days_ago=0, every_s=600, now=now)
    assert out["rejected"] == 0 and out["stored"] > 0
    row = conn.execute("select max(ts) last, count(distinct provenance) kinds, min(provenance) p from readings "
                       "where device_uuid = %s", (f"xseed-sim-{org['n']}",)).fetchone()
    assert row["last"] <= now and row["kinds"] == 1 and row["p"] == "simulated"
    dev = conn.execute("select data_origin, sim_meta from devices where device_uuid = %s",
                       (f"xseed-sim-{org['n']}",)).fetchone()
    assert dev["data_origin"] == "simulator" and dev["sim_meta"]["scenario"] == "s0_nominal"


# ------------------------------------------------------------------ catalog
EC5_ENTRY = {
    "ec5_uuid": "0a1b2c3d-0000-4000-8000-000000000001", "created_at": "2022-03-04T10:00:00.000Z",
    "uploaded_at": "2022-03-04T11:00:00.000Z", "title": "0a1b2c3d-0000-4000-8000-000000000001",
    "1_photo": "https://five.epicollect.net/api/media/proj?type=photo&format=entry_original&name=a.jpg",
    "2_plant_health": "Good", "3_plants_per_tray": "12", "4_Select_the_cultivar_being_reported": "Outredgeous",
    "5_location": {"latitude": 43.07, "longitude": -89.4, "accuracy": 5}, "6_notes": "watered twice",
}


def test_ec5_mapping_matches_the_draft_rules():
    it = catalog.map_ec5(EC5_ENTRY)
    assert it["species"] == "Outredgeous"                  # not "Good", not "12"
    assert it["title"] == "Outredgeous" and it["media_kind"] == "image"
    assert it["thumb_url"].endswith("format=entry_thumb&name=a.jpg")
    assert (it["lat"], it["lon"]) == (43.07, -89.4)
    assert {"name": "Notes", "value": "watered twice"} in it["fields"]


def test_sidecars():
    csv_rows = catalog.parse_sidecar("metadata.csv", "filename,species,treatment\na.jpg,Arabidopsis thaliana,flight\n")
    assert csv_rows["a.jpg"]["species"] == "Arabidopsis thaliana"
    json_rows = catalog.parse_sidecar("metadata.json", json.dumps({"b.png": {"species": "Zea mays"}}))
    assert json_rows["b.png"]["species"] == "Zea mays"


@pytest.mark.db
def test_harvest_without_network(conn, make_org):
    org = make_org()
    slug = conn.execute("select slug from orgs where id = %s", (org["id"],)).fetchone()["slug"]
    with conn.transaction():
        catalog.register_sources(conn, org["id"])

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "five.epicollect.net":
            return httpx.Response(200, json={"data": {"entries": [EC5_ENTRY]}, "links": {"next": None}})
        if req.url.path.endswith("/contents/APEX05/images"):
            return httpx.Response(200, json=[
                {"type": "file", "name": "a.jpg", "path": "APEX05/images/a.jpg", "download_url": "https://raw.example/a.jpg"},
                {"type": "file", "name": "metadata.csv", "path": "APEX05/images/metadata.csv",
                 "download_url": "https://raw.example/metadata.csv"},
                {"type": "file", "name": "readme.txt", "path": "APEX05/images/readme.txt", "download_url": "x"}])
        if req.url.host == "raw.example":
            return httpx.Response(200, text="filename,species\na.jpg,Arabidopsis thaliana\n")
        return httpx.Response(404, json={"message": "Not Found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = catalog.harvest(conn, slug, client=client, ec5_gap_s=0)
    assert report["clinostat-collaboration"] == 1
    assert report["dr-richard-barker/image-analysis-software-and-R-codes/master/APEX05/images"] == 1
    assert str(report["dr-richard-barker/image-analysis-software-and-R-codes/master/TICTOC/images"]).startswith("error")
    row = conn.execute("select i.species, i.media_url from catalog_items i join catalog_sources s on s.id = i.source_id "
                       "where s.org_id = %s and s.kind = 'github'", (org["id"],)).fetchone()
    assert row == {"species": "Arabidopsis thaliana", "media_url": "https://raw.example/a.jpg"}


# ------------------------------------------------------------------ charts
METRICS = [{"key": "t", "label": "Dome air temperature", "unit": "°C"},
           {"key": "r", "label": "Root-zone temperature", "unit": "°C"},
           {"key": "h", "label": "Mean canopy height", "unit": "mm"}]
PTS = [{"metric": k, "ts": START + timedelta(minutes=i), "value": float(i), "n": 1} for k in "trh" for i in range(3)]


def test_different_units_never_share_an_axis():
    spec = charts.build(PTS, METRICS, title="x", provenance_notes=["SIMULATED — test"], provenance=["simulated"])
    assert len(spec["vconcat"]) == 2 and spec["resolve"]["scale"]["y"] == "independent"
    assert spec["data"]["name"] == charts.DATA_NAME and len(spec["data"]["values"]) == 9
    hovers = [l["params"][0]["name"] for panel in spec["vconcat"] for l in panel["layer"] if "params" in l]
    assert len(hovers) == len(set(hovers)) == 2        # unique selection names across panels
    assert spec["title"]["subtitle"] == ["SIMULATED — test"]
    long = charts.build(PTS, METRICS[:1], title="x", provenance_notes=["SIMULATED — CoSE-Care-Agent SimPod v0.1.1 "
                        "(s0_nominal, seed 0), sim-uncalibrated"], provenance=["simulated"])
    assert len(long["title"]["subtitle"]) == 2 and long["title"]["subtitle"][0].startswith("SIMULATED")


def test_one_unit_is_one_panel_with_legend_and_labels():
    spec = charts.build(PTS, METRICS[:2], title="x", provenance_notes=[], provenance=["measured"])
    assert "vconcat" not in spec and spec["layer"][0]["encoding"]["color"]["legend"] is not None
    assert not any(layer["mark"]["type"] == "text" for layer in spec["layer"])  # both end at 2.0: labels would collide
    apart = [{**p, "value": p["value"] * (10 if p["metric"] == "r" else 1)} for p in PTS]
    spec = charts.build(apart, METRICS[:2], title="x", provenance_notes=[], provenance=["measured"])
    assert any(layer["mark"]["type"] == "text" for layer in spec["layer"])     # end-of-line labels
    single = charts.build(PTS, METRICS[:1], title="x", provenance_notes=[], provenance=["measured"])
    assert single["layer"][0]["encoding"]["color"]["legend"] is None


# ------------------------------------------------------------------ editions and broker rules
def test_editions_validate():
    eds = editions.all_editions()
    assert list(eds) == ["hq", "xseed", "rover", "drone", "sense"]
    assert [e for e in eds.values() if e["status"] == "live"] == [eds["hq"], eds["xseed"]]
    assert editions.allowed_tools("hq") is None and "make_chart" in editions.allowed_tools("xseed")


def test_committed_acl_matches_the_generator():
    assert (REPO / "deploy/compose/mosquitto/acl").read_text() == acl_text()


def test_nobody_may_write_commands():
    text = acl_text()
    assert "write cose/v1/devices/+/commands" not in text
    user_block = text.split("pattern", 1)[0]
    assert "topic write" not in user_block


def test_write_spec_fixtures():
    """Real builder output for apps/web/src/test/vegalite.test.ts, which compiles each spec with Vega-Lite."""
    out = {f"{kind}-{n}": charts.build(PTS, METRICS[:n], title=f"{kind} {n}", kind=kind,
                                        provenance_notes=["SIMULATED — test"], provenance=["simulated"])
           for kind in charts.KINDS for n in (1, 2, 3)}
    path = REPO / "apps/web/src/test/fixtures/specs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, indent=1, sort_keys=True, default=str) + "\n"
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
