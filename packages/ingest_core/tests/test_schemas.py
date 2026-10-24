"""The schema copies are verbatim: same sha256 as recorded, and the same bytes as their sources when the CoSE_tools
workspace is checked out next to this repository (skipped otherwise, e.g. in CI)."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

SCHEMAS = files("cose_ingest_core").joinpath("schemas")
SOURCES = json.loads(SCHEMAS.joinpath("SOURCES.json").read_text())
NAMES = [k for k in SOURCES if k.endswith(".json")]
WORKSPACE = Path(__file__).resolve().parents[4] / "CoSE_tools"


@pytest.mark.parametrize("name", NAMES)
def test_sha256_matches_the_record(name):
    assert hashlib.sha256(SCHEMAS.joinpath(name).read_bytes()).hexdigest() == SOURCES[name]["sha256"]


@pytest.mark.parametrize("name", NAMES)
def test_copy_matches_its_source(name):
    src = WORKSPACE.parent / SOURCES[name]["source"]
    if not src.exists():
        pytest.skip(f"{src} not checked out here")
    assert src.read_bytes() == SCHEMAS.joinpath(name).read_bytes(), f"{name} drifted from {src}: re-copy and re-record"
