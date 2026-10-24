"""Admin commands.

    cose-cloud migrate
    cose-cloud seed --admin-email you@example.org          (password from $COSE_ADMIN_PASSWORD)
    cose-cloud create-user --org hq --email someone@example.org --role analyst   (password from $COSE_NEW_PASSWORD)
    cose-cloud register-device --org hq --device xseed-0001 --product xseed --origin hardware
    cose-cloud acl                                          (the broker access rules, to stdout)
"""

from __future__ import annotations

import argparse
import os
import sys

from cose_cloud import auth, catalog, store
from cose_cloud.broker_acl import acl_text
from cose_cloud.config import settings
from cose_cloud.db import connect, migrate


def _password(var: str) -> str:
    pw = os.environ.get(var)
    if not pw:
        raise SystemExit(f"set ${var} to the password (it is never taken on the command line)")
    return pw


def cmd_migrate(conn, a) -> None:
    applied = migrate(conn)
    with conn.transaction():
        n = store.seed_metrics(conn)
    print(f"applied {applied or 'nothing new'}; {n} metric rows")


def cmd_seed(conn, a) -> None:
    with conn.transaction():
        org = conn.execute("insert into orgs (slug, name) values (%s,%s) on conflict (slug) do update "
                           "set name = excluded.name returning id", (a.org, a.org_name)).fetchone()
        conn.execute("insert into sites (org_id, name, kind, timezone) values (%s,%s,'hq',%s) "
                     "on conflict (org_id, name) do update set timezone = excluded.timezone",
                     (org["id"], a.site, a.timezone))
        conn.execute("insert into entitlements (org_id, tier, llm_mode, llm_monthly_cap_usd) values (%s,%s,%s,%s) "
                     "on conflict (org_id) do update set tier = excluded.tier, llm_mode = excluded.llm_mode, "
                     "llm_monthly_cap_usd = excluded.llm_monthly_cap_usd, updated_at = now()",
                     (org["id"], a.tier, a.llm_mode, a.llm_cap))
        uid = auth.create_user(conn, email=a.admin_email, password=_password("COSE_ADMIN_PASSWORD"),
                               org_id=org["id"], role="admin", display_name=a.admin_name)
        conn.execute("insert into platform_admins (user_id) values (%s) on conflict do nothing", (uid,))
        n = catalog.register_sources(conn, org["id"])
    print(f"org {a.org} (id {org['id']}), site {a.site} ({a.timezone}), admin {a.admin_email}, "
          f"llm {a.llm_mode} cap {a.llm_cap}, {n} catalog sources")


def cmd_create_user(conn, a) -> None:
    with conn.transaction():
        org = conn.execute("select id from orgs where slug = %s", (a.org,)).fetchone()
        if org is None:
            raise SystemExit(f"no org {a.org!r}")
        uid = auth.create_user(conn, email=a.email, password=_password("COSE_NEW_PASSWORD"), org_id=org["id"],
                               role=a.role, display_name=a.name)
    print(f"user {a.email} (id {uid}) is {a.role} in {a.org}")


def cmd_register_device(conn, a) -> None:
    with conn.transaction():
        org = conn.execute("select id from orgs where slug = %s", (a.org,)).fetchone()
        if org is None:
            raise SystemExit(f"no org {a.org!r}")
        store.register_device(conn, device_uuid=a.device, org_id=org["id"], product=a.product,
                              data_origin=a.origin, label=a.label, variant=a.variant)
    print(f"registered {a.device} ({a.product}, {a.origin}) in {a.org}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="cose-cloud", description="CoSE Cloud admin commands")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations and the metric registry")
    s = sub.add_parser("seed", help="create the HQ org, its site, entitlements, admin and catalog sources")
    s.add_argument("--org", default="hq")
    s.add_argument("--org-name", default="CoSE HQ")
    s.add_argument("--site", default="Madison HQ")
    s.add_argument("--timezone", default="America/Chicago")
    s.add_argument("--tier", default="institutional", choices=("free", "pro", "institutional"))
    s.add_argument("--llm-mode", default="off", choices=("hosted", "local", "off"))
    s.add_argument("--llm-cap", type=float, default=None, help="monthly hosted-model cap in USD")
    s.add_argument("--admin-email", required=True)
    s.add_argument("--admin-name")
    u = sub.add_parser("create-user")
    u.add_argument("--org", default="hq")
    u.add_argument("--email", required=True)
    u.add_argument("--name")
    u.add_argument("--role", default="analyst", choices=("viewer", "analyst", "admin"))
    d = sub.add_parser("register-device")
    d.add_argument("--org", default="hq")
    d.add_argument("--device", required=True)
    d.add_argument("--product", required=True, choices=store.PRODUCTS)
    d.add_argument("--origin", required=True, choices=("hardware", "simulator", "replay"))
    d.add_argument("--label")
    d.add_argument("--variant")
    sub.add_parser("acl", help="print the broker access rules")
    a = ap.parse_args(argv)
    if a.cmd == "acl":
        sys.stdout.write(acl_text())
        return
    with connect(settings().database_url) as conn:
        {"migrate": cmd_migrate, "seed": cmd_seed, "create-user": cmd_create_user,
         "register-device": cmd_register_device}[a.cmd](conn, a)


if __name__ == "__main__":
    main()
