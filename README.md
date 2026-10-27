# CoSE Cloud

CoSE Cloud is where data from Collaborative Science Environment Inc. (CoSE) instruments is accessed, analysed, visualised, merged and exported. **CoSE_Agent** sits at its centre: an AI assistant that answers questions about the data, draws charts and prepares exports. It speaks through **CoSE_Agent_Avatar**.

There is one codebase with five editions:

- **HQ:** every instrument and past experiment, merged.
- **XSeed**
- **Ground Rover**
- **Cozy Canopy drone**
- **senSE**

This repository also serves the public **project hub** at <https://dr-richard-barker.github.io/CoSE_Cloud/Hub/>. The root `index.html` redirects there. Only `index.html`, `.nojekyll` and `Hub/` are published to GitHub Pages (`.github/workflows/pages.yml`). The platform code runs at CoSE HQ and is never served from Pages.

## Status: Milestone 1 (October 2026)

| Edition | State |
| :- | :- |
| **HQ** | **Live.** Fleet, experiments, and a past-experiment catalog of 16 sources: the AstroBotany calibration database's Epicollect5 projects and GitHub image collections. Also the analysis tools and CoSE_Agent. |
| **XSeed** | **Live on simulated data.** No XSeed unit has been built. A simulated XSeed runs on the broker: CoSE-Care-Agent's SimPod, which is the XSeed firmware core plus plant physics. Every value it produces is stored, charted, exported and spoken as **simulated**. |
| **Ground Rover, drone, senSE** | **Planned shells.** Their hardware has no networking yet; each page says what it needs. They show no readings, simulated or otherwise. |

CoSE_Agent is read-only in M1: it cannot command devices. Supervised device actions are M3; they will go through CoSE-Care-Agent's safety layer, never straight from the chat model.

## How it fits together

```
devices ──MQTTS 8883 (client certificates)──▶ Mosquitto ──▶ ingest ──▶ Postgres ◀── catalog harvester
                                                                          │            (Epicollect5, GitHub)
browser ──▶ Caddy :8428 ── web app + /api ──▶ API ── CoSE_Agent ── Claude (hosted) | local model | off
```

The rest is in `docs/`:

- [ARCHITECTURE](docs/ARCHITECTURE.md): the layout, editions, tiers, phases and dependencies.
- [DATA_MODEL](docs/DATA_MODEL.md): tables, ingest rules, provenance, null vs omitted, and exports.
- [AGENT](docs/AGENT.md): tools, model choice, the spend cap, safety and the avatar.
- [AWS_PORTABILITY](docs/AWS_PORTABILITY.md): the move to AWS IoT Core, with what is still to verify.
- [SECURITY](docs/SECURITY.md): the M1 exposure, secrets, and what must happen before internet exposure.

## Run it at HQ (Docker)

```bash
make wheels                       # CoSE-Care-Agent wheel + pinned requirements (needs ../CoSE-Care-Agent)
make pki                          # throwaway development certificates (never production)
cp deploy/compose/.env.example deploy/compose/.env   # then edit the passwords and the agent mode
docker compose -f deploy/compose/docker-compose.yml up -d --build
docker compose -f deploy/compose/docker-compose.yml --profile seed run --rm seed     # HQ org, admin, 6-day backfill
docker compose -f deploy/compose/docker-compose.yml --profile sim up -d sim          # live simulated XSeed
docker compose -f deploy/compose/docker-compose.yml --profile catalog run --rm catalog
```

Then open <http://localhost:8428>. To add users: `docker compose … exec api cose-cloud create-user --org hq --email … --role analyst`, with the password in `$COSE_NEW_PASSWORD`.

## Develop and test

```bash
uv sync --python 3.11             # workspace venv (.venv); CoSE-Care-Agent is a sibling path dependency
make check                        # Python tests (a throwaway Postgres 17 on :54329) + web type-check and tests
make e2e                          # the whole stack in Docker: broker, live simulator, web, CoSE_Agent
npm --prefix apps/web run dev     # web app on :5173; API: .venv/bin/python -m cose_cloud.cli serve --env-file deploy/dev.env
```

## Licence

MIT (`LICENSE`). CoSE-Care-Agent, which the simulator and the model layer come from, is CoSE's own code with its own terms. Catalog entries link to third-party data under their sources' licences; CoSE Cloud stores metadata and links, not copies.
