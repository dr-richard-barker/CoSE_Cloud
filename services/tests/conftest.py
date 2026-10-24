"""Shared fixtures. Database tests need Postgres: COSE_TEST_DATABASE_URL points at a server where the test user
may create databases (`make test-db` starts one on 127.0.0.1:54329). Each run gets a fresh database."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import psycopg
import pytest
from psycopg.rows import dict_row

from cose_cloud import auth, store
from cose_cloud.db import connect, migrate
from cose_ingest_core import DeviceRecord, normalise

ADMIN_URL = os.environ.get("COSE_TEST_DATABASE_URL", "postgresql://cose:cose@127.0.0.1:54329/cose_test")
FIX = Path(__file__).resolve().parents[2] / "packages/ingest_core/tests/fixtures"
PASSWORD = "test-password-123"


def _server_available() -> bool:
    try:
        psycopg.connect(ADMIN_URL, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    if not _server_available():
        pytest.skip(f"no Postgres at {ADMIN_URL} (run `make test-db`)")
    name = f"cose_pytest_{os.getpid()}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f"drop database if exists {name}")
        c.execute(f"create database {name}")
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    with connect(url) as conn:
        migrate(conn)
        with conn.transaction():
            store.seed_metrics(conn)
    os.environ["COSE_DATABASE_URL"] = url
    yield url
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f"drop database if exists {name} with (force)")


@pytest.fixture
def conn(db_url) -> Iterator[psycopg.Connection]:
    with connect(db_url) as c:
        yield c


_counter = iter(range(1, 10_000))


@pytest.fixture
def make_org(conn) -> Callable[..., dict]:
    def make(llm_mode: str = "off", cap: float | None = None, tz: str = "America/Chicago") -> dict:
        n = next(_counter)
        with conn.transaction():
            org = conn.execute("insert into orgs (slug, name) values (%s,%s) returning id",
                               (f"org-{os.getpid()}-{n}", f"Org {n}")).fetchone()
            site = conn.execute("insert into sites (org_id, name, timezone) values (%s,'Lab',%s) returning id",
                                (org["id"], tz)).fetchone()
            conn.execute("insert into entitlements (org_id, llm_mode, llm_monthly_cap_usd) values (%s,%s,%s)",
                         (org["id"], llm_mode, cap))
            email = f"user{n}-{os.getpid()}@example.org"
            uid = auth.create_user(conn, email=email, password=PASSWORD, org_id=org["id"], role="admin")
        return {"id": org["id"], "site_id": site["id"], "user_id": uid, "email": email, "n": n}
    return make


@pytest.fixture
def contract_payload() -> dict:
    return json.loads((FIX / "xseed_contract_h72.json").read_text())


def add_device(conn, org: dict, uuid: str, origin: str = "simulator", product: str = "xseed",
               sim_meta: dict | None = None) -> None:
    with conn.transaction():
        store.register_device(conn, device_uuid=uuid, org_id=org["id"], product=product, data_origin=origin,
                              site_id=org["site_id"], label=f"{product} {uuid}",
                              sim_meta=sim_meta if sim_meta is not None else (
                                  {"scenario": "s0_nominal", "seed": 0, "care_agent": "0.1.1"}
                                  if origin == "simulator" else None))


def ingest(conn, uuid: str, payload: dict, origin: str = "simulator", path: str = "backfill"):
    raw = json.dumps(payload).encode()
    ts = datetime.fromtimestamp(payload["timestamp"], timezone.utc)
    res = normalise(f"cose/v1/devices/{uuid}/telemetry", raw, ts + timedelta(seconds=1),
                    DeviceRecord(uuid, "xseed", origin), ingest_path=path)
    with conn.transaction():
        return store.write(conn, res, f"cose/v1/devices/{uuid}/telemetry", raw)


def series_payloads(base: dict, start: datetime, values: list[float], step_s: int = 60) -> list[dict]:
    """Copies of a real payload with dome_temp_c set to `values`, one per step from `start`."""
    out = []
    for i, v in enumerate(values):
        p = json.loads(json.dumps(base))
        p["timestamp"] = int(start.timestamp()) + i * step_s
        p["sensors"]["dome_temp_c"] = v
        p["seq"] = i + 1
        out.append(p)
    return out
