"""A simulated XSeed for CoSE Cloud, until XSeed hardware exists: a backfilled crop history plus a live stream.

    cose-cloud-sim backfill --org hq --device xseed-sim-0001 --days-ago 6
    cose-cloud-sim live --device xseed-sim-0001

Both run CoSE-Care-Agent's SimPod (plant physics + the XSeed firmware core). `backfill` steps it offline from the
start of the crop (local midnight `--days-ago` days back, in the site's time zone) to now and stores one telemetry
message every `--every` seconds through the same normalise() the broker path uses. `live` starts Care-Agent's
SimDevice on the broker at the crop hour reached now, with the same scenario and seed: SimPod's noise does not
depend on its state, so the live stream continues the backfilled run.

Every message from a simulator device is stored as `simulated` (the registry, not the payload, decides), and the
device's `sim_meta` says what produced it.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import cose_care_agent
from cose_care_agent.contract.profile import load_profile
from cose_care_agent.contract.units import S_PER_H
from cose_care_agent.eval.runner import load_scenarios
from cose_care_agent.sim.world import SimPod

from cose_cloud import store
from cose_cloud.config import settings
from cose_cloud.db import connect
from cose_cloud.provenance import SIM_LABEL, provenance_note
from cose_ingest_core import Accepted, DeviceRecord, normalise

log = logging.getLogger("cose_cloud.sim")
PROFILE = "xseed_v1"


def crop_start(days_ago: int, tz: str, now: datetime) -> datetime:
    """Local midnight `days_ago` days before today, in the site's time zone (the crop clock starts at midnight)."""
    local = now.astimezone(ZoneInfo(tz))
    day = (local - timedelta(days=days_ago)).date()
    return datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def simulate(scenario: str, seed: int, start: datetime, until: datetime, every_s: float,
             emit: Callable[[bytes], None]) -> SimPod:
    """Step a pod from crop hour 0 at `start` to `until`, emitting the device's telemetry every `every_s` seconds."""
    pod = SimPod(load_profile(PROFILE), load_scenarios([scenario])[0], seed=seed)
    pod.device.epoch = start.timestamp()          # device wall clock = epoch + crop seconds
    t_end = (until - start).total_seconds()
    every = max(every_s, pod.dt)
    next_emit = every
    while pod.t + pod.dt <= t_end + 1e-9:
        pod.step()
        if pod.t + 1e-9 >= next_emit:
            emit(pod.device.telemetry(pod.t).model_dump_json().encode())
            next_emit += every
    return pod


def backfill(conn, *, org_slug: str, device_uuid: str, scenario: str, seed: int, days_ago: int, every_s: float,
             site_name: Optional[str] = None, now: Optional[datetime] = None, batch: int = 500) -> dict:
    now = now or datetime.now(timezone.utc)
    org = conn.execute("select id from orgs where slug = %s", (org_slug,)).fetchone()
    if org is None:
        raise SystemExit(f"no org {org_slug!r}: run `cose-cloud seed` first")
    site = conn.execute("select id, timezone from sites where org_id = %s and (%s::text is null or name = %s) "
                        "order by id limit 1", (org["id"], site_name, site_name)).fetchone()
    if site is None:
        raise SystemExit("no site for this org: run `cose-cloud seed` first")
    start = crop_start(days_ago, site["timezone"], now)
    exp_id = f"{device_uuid}-{start.astimezone(ZoneInfo(site['timezone'])):%Y%m%d}"
    sim_meta = {"scenario": scenario, "seed": seed, "epoch": start.timestamp(), "experiment_id": exp_id,
                "care_agent": cose_care_agent.__version__, "profile": PROFILE, "every_s": every_s, "label": SIM_LABEL}
    profile = load_profile(PROFILE)
    with conn.transaction():
        store.register_device(conn, device_uuid=device_uuid, org_id=org["id"], product="xseed",
                              data_origin="simulator", site_id=site["id"], label="XSeed (simulated)",
                              variant="terrestrial", sim_meta=sim_meta)
        conn.execute(
            "insert into experiments (id, org_id, product, device_uuid, title, crop, started_at, data_origin, protocol) "
            "values (%s,%s,'xseed',%s,%s,%s,%s,'simulator',%s) on conflict (id) do update set started_at = excluded.started_at",
            (exp_id, org["id"], device_uuid, f"Simulated {profile.get('recipe.crop')} cycle ({scenario})",
             profile.get("recipe.crop"), start, json.dumps({"scenario": scenario, "seed": seed,
                                                            "source": provenance_note(sim_meta)})))
    device = DeviceRecord(device_uuid, "xseed", "simulator")
    topic = f"cose/v1/devices/{device_uuid}/telemetry"
    counts = {"stored": 0, "duplicates": 0, "rejected": 0}
    pending: list[bytes] = []

    def flush() -> None:
        with conn.transaction():
            for payload in pending:
                ts = datetime.fromtimestamp(json.loads(payload)["timestamp"], timezone.utc)
                result = normalise(topic, payload, ts, device, ingest_path="backfill")
                mid = store.write(conn, result, topic, payload)
                key = "stored" if mid is not None else ("duplicates" if isinstance(result, Accepted) else "rejected")
                counts[key] += 1
        pending.clear()

    def emit(payload: bytes) -> None:
        pending.append(payload)
        if len(pending) >= batch:
            flush()

    t0 = time.monotonic()
    pod = simulate(scenario, seed, start, now, every_s, emit)
    flush()
    log.info("backfilled %s from %s to crop hour %.1f in %.1fs: %s", device_uuid, start.isoformat(),
             pod.t / S_PER_H, time.monotonic() - t0, counts)
    return {"experiment_id": exp_id, "start": start.isoformat(), "crop_hours": pod.t / S_PER_H, **counts}


def live(conn, *, device_uuid: str, duration_s: Optional[float] = None) -> None:
    from cose_care_agent.service.config import SimDeviceConfig
    from cose_care_agent.service.simdevice import SimDevice
    from cose_care_agent.transport.mosquitto import Endpoint

    row = conn.execute("select sim_meta from devices where device_uuid = %s and data_origin = 'simulator'",
                       (device_uuid,)).fetchone()
    if row is None or not row["sim_meta"]:
        raise SystemExit(f"{device_uuid} is not a backfilled simulator device: run `cose-cloud-sim backfill` first")
    meta = row["sim_meta"]
    conn.commit()
    scenario = load_scenarios([meta["scenario"]])[0]
    start_h = (time.time() - meta["epoch"]) / S_PER_H
    if start_h > scenario.get("window_h", float("inf")):
        log.warning("crop hour %.1f is past the %s window (%s h): run a new backfill for a fresh crop",
                    start_h, meta["scenario"], scenario["window_h"])
    cfg = settings()
    ep = Endpoint(cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_ca, cfg.mqtt_cert, cfg.mqtt_key)
    dev = SimDevice(SimDeviceConfig(device_uuid=device_uuid, broker=ep, profile=meta.get("profile", PROFILE),
                                    scenario=meta["scenario"], seed=int(meta["seed"]), start_h=start_h))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: dev.stop())
    dev.run(duration_s)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Simulated XSeed for CoSE Cloud (CoSE-Care-Agent SimPod).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="store a crop's history so far, offline")
    b.add_argument("--org", default="hq")
    b.add_argument("--site")
    b.add_argument("--device", default="xseed-sim-0001")
    b.add_argument("--scenario", default="s0_nominal")
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--days-ago", type=int, default=6)
    b.add_argument("--every", type=float, default=60.0, help="seconds between stored messages")
    lv = sub.add_parser("live", help="publish on the broker in real time, continuing the backfilled crop")
    lv.add_argument("--device", default="xseed-sim-0001")
    lv.add_argument("--duration", type=float)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with connect(settings().database_url) as conn:
        if a.cmd == "backfill":
            print(json.dumps(backfill(conn, org_slug=a.org, device_uuid=a.device, scenario=a.scenario, seed=a.seed,
                                      days_ago=a.days_ago, every_s=a.every, site_name=a.site), indent=1))
        else:
            live(conn, device_uuid=a.device, duration_s=a.duration)


if __name__ == "__main__":
    main()
