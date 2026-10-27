"""End-to-end: the whole stack in Docker, a simulated XSeed on the broker, the web app and CoSE_Agent.

    make e2e            (or: .venv/bin/python tests/e2e/run_e2e.py [--keep])

1. Build the images, start Postgres and Mosquitto, migrate, seed the HQ org and backfill 6 days of simulated XSeed.
2. Start ingest, API, Caddy, the scripted model server and the live simulator (which publishes over mutual TLS).
3. Sign in through Caddy; wait for a reading less than 15 s old that arrived through the broker.
4. The web app is served; the XSeed chart for the last minutes carries the SIMULATED label and live points.
5. Ask CoSE_Agent for yesterday's mean dome temperature (the scripted model drives the real tool loop): the
   answer must match an independent SQL average, with one labelled chart and $0 in the ledger.
Uses its own compose project and random passwords (deploy/compose/e2e.env, git-ignored). Unless --keep, it then tears
everything down, profile services included, and checks that no container of the project is left.
"""

from __future__ import annotations

import argparse
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy/compose"
ENV_FILE = COMPOSE_DIR / "e2e.env"
PROJECT = "cose-cloud-e2e"
BASE = "http://127.0.0.1:8428"
DEVICE = "xseed-sim-0001"
CHECKS: list[tuple[str, bool, str]] = []


def compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-p", PROJECT, "--env-file", str(ENV_FILE), "-f", "docker-compose.yml",
           "-f", "docker-compose.e2e.yml", *args]
    return subprocess.run(cmd, cwd=COMPOSE_DIR, check=check, text=True, capture_output=capture)


def down() -> None:
    """Remove the stack, services behind a profile included: a plain `down` leaves the live simulator running."""
    profiles = compose("config", "--profiles", check=False, capture=True).stdout.split()
    compose(*(a for p in profiles for a in ("--profile", p)), "down", "-v", "--remove-orphans", check=False, capture=True)


def leftover_containers() -> list[str]:
    out = subprocess.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={PROJECT}",
                          "--format", "{{.Names}}"], text=True, capture_output=True).stdout
    return out.split()


def sql(query: str) -> str:
    return compose("exec", "-T", "postgres", "psql", "-U", "cose", "-d", "cose", "-Atc", query,
                   capture=True).stdout.strip()


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}", flush=True)


def wait_for(fn, timeout: float, every: float = 2.0):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = fn()
            if last:
                return last
        except (httpx.HTTPError, KeyError, ValueError) as e:
            last = e
        time.sleep(every)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="leave the stack running afterwards")
    a = ap.parse_args()
    password = secrets.token_urlsafe(18)
    ENV_FILE.write_text("\n".join([
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(18)}", "COSE_ADMIN_EMAIL=e2e-admin@cose.test",
        f"COSE_ADMIN_PASSWORD={password}", "COSE_LLM_MODE=local", "COSE_BACKFILL_DAYS=6", "COSE_TAG=e2e",
        "HTTP_BIND=127.0.0.1", "MQTT_BIND=127.0.0.1", ""]))
    try:
        down()
        print("building images…", flush=True)
        compose("build", "migrate", capture=True)          # one build of the shared services image
        compose("build", "caddy", capture=True)
        compose("up", "-d", "postgres", "mosquitto")
        compose("up", "--no-deps", "migrate")
        t0 = time.monotonic()
        seeded = compose("--profile", "seed", "run", "--rm", "seed", capture=True)
        record("seed + 6-day backfill", '"rejected": 0' in seeded.stdout, f"{time.monotonic() - t0:.0f} s")
        compose("up", "-d", "ingest", "api", "caddy", "fake-llm")
        compose("--profile", "sim", "up", "-d", "sim")

        c = httpx.Client(base_url=BASE, timeout=60)
        ok = wait_for(lambda: c.post("/api/auth/login", json={"email": "e2e-admin@cose.test",
                                                                "password": password}).status_code == 200, 90)
        record("sign in through Caddy", bool(ok))

        def fresh():
            r = c.get(f"/api/devices/{DEVICE}/latest", params={"metrics": "sensors.dome_temp_c"}).json()
            ts = datetime.fromisoformat(r["readings"][0]["ts"])
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            return age if age < 15 else None
        age = wait_for(fresh, 120)
        record("live reading via broker < 15 s old", age is not None, f"{age:.1f} s" if age is not None else "timed out")
        live = sql(f"select count(*) from messages where device_uuid = '{DEVICE}' and ingest_path = 'live'")
        rejects = sql("select count(*) from ingest_rejects")
        record("live messages stored, no rejects", int(live) > 0 and rejects == "0", f"live {live}, rejects {rejects}")

        page = c.get("/xseed")
        record("web app served", page.status_code == 200 and "<title>CoSE Cloud</title>" in page.text)
        csp = page.headers.get("content-security-policy", "")
        record("CSP forbids eval and outside scripts", "script-src 'self'" in csp and "unsafe-eval" not in csp)
        start = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        chart = c.get(f"/api/devices/{DEVICE}/chart", params={"metrics": "sensors.dome_temp_c", "start": start}).json()
        spec = chart["spec"]
        newest = max(datetime.fromisoformat(v["ts"]) for v in spec["data"]["values"])
        record("XSeed chart: SIMULATED label + points from the last minute",
               spec["usermeta"]["provenance"] == ["simulated"] and spec["title"]["subtitle"][0].startswith("SIMULATED")
               and datetime.now(timezone.utc) - newest < timedelta(minutes=1), f"newest bucket {newest.isoformat()}")

        cid = c.post("/api/agent/conversations", json={"edition": "xseed"}).json()["id"]
        reply = c.post(f"/api/agent/conversations/{cid}/ask",
                       json={"question": "What was the mean dome temperature yesterday?"}).json()
        m = re.search(r"was (-?\d+\.\d) °C", reply.get("text", ""))
        truth = float(sql(
            f"select avg(value) from readings where device_uuid = '{DEVICE}' and metric = 'sensors.dome_temp_c' "
            "and quality = 'ok' and ts >= (date_trunc('day', now() at time zone 'America/Chicago') - interval '1 day') "
            "at time zone 'America/Chicago' and ts < date_trunc('day', now() at time zone 'America/Chicago') "
            "at time zone 'America/Chicago'"))
        record("agent mean = independent SQL average", bool(m) and abs(float(m.group(1)) - truth) <= 0.05 + 1e-9,
               f"agent {m.group(1) if m else '?'} °C, SQL {truth:.3f} °C")
        charts = reply.get("charts", [])
        record("one labelled chart, simulated footer",
               len(charts) == 1 and charts[0]["spec"]["title"]["subtitle"][0].startswith("SIMULATED")
               and (reply.get("provenance_footer") or "").startswith("Data provenance: simulated"))
        cost = sql(f"select count(*) || ' calls, $' || coalesce(sum(cost_usd), 0) from usage_ledger where conversation_id = '{cid}'")
        record("ledger: local model at $0", cost.endswith("$0.000000") and not cost.startswith("0 "), cost)
    except subprocess.CalledProcessError as e:
        out = "\n".join(x for x in (e.stdout, e.stderr) if x)
        record("compose step", False, f"{' '.join(e.cmd[-3:])} exited {e.returncode}")
        print(out[-3000:], file=sys.stderr)
    finally:
        if a.keep:
            print(f"stack left running: {BASE} (sign-in e2e-admin@cose.test, password in {ENV_FILE})")
        else:
            down()
            left = leftover_containers()
            record("teardown leaves no containers", not left, ", ".join(left))
    failed = [n for n, ok, _ in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed or not CHECKS else 0


if __name__ == "__main__":
    sys.exit(main())
