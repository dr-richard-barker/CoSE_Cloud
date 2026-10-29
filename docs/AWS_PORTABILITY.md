# Moving to AWS IoT Core (M7)

The HQ stack is built so the move replaces parts without rewriting them.

| Part | At HQ (M1) | On AWS | Status |
| :- | :- | :- | :- |
| Broker | Mosquitto 2, mutual TLS, CN = username | AWS IoT Core | to build |
| Ingest | `cose-cloud-ingest` → `normalise()` → `store.write()` | IoT rule → Lambda (`deploy/aws/lambda_handler.py`) → the same functions | shim written, test covers the event adapter |
| Database | Postgres 17, `citext` only | Amazon RDS for PostgreSQL, same migrations | to verify |
| Registry | `devices` table | `devices` table + IoT Things (UUID = thing name), attributes mirrored | to build |
| API, web | Docker on the HQ server | containers on ECS/App Runner or the same server | unchanged code |

## Choices already made for portability

- **QoS 1 only.** No QoS 2 anywhere.
- **Client ID = device UUID = certificate CN.** Care-Agent's transport currently adds a random suffix to client IDs; devices must use their UUID before M7.
- **Payloads ≤ 128 KiB.** `normalise()` rejects larger ones, and the broker's `max_packet_size` (132096 bytes: 128 KiB plus 1 KiB for the packet header) matches.
- **The rule must pass the payload bytes unchanged** (`encode(*, 'base64')`), so the sha256 dedupe is the same on both paths.
- **No Postgres extensions** other than `citext`; no TimescaleDB.

## To verify against AWS documentation before relying on them

These are checks, not facts. Each needs the current AWS IoT Core quotas and documentation page cited when M7 starts.

1. Maximum forward slashes and length of a topic. Today's tree uses 4 slashes (`cose/v1/devices/{uuid}/{leaf}`). XSeed-µg's planned `modules/{n}/{leaf}` subtree (XSeed `docs/06_SOFTWARE_IOT_SPEC.md` §8.1) would use 6.
2. Retained messages: whether, how many, size, and billing, before a retained `state` leaf is relied on.
3. The keepalive range. Care-Agent uses 30 s.
4. Delivery guarantees: at-least-once, possibly out of order. Ingest already dedupes by sha256 and orders by device timestamp.
5. Registering CoSE's own CA, and how device certificates map to Things.
6. Rewriting the Mosquitto ACL (`%u` patterns) as IoT policies with policy variables on the thing name or client ID. The rule that no CoSE Cloud identity may publish `commands` must carry over.
7. The rule SQL `SELECT encode(*, 'base64') AS payload_b64, topic() AS topic, timestamp() AS received_ms FROM 'cose/v1/devices/+/+'`. Confirm `encode(*, 'base64')` yields the original bytes for JSON payloads.
8. RDS: Postgres 17 availability in the chosen region, and `citext` support.
