"""Past-experiment catalog: harvest metadata and media links from public Epicollect5 projects and GitHub image
folders (the AstroBotany calibration database's sources) into catalog_items.

    cose-cloud-catalog --org hq [--source <slug>]          (GITHUB_TOKEN raises GitHub's rate limit)

Epicollect5 allows about 5 entry requests a minute, so pages are spaced 13 s apart. The entry mapping (photo,
GPS, species, title) follows the draft app's mapEntry() so both show the same thing.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any, Iterable, Optional

import httpx
import psycopg
import yaml
from psycopg.types.json import Jsonb

from cose_cloud.config import settings
from cose_cloud.db import connect

log = logging.getLogger("cose_cloud.catalog")
EC5 = "https://five.epicollect.net"
EC5_PAGE_GAP_S = 13.0
EC5_PER_PAGE = 500
GITHUB_API = "https://api.github.com"
USER_AGENT = "CoSE-Cloud-catalog/0.1 (+https://github.com/dr-richard-barker/CoSE_Cloud)"
IMAGE_RE = re.compile(r"\.(jpe?g|png|webp|gif|tiff?|bmp)$", re.I)
VIDEO_RE = re.compile(r"\.(avi|mp4|webm|ogv|mov|m4v|mkv)$", re.I)


def sources() -> list[dict]:
    return yaml.safe_load(files("cose_cloud").joinpath("catalog_sources.yaml").read_text())


def register_sources(conn: psycopg.Connection, org_id: int) -> int:
    for s in sources():
        conn.execute(
            "insert into catalog_sources (org_id, kind, slug, title, url, licence, provenance) values (%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (org_id, kind, slug) do update set title = excluded.title, url = excluded.url, "
            "provenance = excluded.provenance",
            (org_id, s["kind"], s["slug"], s["title"], s.get("url"), s.get("licence"), Jsonb(s.get("provenance", {}))))
    return len(sources())


# ------------------------------------------------------------------ Epicollect5 entry mapping (draft mapEntry)
RESERVED = {"ec5_uuid", "created_at", "uploaded_at", "title"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", re.I)
NUMERICISH = re.compile(r"^[\s\d.,%±+/-]+$")
SPECIES_TIERS = [re.compile(p, re.I) for p in (
    r"scientific|\bspecies\b|taxon", r"cultivar|variet", r"genotype|ecotype|accession|line|strain",
    r"speci|(^|[_\s])plant|organism|crop|specimen")]
NOT_SPECIES = re.compile(r"health|status|conditio|appearanc|quality|rating|vigou?r|score|grade|\bstage\b|count|number|"
                         r"amount|\bper\b|height|weight|date|time|note|comment", re.I)
RATING = re.compile(r"^(good|poor|fair|great|excellent|ok|okay|healthy|unhealthy|sick|dead|alive|yes|no|n/?a|none|na|"
                    r"high|med(ium)?|low|normal|abnormal|true|false|present|absent|pass|fail)$", re.I)


def prettify(key: str) -> str:
    key = re.sub(r"^\d+_", "", key)
    return key.replace("_", " ").strip().capitalize()


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(fmt(v) for v in value if fmt(v))
    if isinstance(value, dict):
        return ", ".join(f"{k}: {fmt(v)}" for k, v in value.items() if fmt(v))
    return str(value).strip()


def pick_species(fields: list[dict]) -> Optional[str]:
    for tier in SPECIES_TIERS:
        for f in fields:
            v = f["value"]
            if (v and not NUMERICISH.match(v) and not RATING.match(v.strip())
                    and (tier.search(f["key"]) or tier.search(f["name"]))
                    and not NOT_SPECIES.search(f["key"]) and not NOT_SPECIES.search(f["name"])):
                return v
    return None


def parse_time(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def map_ec5(raw: dict) -> dict:
    photo = None
    lat = lon = None
    fields: list[dict] = []
    for key, value in raw.items():
        if key in RESERVED:
            continue
        if isinstance(value, str) and "/api/media/" in value and "type=photo" in value:
            photo = value
            continue
        if isinstance(value, dict) and "latitude" in value and "longitude" in value:
            try:
                la, lo = float(value["latitude"]), float(value["longitude"])
            except (TypeError, ValueError):
                continue
            if la or lo:
                lat, lon = la, lo
            continue
        text = fmt(value)
        if text:
            fields.append({"key": key, "name": prettify(key), "value": text})
    species = pick_species(fields)
    title, title_key = raw.get("title") or "", None
    if not title or UUID_RE.match(title):
        named = next((f for f in fields if re.search(r"name|title", f["key"], re.I)), None)
        if named:
            title, title_key = named["value"], named["key"]
        elif species:
            title = species
        elif fields:
            title, title_key = fields[0]["value"], fields[0]["key"]
        else:
            title = "(untitled entry)"
    return {
        "external_id": raw["ec5_uuid"], "title": title[:300], "species": species,
        "captured_at": parse_time(raw.get("created_at")), "uploaded_at": parse_time(raw.get("uploaded_at")),
        "fields": [{"name": f["name"], "value": f["value"][:500]} for f in fields if f["key"] != title_key],
        "media_url": photo, "thumb_url": re.sub(r"format=[^&]+", "format=entry_thumb", photo) if photo else None,
        "media_kind": "image" if photo else "none", "lat": lat, "lon": lon,
    }


def ec5_pages(client: httpx.Client, slug: str, gap_s: float = EC5_PAGE_GAP_S) -> Iterable[list[dict]]:
    page = 1
    while True:
        r = client.get(f"{EC5}/api/export/entries/{slug}",
                       params={"per_page": EC5_PER_PAGE, "page": page, "format": "json"})
        if r.status_code == 429:
            log.info("Epicollect5 rate limit; waiting 60 s")
            time.sleep(60)
            continue
        r.raise_for_status()
        body = r.json()
        yield body.get("data", {}).get("entries", [])
        if not body.get("links", {}).get("next"):
            return
        page += 1
        time.sleep(gap_s)


# ------------------------------------------------------------------ GitHub folders with an optional sidecar
def parse_sidecar(name: str, text: str) -> dict[str, dict]:
    """filename -> metadata row, from metadata.csv (any delimiter csv sniffs) or metadata.json (list or mapping)."""
    rows: list[dict] = []
    if name.endswith(".json"):
        data = json.loads(text)
        rows = data if isinstance(data, list) else [{"filename": k, **v} for k, v in data.items() if isinstance(v, dict)]
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    out = {}
    for row in rows:
        clean = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k and v not in (None, "")}
        if clean.get("filename"):
            out[clean["filename"]] = clean
    return out


def map_github(f: dict, meta: Optional[dict]) -> dict:
    meta = meta or {}
    fields = [{"name": prettify(k), "value": v[:500]} for k, v in meta.items() if k not in ("filename", "species")]
    kind = "video" if VIDEO_RE.search(f["name"]) else "image"
    return {
        "external_id": f["path"], "title": meta.get("title") or f["name"], "species": meta.get("species"),
        "captured_at": parse_time(meta.get("date_taken")), "uploaded_at": None, "fields": fields,
        "media_url": f.get("download_url"), "thumb_url": f.get("download_url") if kind == "image" else None,
        "media_kind": kind, "lat": None, "lon": None,
    }


def github_items(client: httpx.Client, slug: str) -> list[dict]:
    owner, repo, ref, path = slug.split("/", 3)
    r = client.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
    r.raise_for_status()
    listing = [x for x in r.json() if x.get("type") == "file"]
    meta: dict[str, dict] = {}
    side = next((x for x in listing if x["name"].lower() in ("metadata.csv", "metadata.json")), None)
    if side is not None:
        meta = parse_sidecar(side["name"].lower(), client.get(side["download_url"]).text)
    return [map_github(x, meta.get(x["name"])) for x in listing if IMAGE_RE.search(x["name"]) or VIDEO_RE.search(x["name"])]


# ------------------------------------------------------------------ storing
def upsert_items(conn: psycopg.Connection, source_id: int, items: list[dict]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "insert into catalog_items (source_id, external_id, title, species, captured_at, uploaded_at, fields, "
            "media_url, thumb_url, media_kind, lat, lon) values (%(source_id)s, %(external_id)s, %(title)s, %(species)s, "
            "%(captured_at)s, %(uploaded_at)s, %(fields)s, %(media_url)s, %(thumb_url)s, %(media_kind)s, %(lat)s, %(lon)s) "
            "on conflict (source_id, external_id) do update set title = excluded.title, species = excluded.species, "
            "captured_at = excluded.captured_at, uploaded_at = excluded.uploaded_at, fields = excluded.fields, "
            "media_url = excluded.media_url, thumb_url = excluded.thumb_url, media_kind = excluded.media_kind, "
            "lat = excluded.lat, lon = excluded.lon",
            [{**it, "source_id": source_id, "fields": Jsonb(it["fields"])} for it in items])
    return len(items)


def harvest(conn: psycopg.Connection, org_slug: str, only: Optional[str] = None,
            client: Optional[httpx.Client] = None, ec5_gap_s: float = EC5_PAGE_GAP_S) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    client = client or httpx.Client(headers=headers, timeout=60.0, follow_redirects=True)
    rows = conn.execute("select s.id, s.kind, s.slug from catalog_sources s join orgs o on o.id = s.org_id "
                        "where o.slug = %s and (%s::text is null or s.slug = %s) and s.kind in ('ec5', 'github') "
                        "order by s.id", (org_slug, only, only)).fetchall()
    conn.commit()
    report: dict[str, Any] = {}
    for src in rows:
        try:
            if src["kind"] == "ec5":
                items = [map_ec5(e) for page in ec5_pages(client, src["slug"], ec5_gap_s) for e in page]
            else:
                items = github_items(client, src["slug"])
            with conn.transaction():
                n = upsert_items(conn, src["id"], items)
                conn.execute("update catalog_sources set last_harvest = now(), last_error = null, item_count = "
                             "(select count(*) from catalog_items where source_id = %s) where id = %s",
                             (src["id"], src["id"]))
            report[src["slug"]] = n
            log.info("%s %s: %d items", src["kind"], src["slug"], n)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            with conn.transaction():
                conn.execute("update catalog_sources set last_error = %s where id = %s", (str(e)[:500], src["id"]))
            report[src["slug"]] = f"error: {e}"
            log.warning("%s %s failed: %s", src["kind"], src["slug"], e)
        if src["kind"] == "ec5":
            time.sleep(ec5_gap_s)
    return report


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Harvest the past-experiment catalog (metadata and links only).")
    ap.add_argument("--org", default="hq")
    ap.add_argument("--source", help="harvest only this slug")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with connect(settings().database_url) as conn:
        print(json.dumps(harvest(conn, a.org, a.source), indent=1))


if __name__ == "__main__":
    main()
