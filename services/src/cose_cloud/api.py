"""CoSE Cloud HTTP API (FastAPI), served under /api behind Caddy.

    uvicorn cose_cloud.api:app --host 0.0.0.0 --port 8429

Every data route takes the organisation from the session cookie; nothing in a request chooses another org.
This process has no broker credentials: it reads the database and calls the model provider, and nothing else.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import psycopg
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from cose_cloud import __version__, auth, editions, export, queries
from cose_cloud.agent import charts, ledger
from cose_cloud.agent.loop import AgentUnavailable, Org, ask, provider_for
from cose_cloud.config import Settings, settings

COOKIE = "cose_session"
_pool: Optional[ConnectionPool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = ConnectionPool(settings().database_url, min_size=1, max_size=10, kwargs={"row_factory": dict_row},
                           open=True)
    yield
    _pool.close()


app = FastAPI(title="CoSE Cloud", version=__version__, lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json")


def get_conn() -> Iterator[psycopg.Connection]:
    assert _pool is not None
    with _pool.connection() as conn:   # commits on success, rolls back on error
        yield conn


def cfg() -> Settings:
    return settings()


def me(conn: psycopg.Connection = Depends(get_conn),
       cose_session: Optional[str] = Cookie(default=None)) -> auth.Principal:
    p = auth.principal(conn, cose_session)
    if p is None:
        raise HTTPException(401, "sign in first")
    return p


@app.exception_handler(queries.NotFound)
async def _not_found(request: Request, exc: queries.NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(queries.BadRequest)
async def _bad_request(request: Request, exc: queries.BadRequest):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ------------------------------------------------------------------ auth
class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, conn: psycopg.Connection = Depends(get_conn),
          s: Settings = Depends(cfg)) -> dict:
    token = auth.login(conn, body.email.strip(), body.password, s.session_days)
    if token is None:
        raise HTTPException(401, "wrong email or password")
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_days * 86400, path="/")
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response, conn: psycopg.Connection = Depends(get_conn),
           cose_session: Optional[str] = Cookie(default=None)) -> dict:
    auth.logout(conn, cose_session)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


def _entitlements(conn, org_id: int) -> dict:
    return conn.execute("select tier, llm_mode, llm_monthly_cap_usd from entitlements where org_id = %s",
                        (org_id,)).fetchone() or {"tier": "free", "llm_mode": "off", "llm_monthly_cap_usd": None}


@app.get("/api/me")
def whoami(p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> dict:
    ent = _entitlements(conn, p.org_id)
    return {"user": {"id": p.user_id, "email": p.email, "name": p.display_name, "role": p.role},
            "org": {"id": p.org_id, "slug": p.org_slug, "name": p.org_name},
            "entitlements": {"tier": ent["tier"], "llm_mode": ent["llm_mode"]}}


@app.get("/api/health")
def health(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    conn.execute("select 1")
    return {"ok": True, "version": __version__}


# ------------------------------------------------------------------ registry and data
@app.get("/api/editions")
def list_editions() -> list[dict]:
    return list(editions.all_editions().values())


@app.get("/api/metrics")
def metrics(product: Optional[str] = None, p: auth.Principal = Depends(me),
            conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    return queries.metric_registry(conn, product)


@app.get("/api/devices")
def devices(product: Optional[str] = None, p: auth.Principal = Depends(me),
            conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    return queries.list_devices(conn, p.org_id, product)


@app.get("/api/devices/{device_uuid}")
def device_detail(device_uuid: str, p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> dict:
    return {"device": queries.device(conn, p.org_id, device_uuid),
            "coverage": queries.coverage(conn, p.org_id, device_uuid)}


def _metrics_param(metrics: str) -> list[str]:
    out = [m for m in (x.strip() for x in metrics.split(",")) if m]
    if not 1 <= len(out) <= 8:
        raise queries.BadRequest("give 1-8 comma-separated metric keys")
    return out


@app.get("/api/devices/{device_uuid}/latest")
def latest(device_uuid: str, metrics: Optional[str] = None, p: auth.Principal = Depends(me),
           conn: psycopg.Connection = Depends(get_conn)) -> dict:
    return queries.latest(conn, p.org_id, device_uuid, _metrics_param(metrics) if metrics else None)


@app.get("/api/devices/{device_uuid}/series")
def series(device_uuid: str, metrics: str, day: Optional[str] = None, start: Optional[str] = None,
           end: Optional[str] = None, bucket_s: Optional[int] = Query(default=None, ge=0),
           p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> dict:
    dev = queries.device(conn, p.org_id, device_uuid)
    s, e, label = queries.window(start, end, day, dev["timezone"])
    out = queries.series(conn, p.org_id, device_uuid, _metrics_param(metrics), s, e, bucket_s)
    return {**out, "window": label}


@app.get("/api/devices/{device_uuid}/chart")
def chart(device_uuid: str, metrics: str, title: str = Query(default="", max_length=120), day: Optional[str] = None,
          start: Optional[str] = None, end: Optional[str] = None, p: auth.Principal = Depends(me),
          conn: psycopg.Connection = Depends(get_conn)) -> dict:
    """A server-built chart (the same builder CoSE_Agent uses), for the dashboards."""
    dev = queries.device(conn, p.org_id, device_uuid)
    s, e, label = queries.window(start, end, day, dev["timezone"])
    out = queries.series(conn, p.org_id, device_uuid, _metrics_param(metrics), s, e)
    order = _metrics_param(metrics)
    registry = sorted(out["metrics"], key=lambda m: order.index(m["key"]))
    spec = charts.build(out["points"], registry, title=title or f"{dev['label'] or device_uuid}",
                        provenance_notes=[dev["provenance_note"]] if dev["provenance_note"] else [],
                        provenance=[dev["provenance"]])
    return {"spec": spec, "window": label, "bucket_s": out["bucket_s"], "window_utc": out["window_utc"]}


@app.get("/api/devices/{device_uuid}/since")
def since(device_uuid: str, metrics: str, after: str, p: auth.Principal = Depends(me),
          conn: psycopg.Connection = Depends(get_conn)) -> dict:
    try:
        ts = datetime.fromisoformat(after.replace("Z", "+00:00"))
    except ValueError as e:
        raise queries.BadRequest("after must be ISO 8601") from e
    return {"rows": queries.since(conn, p.org_id, device_uuid, _metrics_param(metrics), ts),
            "server_time": datetime.now(timezone.utc)}


@app.get("/api/devices/{device_uuid}/alerts")
def alerts(device_uuid: str, day: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
           p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> dict:
    dev = queries.device(conn, p.org_id, device_uuid)
    s, e, label = queries.window(start, end, day, dev["timezone"])
    return {"window": label, "events": queries.alerts(conn, p.org_id, device_uuid, s, e)}


@app.get("/api/experiments")
def experiments(p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    return queries.experiments(conn, p.org_id)


@app.get("/api/catalog/sources")
def catalog_sources(p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    return queries.catalog_sources(conn, p.org_id)


@app.get("/api/catalog/items")
def catalog_items(q: Optional[str] = None, species: Optional[str] = None, source: Optional[str] = None,
                  media: Optional[str] = None, limit: int = Query(default=60, ge=1, le=200),
                  offset: int = Query(default=0, ge=0), p: auth.Principal = Depends(me),
                  conn: psycopg.Connection = Depends(get_conn)) -> dict:
    return queries.catalog_search(conn, p.org_id, q, species, source, media, limit, offset)


@app.get("/api/catalog/species")
def catalog_species(p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    return queries.catalog_species(conn, p.org_id)


# ------------------------------------------------------------------ exports
def _download(dataset: dict, fmt: str, conn, org_id: int) -> Response:
    q = dataset["query"]
    if fmt == "csv":
        return Response(export.samples_csv(dataset), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{export.filename(dataset, "csv")}"'})
    if fmt != "rocrate":
        raise queries.BadRequest("format must be csv or rocrate")
    dev = queries.device(conn, org_id, q["device_uuid"])
    exp = next((e for e in queries.experiments(conn, org_id) if e["id"] == dev["experiment_id"]), None)
    s, e = (datetime.fromisoformat(x) for x in q["window_utc"])
    body = export.rocrate_zip(dataset, device=dev, experiment=exp,
                              events=queries.alerts(conn, org_id, q["device_uuid"], s, e))
    return Response(body, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{export.filename(dataset, "zip")}"'})


@app.get("/api/devices/{device_uuid}/export")
def export_device(device_uuid: str, metrics: str, format: str = "csv", day: Optional[str] = None,
                  start: Optional[str] = None, end: Optional[str] = None, bucket_s: Optional[int] = Query(None, ge=0),
                  p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> Response:
    dev = queries.device(conn, p.org_id, device_uuid)
    s, e, label = queries.window(start, end, day, dev["timezone"])
    out = queries.series(conn, p.org_id, device_uuid, _metrics_param(metrics), s, e, bucket_s)
    dataset = {"query": {"device_uuid": device_uuid, "device_label": dev["label"], "product": dev["product"],
                         "registry": out["metrics"], "window": label, "window_utc": out["window_utc"],
                         "bucket_s": out["bucket_s"], "provenance_note": dev["provenance_note"]},
               "provenance": [dev["provenance"]],
               "rows": [{**r, "ts": r["ts"].isoformat()} for r in out["points"]]}
    return _download(dataset, format, conn, p.org_id)


@app.get("/api/datasets/{dataset_id}/export")
def export_dataset(dataset_id: uuid.UUID, format: str = "csv", p: auth.Principal = Depends(me),
                   conn: psycopg.Connection = Depends(get_conn)) -> Response:
    ds = conn.execute("select id, query, provenance, rows from datasets where id = %s and org_id = %s",
                      (dataset_id, p.org_id)).fetchone()
    if ds is None:
        raise HTTPException(404, "no such dataset")
    return _download(ds, format, conn, p.org_id)


# ------------------------------------------------------------------ CoSE_Agent
class NewConversation(BaseModel):
    edition: str = Field(default="hq", max_length=20)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@app.get("/api/agent/status")
def agent_status(p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn),
                 s: Settings = Depends(cfg)) -> dict:
    ent = _entitlements(conn, p.org_id)
    model = {"hosted": s.chat_model, "local": s.local_llm_model, "off": None}[ent["llm_mode"]]
    available, reason = True, None
    try:
        provider_for(s, ent["llm_mode"]) if ent["llm_mode"] != "hosted" else None
    except AgentUnavailable as e:
        available, reason = False, str(e)
    if s.llm_kill_switch:
        available, reason = False, "CoSE_Agent is switched off for maintenance"
    return {"llm_mode": ent["llm_mode"], "model": model, "available": available, "reason": reason,
            "month_spend_usd": round(ledger.month_spend(conn, p.org_id), 4),
            "monthly_cap_usd": float(ent["llm_monthly_cap_usd"]) if ent["llm_monthly_cap_usd"] is not None else None,
            "data_notice": ("Questions and the data the agent reads are sent to Anthropic's API."
                            if ent["llm_mode"] == "hosted" else
                            "Questions stay on this network (local model)." if ent["llm_mode"] == "local" else None)}


@app.post("/api/agent/conversations")
def new_conversation(body: NewConversation, p: auth.Principal = Depends(me),
                     conn: psycopg.Connection = Depends(get_conn)) -> dict:
    if editions.get(body.edition) is None:
        raise HTTPException(400, f"no edition {body.edition!r}")
    cid = uuid.uuid4()
    conn.execute("insert into conversations (id, org_id, user_id, edition) values (%s,%s,%s,%s)",
                 (cid, p.org_id, p.user_id, body.edition))
    return {"id": str(cid), "edition": body.edition}


def _conversation(conn, p: auth.Principal, cid: uuid.UUID) -> dict:
    row = conn.execute("select id, edition from conversations where id = %s and org_id = %s and user_id = %s",
                       (cid, p.org_id, p.user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "no such conversation")
    return row


@app.get("/api/agent/conversations/{cid}")
def conversation(cid: uuid.UUID, p: auth.Principal = Depends(me), conn: psycopg.Connection = Depends(get_conn)) -> dict:
    conv = _conversation(conn, p, cid)
    turns = conn.execute("select question, reply, created_at from conversation_turns where conversation_id = %s "
                         "order by id", (cid,)).fetchall()
    return {"id": str(conv["id"]), "edition": conv["edition"], "turns": turns}


@app.post("/api/agent/conversations/{cid}/ask")
def ask_question(cid: uuid.UUID, body: Question, p: auth.Principal = Depends(me),
                 conn: psycopg.Connection = Depends(get_conn), s: Settings = Depends(cfg)) -> dict[str, Any]:
    conv = _conversation(conn, p, cid)
    ent = _entitlements(conn, p.org_id)
    site = conn.execute("select timezone from sites where org_id = %s order by id limit 1", (p.org_id,)).fetchone()
    org = Org(p.org_id, p.org_name, p.user_id, ent["llm_mode"],
              float(ent["llm_monthly_cap_usd"]) if ent["llm_monthly_cap_usd"] is not None else None)
    try:
        return ask(conn, s, org, conversation_id=cid, edition=conv["edition"], question=body.question,
                   tz=site["timezone"] if site else queries.DEFAULT_TZ,
                   allowed_tools=editions.allowed_tools(conv["edition"]))
    except AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e
