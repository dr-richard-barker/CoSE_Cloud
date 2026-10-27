# Security

## M1 exposure

M1 runs on the HQ network or a VPN only.

- Compose binds Caddy (8428) and Mosquitto (8883) to 127.0.0.1 unless `HTTP_BIND` / `MQTT_BIND` say otherwise.
- **Before anything is reachable from the internet** (the subscription service):
  - TLS on Caddy;
  - `COSE_COOKIE_SECURE=true`;
  - rate limits on sign-in;
  - an external review.

  That review belongs in M7.

## Identities

| Who | How | May |
| :- | :- | :- |
| A device | client certificate, CN = device UUID | publish its own `telemetry`, `acks`, `state`, `alerts`; subscribe to its own `commands` |
| Ingest service | client certificate `cose-cloud-ingest` | read every device's reports; write nothing |
| API | no broker identity at all | read the database, call the model provider |
| Users | email + argon2id password; HttpOnly SameSite=Lax session cookie; only the token's sha256 is stored | their organisation's data, by role |

- No CoSE Cloud identity may write `commands` in M1. `deploy/compose/mosquitto/acl` is generated (`make acl`), and a test checks it.
- A test checks that the API process never imports the MQTT client.
- Device UUIDs may not equal a broker user name: Mosquitto's `pattern` lines apply to every user.

## Organisation isolation

Every query filters on the organisation from the session; agent tools get it from the server. Tests cover this:

- one organisation cannot see another's devices, readings, datasets or catalog, through the API or any agent tool that takes a device, dataset or search (`services/tests/test_api.py`: `test_another_org_gets_404`, `test_another_orgs_dataset_gets_404`, `test_the_catalog_is_per_organisation`; `services/tests/test_agent.py`: `test_other_orgs_devices_are_invisible_to_tools`, `test_other_orgs_readings_datasets_and_catalog_are_invisible_to_tools`);
- a conversation is visible only to the user who started it, not to a colleague in the same organisation or to another organisation (`test_a_conversation_is_visible_only_to_its_starter`).

## Model safety

See docs/AGENT.md. In short:

- read-only tools;
- third-party text returned as `untrusted_text`;
- chart specs and the chat renderer refuse links, data URLs and images;
- hosted spend is capped per organisation and globally, with an off switch.

## Web

Caddy sends:

- `Content-Security-Policy: script-src 'self'`, with no `unsafe-eval`; charts use Vega's expression interpreter for this;
- `frame-ancestors 'none'`;
- `Referrer-Policy: no-referrer`;
- `X-Content-Type-Options: nosniff`.

Catalog images load from their own hosts with no referrer.

## Secrets

- `.env`, `deploy/dev.env`, `deploy/compose/e2e.env`, `deploy/compose/pki/` and the built wheels are git-ignored.
- `make pki` makes **development** certificates only, with readable keys. A production CA lives off the server, and device keys are generated on the device.
- Passwords are read from environment variables, never from the command line.
