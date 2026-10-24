# Architecture

## Decisions (Richard, 24 Oct 2026)

| Question | Decision |
| :- | :- |
| Model for CoSE_Agent | **Hybrid.** Subscribers get hosted Claude through the CoSE backend, metered per organisation. A local open model serves offline use and HQ. Device commands go only through CoSE-Care-Agent's leased-override contract and its safety layer. |
| Where the code lives | **This repository.** The public Hub keeps working beside the platform. |
| Backend | **Self-hosted at HQ** on Docker Compose (Postgres, Mosquitto, Python API), built so it can move to AWS IoT Core. |
| Milestone 1 | **HQ edition plus XSeed edition on simulated data.** The agent is read-only. |
| Avatar | **CoSE logo orb** in M1. This was the default; a character design is M6. |

## Layout

```
index.html .nojekyll Hub/      public project hub (GitHub Pages; pages.yml publishes only these)
apps/web/                      React 19 + Vite 6 web app: editions, dashboards, catalog, CoSE_Agent + avatar
packages/ingest_core/          normalise(): (topic, payload) -> message + readings. Pure; shared with AWS Lambda
services/src/cose_cloud/       API, ingest service, simulator, catalog harvester, agent, migrations, editions
deploy/compose/                docker-compose.yml, broker config + ACL, dev PKI script, Dockerfiles, Caddyfile
deploy/aws/                    Lambda shim for an IoT Core rule (M7; not deployed)
tests/e2e/                     whole-stack test and the scripted model server it uses
```

Migrations and edition profiles live inside the package (`services/src/cose_cloud/migrations`, `…/editions`), so an installed image carries them.

## Editions and tiers

One web app and one API serve every edition. An edition is a YAML profile (`editions/*.yaml`, schema-checked on load) listing:

- its products and panels;
- the agent tools it allows;
- for planned editions, the data source as designed and what the hardware still needs.

The URL picks the edition: `#/hq`, `#/xseed`, `#/rover`, `#/drone` or `#/sense`.

Tiers are entitlement flags per organisation (`entitlements`: tier, `llm_mode`, monthly cap), with no prices in code.

| Tier | What it gets |
| :- | :- |
| **Free, with hardware** | The customer runs this stack. Dashboards, merge and export, and the read-only agent on a local model if they have one. |
| **Subscription ("talk with my CoSE device")** | A CoSE-hosted instance: hosted Claude, automations (M2), supervised device actions (M3). |
| **Institutional** | Multi-user organisations. |

Prices are not decided. The three cloud prices in CoSE's documents conflict, and the SaaS model is being rebuilt for NSF PESOSE (`Market_Research/products/software_suite.md`, `OPEN_DECISIONS.md` in CoSE_tools). That is phase M2a.

## Phases

| # | Delivers | Waits on |
| :- | :- | :- |
| **M1** | HQ + XSeed (simulated), ingest, registry, catalog, read-only agent, avatar orb, CSV + RO-Crate | done on `feat/platform-m1` |
| M2 | Organisations UI, entitlements, cap UI, scheduled and triggered automations, Google sign-in, billing hook, CyVerse/YouTube sources | M2a |
| M2a | Pricing research: reconcile the conflicting prices; research ZENTRA Cloud, Aranet Cloud, HOBOlink, DJI FlightHub, John Deere Operations Center, DroneDeploy, Growlink, Arable | — |
| M3 | Supervised device actions through Care-Agent (XSeed, then AlgaFlux) | XSeed hardware |
| M4 | Rover, senSE and drone editions live, with bridges per DATA_INTEGRATION_SPEC §3.3 | units with networking |
| M5 | SciSpinner edition (log format from Technical Reference Rev 1.2) | the PDFs read |
| M6 | Avatar character and voice | design call |
| M7 | Tested AWS IoT Core path; security review before internet exposure | — |

## Dependencies

- **CoSE-Care-Agent v0.1.1** (`../CoSE_tools/CoSE-Care-Agent`).
  - What CoSE Cloud uses from it: the simulator (SimPod, SimDevice), the topic tree and broker rules, the model providers (Anthropic, local, fake), and the cost meter with its sourced `pricing.yaml`.
  - Development uses an editable path dependency. Images install the wheel that `make wheels` builds.
  - It has no remote yet. Once its GitHub repository exists, switch `[tool.uv.sources]` to a git source pinned by tag, and add the services tests to CI.
- **The data spec:** `CoSE_tools/CoSE_Ecosystem/docs/DATA_INTEGRATION_SPEC.md` (proposal v0.1).
  - CoSE Cloud implements its topic tree, envelope, device registry (§3.6) and RO-Crate bundle (§3.4), and becomes the registry's owner.
  - Its schema files are copied verbatim into `packages/ingest_core/.../schemas/` with sha256 and source commit, and a test compares them.
- **The AstroBotany calibration database** stays live and unchanged. Its source list and entry mapping were ported into the catalog harvester. It remains the place for image viewing and marker analysis, and is linked as a tool.
