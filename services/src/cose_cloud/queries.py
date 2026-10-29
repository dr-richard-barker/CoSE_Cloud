"""Reads, all scoped to one org. The org always comes from the caller's session (API) or the server (agent tools),
never from request data or the model, so every function takes `org_id` first and filters on it."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import psycopg

from cose_cloud.provenance import provenance_note

DEFAULT_TZ = "America/Chicago"
MAX_POINTS = 1500          # per metric, per series request: buckets widen to stay under it
MAX_WINDOW = timedelta(days=62)


class NotFound(LookupError):
    pass


class BadRequest(ValueError):
    pass


def _device_select() -> str:
    return ("select d.device_uuid, d.product, d.variant, d.label, d.data_origin, d.sim_meta, d.first_seen, d.last_seen, "
            "s.name site, coalesce(s.timezone, %s) timezone, "
            "(select e.id from experiments e where e.device_uuid = d.device_uuid order by e.started_at desc limit 1) "
            "experiment_id from devices d left join sites s on s.id = d.site_id ")


def _decorate(d: dict) -> dict:
    d["provenance"] = {"hardware": "measured", "simulator": "simulated", "replay": "replay"}[d["data_origin"]]
    d["provenance_note"] = provenance_note(d["sim_meta"]) if d["data_origin"] == "simulator" and d["sim_meta"] else None
    return d


def list_devices(conn: psycopg.Connection, org_id: int, product: Optional[str] = None) -> list[dict]:
    rows = conn.execute(_device_select() + "where d.org_id = %s and (%s::text is null or d.product = %s) and not exists "
                        "(select 1 from hidden_content h where h.org_id = d.org_id and h.kind = 'device' "
                        "and h.ref = d.device_uuid) order by d.product, d.device_uuid",
                        (DEFAULT_TZ, org_id, product, product)).fetchall()
    return [_decorate(r) for r in rows]


def device(conn: psycopg.Connection, org_id: int, device_uuid: str) -> dict:
    row = conn.execute(_device_select() + "where d.org_id = %s and d.device_uuid = %s",
                       (DEFAULT_TZ, org_id, device_uuid)).fetchone()
    if row is None:
        raise NotFound(f"no device {device_uuid!r} in this organisation")
    return _decorate(row)


def metric_registry(conn: psycopg.Connection, product: Optional[str] = None) -> list[dict]:
    return conn.execute("select product, key, label, unit, kind, null_meaning from metrics "
                        "where %s::text is null or product = %s order by product, key", (product, product)).fetchall()


def _metric_keys(conn, product: str) -> set[str]:
    return {r["key"] for r in metric_registry(conn, product)}


def check_metrics(conn, dev: dict, metrics: list[str]) -> list[str]:
    known = _metric_keys(conn, dev["product"])
    bad = [m for m in metrics if m not in known]
    if bad:
        raise BadRequest(f"unknown metric(s) for {dev['product']}: {', '.join(bad)}; use list_metrics")
    return metrics


def coverage(conn: psycopg.Connection, org_id: int, device_uuid: str) -> list[dict]:
    dev = device(conn, org_id, device_uuid)
    return conn.execute(
        "select m.key metric, m.label, m.unit, m.kind, c.n, c.first, c.last from metrics m left join lateral "
        "(select count(*) n, min(ts) first, max(ts) last from readings r where r.device_uuid = %s and r.metric = m.key) c "
        "on true where m.product = %s order by m.key", (device_uuid, dev["product"])).fetchall()


def latest(conn: psycopg.Connection, org_id: int, device_uuid: str, metrics: Optional[list[str]] = None) -> dict:
    dev = device(conn, org_id, device_uuid)
    if metrics:
        check_metrics(conn, dev, metrics)
    rows = conn.execute(
        "select distinct on (r.metric) r.metric, r.ts, r.value, r.quality, m.label, m.unit from readings r "
        "join metrics m on m.product = %s and m.key = r.metric where r.device_uuid = %s "
        "and (%s::text[] is null or r.metric = any(%s)) order by r.metric, r.ts desc",
        (dev["product"], device_uuid, metrics, metrics)).fetchall()
    return {"device": _public(dev), "readings": rows}


def day_window(day: str, tz: str, now: Optional[datetime] = None) -> tuple[datetime, datetime, str]:
    """[start, end) in UTC for a local calendar day: 'today', 'yesterday' or YYYY-MM-DD. DST days are 23 or 25 h."""
    zone = ZoneInfo(tz)
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    if day == "today":
        d = today
    elif day == "yesterday":
        d = today - timedelta(days=1)
    else:
        try:
            d = date.fromisoformat(day)
        except ValueError as e:
            raise BadRequest("day must be 'today', 'yesterday' or YYYY-MM-DD") from e
    start = datetime(d.year, d.month, d.day, tzinfo=zone)
    nxt = d + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), f"{d.isoformat()} ({tz})"


def window(start: Optional[str], end: Optional[str], day: Optional[str], tz: str,
           now: Optional[datetime] = None) -> tuple[datetime, datetime, str]:
    now = now or datetime.now(timezone.utc)
    if day:
        return day_window(day, tz, now)
    def parse(s: str) -> datetime:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as e:
            raise BadRequest(f"not an ISO 8601 time: {s!r}") from e
        return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))
    e = parse(end) if end else now
    s = parse(start) if start else e - timedelta(hours=24)
    if s >= e:
        raise BadRequest("start must be before end")
    if e - s > MAX_WINDOW:
        raise BadRequest(f"windows are limited to {MAX_WINDOW.days} days")
    return s.astimezone(timezone.utc), e.astimezone(timezone.utc), f"{s.isoformat()} to {e.isoformat()}"


def stats(conn: psycopg.Connection, org_id: int, device_uuid: str, metric: str, start: datetime, end: datetime) -> dict:
    dev = device(conn, org_id, device_uuid)
    check_metrics(conn, dev, [metric])
    row = conn.execute(
        "select count(*) filter (where quality = 'ok') n, count(*) filter (where quality = 'read_failed') read_failed, "
        "count(*) filter (where quality = 'not_valid') not_valid, avg(value) mean, stddev_samp(value) sd, "
        "min(value) min, max(value) max, min(ts) first, max(ts) last from readings "
        "where device_uuid = %s and metric = %s and ts >= %s and ts < %s", (device_uuid, metric, start, end)).fetchone()
    gap = conn.execute(
        "select percentile_cont(0.5) within group (order by g) median_gap from (select extract(epoch from "
        "ts - lag(ts) over (order by ts)) g from readings where device_uuid = %s and metric = %s and ts >= %s "
        "and ts < %s) x where g is not null", (device_uuid, metric, start, end)).fetchone()["median_gap"]
    rows_total = row["n"] + row["read_failed"] + row["not_valid"]
    expected = (end - start).total_seconds() / gap if gap else None
    m = next(r for r in metric_registry(conn, dev["product"]) if r["key"] == metric)
    return {
        "device_uuid": device_uuid, "metric": metric, "label": m["label"], "unit": m["unit"],
        "window_utc": [start.isoformat(), end.isoformat()], "n": row["n"], "read_failed": row["read_failed"],
        "not_valid": row["not_valid"], "mean": _r(row["mean"]), "sd": _r(row["sd"]), "min": _r(row["min"]),
        "max": _r(row["max"]), "first": row["first"], "last": row["last"],
        "median_interval_s": _r(gap), "coverage_pct": _r(min(100.0, 100.0 * rows_total / expected)) if expected else None,
        "provenance": dev["provenance"], "provenance_note": dev["provenance_note"],
    }


def series(conn: psycopg.Connection, org_id: int, device_uuid: str, metrics: list[str], start: datetime,
           end: datetime, bucket_s: Optional[int] = None) -> dict:
    """Bucketed means (or raw rows when bucket_s = 0), at most MAX_POINTS per metric."""
    dev = device(conn, org_id, device_uuid)
    check_metrics(conn, dev, metrics)
    span = (end - start).total_seconds()
    if bucket_s is None:
        bucket_s = max(60, int(span // MAX_POINTS) + 1)
    if bucket_s == 0:
        rows = conn.execute("select metric, ts, value, quality from readings where device_uuid = %s and metric = any(%s) "
                            "and ts >= %s and ts < %s order by metric, ts limit %s",
                            (device_uuid, metrics, start, end, MAX_POINTS * len(metrics))).fetchall()
        points = [{"metric": r["metric"], "ts": r["ts"], "value": r["value"], "n": 1 if r["quality"] == "ok" else 0}
                  for r in rows]
    else:
        bucket_s = max(bucket_s, int(span // MAX_POINTS) + 1)
        points = conn.execute(
            "select metric, date_bin(make_interval(secs => %s), ts, timestamptz '2000-01-01') ts, avg(value) as value, "
            "count(value) n from readings where device_uuid = %s and metric = any(%s) and ts >= %s and ts < %s "
            "group by 1, 2 order by 1, 2", (bucket_s, device_uuid, metrics, start, end)).fetchall()
    return {"device": _public(dev), "metrics": [m for m in metric_registry(conn, dev["product"]) if m["key"] in metrics],
            "window_utc": [start.isoformat(), end.isoformat()], "bucket_s": bucket_s, "points": points}


def since(conn: psycopg.Connection, org_id: int, device_uuid: str, metrics: list[str], after: datetime) -> list[dict]:
    dev = device(conn, org_id, device_uuid)
    check_metrics(conn, dev, metrics)
    return conn.execute("select metric, ts, value, quality from readings where device_uuid = %s and metric = any(%s) "
                        "and ts > %s order by ts limit 5000", (device_uuid, metrics, after)).fetchall()


def alerts(conn: psycopg.Connection, org_id: int, device_uuid: str, start: datetime, end: datetime) -> list[dict]:
    """Alert raised/cleared transitions, computed from the stored telemetry bodies (ingest stays stateless)."""
    device(conn, org_id, device_uuid)
    rows = conn.execute("select ts, coalesce(body->'alerts', body->'body'->'alerts', '[]'::jsonb) alerts from messages "
                        "where device_uuid = %s and leaf = 'telemetry' and ts >= %s and ts < %s order by ts",
                        (device_uuid, start, end)).fetchall()
    prev: set[str] = set()
    out = []
    for i, r in enumerate(rows):
        cur = {a for a in (r["alerts"] or []) if isinstance(a, str)}
        if i == 0:
            out += [{"ts": r["ts"], "alert": a, "event": "active_at_start"} for a in sorted(cur)]
        else:
            out += [{"ts": r["ts"], "alert": a, "event": "raised"} for a in sorted(cur - prev)]
            out += [{"ts": r["ts"], "alert": a, "event": "cleared"} for a in sorted(prev - cur)]
        prev = cur
    return out


def experiments(conn: psycopg.Connection, org_id: int) -> list[dict]:
    return conn.execute("select id, product, device_uuid, title, crop, started_at, ended_at, data_origin, protocol "
                        "from experiments where org_id = %s order by started_at desc", (org_id,)).fetchall()


def catalog_sources(conn: psycopg.Connection, org_id: int) -> list[dict]:
    return conn.execute(
        "select s.id, s.kind, s.slug, s.title, s.url, s.provenance, s.last_harvest, s.last_error, s.item_count "
        "from catalog_sources s where s.org_id = %s and not exists (select 1 from hidden_content h where "
        "h.org_id = s.org_id and h.kind = 'catalog_source' and h.ref = s.slug) order by s.kind, s.title",
        (org_id,)).fetchall()


def catalog_search(conn: psycopg.Connection, org_id: int, q: Optional[str] = None, species: Optional[str] = None,
                   source: Optional[str] = None, media: Optional[str] = None, limit: int = 60,
                   offset: int = 0) -> dict[str, Any]:
    like = f"%{q.strip()}%" if q and q.strip() else None
    where = ("s.org_id = %(org)s and (%(like)s::text is null or i.title ilike %(like)s or i.species ilike %(like)s "
             "or i.fields::text ilike %(like)s or s.title ilike %(like)s) "
             "and (%(species)s::text is null or i.species ilike %(species)s) "
             "and (%(source)s::text is null or s.slug = %(source)s) "
             "and (%(media)s::text is null or i.media_kind = %(media)s) "
             "and not exists (select 1 from hidden_content h where h.org_id = s.org_id and ((h.kind = 'catalog_source' "
             "and h.ref = s.slug) or (h.kind = 'catalog_item' and h.ref = i.id::text)))")
    p = {"org": org_id, "like": like, "species": species, "source": source, "media": media,
         "limit": max(1, min(limit, 200)), "offset": max(0, offset)}
    total = conn.execute(f"select count(*) n from catalog_items i join catalog_sources s on s.id = i.source_id where {where}",
                         p).fetchone()["n"]
    items = conn.execute(
        "select i.id, i.title, i.species, i.captured_at, i.uploaded_at, i.fields, i.media_url, i.thumb_url, i.media_kind, "
        f"s.slug source, s.title source_title, s.kind source_kind from catalog_items i join catalog_sources s "
        f"on s.id = i.source_id where {where} order by coalesce(i.captured_at, i.uploaded_at) desc nulls last, i.id "
        "limit %(limit)s offset %(offset)s", p).fetchall()
    return {"total": total, "items": items}


def catalog_species(conn: psycopg.Connection, org_id: int, limit: int = 20) -> list[dict]:
    return conn.execute("select i.species, count(*) n from catalog_items i join catalog_sources s on s.id = i.source_id "
                        "where s.org_id = %s and i.species is not null group by 1 order by 2 desc limit %s",
                        (org_id, limit)).fetchall()


def _public(dev: dict) -> dict:
    return {k: dev[k] for k in ("device_uuid", "product", "label", "site", "timezone", "provenance", "provenance_note",
                                "experiment_id")}


def _r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), nd)
