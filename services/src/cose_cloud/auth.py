"""Accounts and sessions. M1: accounts are created by an admin on the command line; the service is reached over
the HQ LAN or VPN only. Passwords are argon2id hashes; a session cookie holds a random token whose sha256 is
the only thing stored."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()   # argon2id with the library's current defaults
MIN_PASSWORD = 12


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    display_name: Optional[str]
    org_id: int
    org_slug: str
    org_name: str
    role: str


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"passwords need at least {MIN_PASSWORD} characters")
    return _ph.hash(password)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(conn: psycopg.Connection, *, email: str, password: Optional[str], org_id: int, role: str,
                display_name: Optional[str] = None) -> int:
    row = conn.execute(
        "insert into users (email, display_name, password_hash) values (%s,%s,%s) on conflict (email) do update "
        "set display_name = coalesce(excluded.display_name, users.display_name), "
        "password_hash = coalesce(excluded.password_hash, users.password_hash) returning id",
        (email, display_name, hash_password(password) if password else None)).fetchone()
    conn.execute("insert into memberships (org_id, user_id, role) values (%s,%s,%s) "
                 "on conflict (org_id, user_id) do update set role = excluded.role", (org_id, row["id"], role))
    return row["id"]


def login(conn: psycopg.Connection, email: str, password: str, days: int) -> Optional[str]:
    """A new session token, or None. The same answer and roughly the same time for a wrong email or password."""
    row = conn.execute("select u.id, u.password_hash, u.banned, m.org_id from users u join memberships m "
                       "on m.user_id = u.id where u.email = %s order by m.org_id limit 1", (email,)).fetchone()
    stored = row["password_hash"] if row and row["password_hash"] else _DUMMY
    try:
        _ph.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return None
    if row is None or row["banned"] or stored is _DUMMY:
        return None
    token = secrets.token_urlsafe(32)
    conn.execute("insert into sessions (token_sha256, user_id, org_id, expires_at) values (%s,%s,%s,%s)",
                 (_sha(token), row["id"], row["org_id"], datetime.now(timezone.utc) + timedelta(days=days)))
    return token


def principal(conn: psycopg.Connection, token: Optional[str]) -> Optional[Principal]:
    if not token:
        return None
    row = conn.execute(
        "select u.id user_id, u.email, u.display_name, o.id org_id, o.slug org_slug, o.name org_name, m.role "
        "from sessions s join users u on u.id = s.user_id join orgs o on o.id = s.org_id "
        "join memberships m on m.user_id = u.id and m.org_id = o.id "
        "where s.token_sha256 = %s and s.expires_at > now() and not u.banned", (_sha(token),)).fetchone()
    return Principal(**row) if row else None


def logout(conn: psycopg.Connection, token: Optional[str]) -> None:
    if token:
        conn.execute("delete from sessions where token_sha256 = %s", (_sha(token),))


_DUMMY = _ph.hash(secrets.token_urlsafe(16))   # verified against when the email is unknown, to even out timing
