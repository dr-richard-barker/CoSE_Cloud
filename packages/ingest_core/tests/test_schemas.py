"""The schema copies are verbatim: same sha256 as recorded, and the same bytes as their sources when the CoSE_tools
workspace holds this repository or sits next to it (skipped only when there is no workspace, e.g. in CI)."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

SCHEMAS = files("cose_ingest_core").joinpath("schemas")
SOURCES = json.loads(SCHEMAS.joinpath("SOURCES.json").read_text())
NAMES = [k for k in SOURCES if k.endswith(".json")]


def _workspace_parent() -> Path | None:
    """The folder that holds CoSE_tools: SOURCES.json paths start there. This repository may be inside it or beside it."""
    for d in Path(__file__).resolve().parents:
        if (d / "CoSE_tools" / "CoSE_Ecosystem").is_dir():
            return d
    return None


WORKSPACE_PARENT = _workspace_parent()


@pytest.mark.parametrize("name", NAMES)
def test_sha256_matches_the_record(name):
    assert hashlib.sha256(SCHEMAS.joinpath(name).read_bytes()).hexdigest() == SOURCES[name]["sha256"]


@pytest.mark.parametrize("name", NAMES)
def test_copy_matches_its_source(name):
    if WORKSPACE_PARENT is None:
        pytest.skip("no CoSE_tools workspace around this checkout")
    src = WORKSPACE_PARENT / SOURCES[name]["source"]
    assert src.exists(), f"{src} is missing: the source moved, so update SOURCES.json"
    assert src.read_bytes() == SCHEMAS.joinpath(name).read_bytes(), f"{name} drifted from {src}: re-copy and re-record"
