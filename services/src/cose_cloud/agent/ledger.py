"""Spend control for hosted models: reserve the worst case before a call, settle the actual cost after it.

The check runs under transaction-scoped advisory locks (global, then the org), so concurrent questions cannot
together pass a cap that each would pass alone. Prices come from CoSE-Care-Agent's sourced pricing.yaml via its
cost_usd(); a model with no listed price fails closed before the call. If a server-side fallback is served by an
unlisted model, it is charged at the highest listed rate and the row says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import psycopg
from cose_care_agent.agent.cost import PRICING, cost_usd
from cose_care_agent.agent.providers.base import Usage
from cose_care_agent.provenance import load

GLOBAL_LOCK = 4211
ORG_LOCK_BASE = 4_212_000_000
CHARS_PER_TOKEN = 3.0          # deliberately low (overestimates tokens) for the worst-case reservation


class CapReached(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    id: Optional[int]
    provider: str
    model: str
    worst_usd: float


def prices() -> dict:
    return load(PRICING)[0]


def worst_case_usd(model: str, request_chars: int, max_tokens: int) -> float:
    est_in = int(request_chars / CHARS_PER_TOKEN) + 1
    return cost_usd(model, Usage(input_tokens=0, output_tokens=max_tokens, cache_write_tokens=est_in))


def _max_rate_cost(u: Usage) -> float:
    pr = prices()
    worst = max(pr["models"].values(), key=lambda m: m["output"])
    return (u.input_tokens * worst["input"] + u.cache_write_tokens * worst["input"] * pr["cache_write_mult"]
            + u.cache_read_tokens * worst["input"] + u.output_tokens * worst["output"]) / 1e6


def month_spend(conn: psycopg.Connection, org_id: Optional[int] = None) -> float:
    row = conn.execute("select coalesce(sum(cost_usd), 0) s from usage_ledger where created_at >= "
                       "date_trunc('month', now()) and (%s::bigint is null or org_id = %s)", (org_id, org_id)).fetchone()
    return float(row["s"])


def record_free(conn: psycopg.Connection, *, org_id: int, user_id: int, conversation_id, provider: str, model: str,
                served_model: str, usage: Usage, note: str) -> None:
    conn.execute(
        "insert into usage_ledger (org_id, user_id, conversation_id, provider, requested_model, served_model, "
        "input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, cost_usd, pricing_src, kind) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,'actual')",
        (org_id, user_id, conversation_id, provider, model, served_model, usage.input_tokens, usage.output_tokens,
         usage.cache_write_tokens, usage.cache_read_tokens, note))


def reserve(conn: psycopg.Connection, *, org_id: int, user_id: int, conversation_id, model: str, request_chars: int,
            max_tokens: int, org_cap_usd: Optional[float], global_cap_usd: Optional[float]) -> Reservation:
    """Insert a worst-case reservation, or raise CapReached. Commits its own transaction."""
    try:
        worst = worst_case_usd(model, request_chars, max_tokens)
    except KeyError as e:
        raise CapReached(f"no listed price for {model}: hosted calls fail closed ({e})") from e
    if org_cap_usd is None:
        raise CapReached("this organisation has no monthly cap for the hosted model, so hosted calls are off")
    with conn.transaction():
        conn.execute("select pg_advisory_xact_lock(%s)", (GLOBAL_LOCK,))
        conn.execute("select pg_advisory_xact_lock(%s)", (ORG_LOCK_BASE + org_id,))
        if global_cap_usd is not None and month_spend(conn) + worst > global_cap_usd:
            raise CapReached(f"CoSE's monthly hosted-model budget (${global_cap_usd:.2f}) would be exceeded")
        spent = month_spend(conn, org_id)
        if spent + worst > org_cap_usd:
            raise CapReached(f"this month's hosted-model cap (${org_cap_usd:.2f}) would be exceeded: "
                             f"${spent:.4f} spent, next call reserves up to ${worst:.4f}")
        row = conn.execute(
            "insert into usage_ledger (org_id, user_id, conversation_id, provider, requested_model, cost_usd, "
            "pricing_src, kind) values (%s,%s,%s,'anthropic',%s,%s,%s,'reserve') returning id",
            (org_id, user_id, conversation_id, model, Decimal(f"{worst:.6f}"),
             json.dumps({"reserved": "worst case", "request_chars": request_chars, "max_tokens": max_tokens}))).fetchone()
    return Reservation(row["id"], "anthropic", model, worst)


def settle(conn: psycopg.Connection, res: Reservation, served_model: Optional[str], usage: Optional[Usage]) -> float:
    """Replace the reservation with the actual cost. With no usage (the call failed), keep the worst case."""
    if usage is None:
        cost, src = res.worst_usd, "call failed: worst-case reservation kept"
    else:
        try:
            cost, src = cost_usd(served_model or res.model, usage), "Care-Agent pricing.yaml"
        except KeyError:
            cost, src = _max_rate_cost(usage), f"{served_model} has no listed price: charged at the highest listed rate"
    u = usage or Usage()
    with conn.transaction():
        conn.execute(
            "update usage_ledger set kind = 'actual', served_model = %s, input_tokens = %s, output_tokens = %s, "
            "cache_write_tokens = %s, cache_read_tokens = %s, cost_usd = %s, pricing_src = %s where id = %s",
            (served_model, u.input_tokens, u.output_tokens, u.cache_write_tokens, u.cache_read_tokens,
             Decimal(f"{cost:.6f}"), src, res.id))
    return cost
