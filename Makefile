# CoSE Cloud. `make check` = every test that needs no running stack; `make e2e` = the whole stack in Docker.
PY ?= .venv/bin/python
CARE_AGENT ?= ../CoSE_tools/CoSE-Care-Agent
WHEELS = deploy/compose/wheels

.PHONY: check test test-db web-test wheels pki acl e2e e2e-keep

check: test web-test
	@echo "make check: OK"

test: test-db
	$(PY) -m pytest

# throwaway Postgres 17 on 127.0.0.1:54329 for the database tests
test-db:
	@docker inspect cose-cloud-testdb >/dev/null 2>&1 || docker run -d --name cose-cloud-testdb -e POSTGRES_USER=cose \
	  -e POSTGRES_PASSWORD=cose -e POSTGRES_DB=cose_test -p 127.0.0.1:54329:5432 postgres:17 >/dev/null
	@docker start cose-cloud-testdb >/dev/null
	@for i in $$(seq 1 30); do docker exec cose-cloud-testdb pg_isready -U cose -d cose_test >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1

web-test:
	cd apps/web && npm ci --no-audit --no-fund && npx tsc --noEmit && npx vitest run

# the CoSE-Care-Agent wheel and pinned third-party requirements the services image installs
wheels:
	rm -rf $(WHEELS) && mkdir -p $(WHEELS)
	uv build --wheel --out-dir $(WHEELS) $(CARE_AGENT)
	uv export --frozen --no-hashes --no-dev --no-emit-workspace --no-emit-package cose-care-agent -o $(WHEELS)/requirements.lock

pki:
	deploy/compose/make_dev_pki.sh

acl:
	$(PY) -m cose_cloud.cli acl > deploy/compose/mosquitto/acl

e2e: wheels pki
	$(PY) tests/e2e/run_e2e.py

e2e-keep: wheels pki
	$(PY) tests/e2e/run_e2e.py --keep
