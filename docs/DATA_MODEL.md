# Data model

## Ingest: `normalise(topic, payload, received_at, device)`

Pure, never raises, no I/O (`packages/ingest_core`). The Mosquitto subscriber, the simulator backfill and an AWS IoT rule → Lambda path all call it.

- **Topic.** `cose/v1/devices/{uuid}/{leaf}`. Wildcards and extra levels are rejected. `commands` and `ota` are never ingested.
- **Identity comes from the topic**, which the broker ties to the client certificate's CN. A `device_id` inside a payload is kept as `payload_device_id` and never trusted; the simulator's says `sim-xseed-0`. An envelope whose `device_uuid` disagrees with its topic is rejected.
- **Unknown devices are rejected.** There is no auto-registration.
- **Provenance comes from the registry**, never the payload: `hardware` → measured, `simulator` → simulated, `replay` → replay. A database trigger refuses any reading or message whose provenance disagrees with its device's `data_origin`.
- **Shapes accepted on `telemetry`:**
  - **envelope**: proposal v0.1, the body validated by its product schema;
  - **xseed_fw**: the XSeed firmware payload;
  - **xseed_contract**: CoSE-Care-Agent contract v0.3, which is the firmware payload plus `seq`, `mode` and `active_overrides`, and is what the simulator sends. A v0.2 payload validates too: v0.3 only adds the mode `MAINTENANCE`.
  The firmware schema rejects the contract shape (`additionalProperties: false`), so each is validated against its own schema.
- **Other leaves without an envelope** (`state`, `alerts`, `acks`) are stored as `raw`, with no readings.
- **Limits.** 128 KiB payloads, matching AWS IoT Core. Device clocks more than a day ahead of the server are rejected.

## Null vs omitted (an open decision, kept open)

DATA_INTEGRATION_SPEC §3.2 leaves the rule open: XSeed and Care-Agent send `null` for a failed read, while soilSENSE omits absent values. CoSE Cloud keeps both meanings without choosing:

- **A JSON null** becomes a reading with no value. Its quality is the metric's declared null meaning:
  - `read_failed` for XSeed sensors;
  - `not_valid` for canopy metrics, which are null until the canopy is valid.
- **An omitted field** produces no reading.

Raw messages are kept, so a later decision means re-normalising stored messages, not losing data.

## Tables (`services/src/cose_cloud/migrations/0001_init.sql`)

| Group | Tables |
| :- | :- |
| Accounts | `orgs`, `users` (argon2id), `memberships` (viewer/analyst/admin), `identities` (M2), `sessions` (token sha256 only), `platform_admins`, `hidden_content` (moderation, ported from the draft's Supabase schema) |
| Plans | `entitlements` (tier, features, `llm_mode`, `llm_monthly_cap_usd`; no prices), `platform_settings` |
| Registry | `sites` (time zone), `devices` (spec §3.6 fields + `data_origin`, `sim_meta`), `experiments` |
| Device data | `messages` (jsonb body, sha256; a QoS 1 redelivery is stored once), `readings` (one number per device/metric/time, quality, provenance), `metrics` (label, unit, kind, null meaning), `ingest_rejects` |
| Catalog | `catalog_sources`, `catalog_items` (metadata and links only) |
| Agent | `conversations`, `conversation_messages` (append-only, provider format), `conversation_turns` (what the user saw), `datasets`, `chart_artifacts`, `usage_ledger` |

Plain Postgres 17 with only the `citext` extension, so the same migrations run on Amazon RDS. BRIN indexes on time; no partitioning in M1. Ingest is stateless: alert raised/cleared transitions are computed at query time from stored bodies.

## Time

- Stored in UTC.
- "Today" and "yesterday" are calendar days in the device site's time zone (default America/Chicago).
- A day is 23 or 25 hours on daylight-saving changes; a test covers Sun 1 Nov 2026.

## Exports

- **CSV:**
  - one row per metric and time bucket, with a `provenance` column on every row;
  - a simulated export's filename ends in `_SIMULATED`.
- **RO-Crate 1.1 zip** (spec §3.4):
  - files: `samples.csv`, `events.csv`, `calibration.json`, `metadata.json` and `ro-crate-metadata.json`;
  - each file listed with its size and SHA-256;
  - labelled **"GeneLab-aligned (unconfirmed)"** until a GeneLab curator confirms the mapping.

## Known gaps in the shared spec (to raise with its owner)

- The envelope's `product` enum has no Ground Rover, though the rover is the one product whose design already uses the envelope (its spec says `ground-rover`).
- The envelope's `mode` examples (`recipe`, `override`, `safe`) differ from the XSeed contract's (`RUN`, `FAULT`).
- The rover's `station` leaf is not among Care-Agent's device leaves, so the broker rules would deny it. M4 adds it.
