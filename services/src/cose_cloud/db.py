"""Database connection and the migration runner (plain SQL files, applied once each, in name order)."""

from __future__ import annotations

from importlib.resources import files

import psycopg
from psycopg.rows import dict_row


def connect(url: str, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row, autocommit=autocommit)


def migrations() -> list[tuple[str, str]]:
    folder = files("cose_cloud").joinpath("migrations")
    return sorted((p.name, p.read_text()) for p in folder.iterdir() if p.name.endswith(".sql"))


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply every migration not yet recorded. Returns the names applied."""
    applied = []
    with conn.transaction():
        conn.execute("create table if not exists schema_migrations "
                     "(name text primary key, applied_at timestamptz not null default now())")
        conn.execute("select pg_advisory_xact_lock(4207)")   # one migrator at a time
        done = {r["name"] for r in conn.execute("select name from schema_migrations")}
        for name, sql in migrations():
            if name in done:
                continue
            conn.execute(sql)
            conn.execute("insert into schema_migrations (name) values (%s)", (name,))
            applied.append(name)
    return applied
