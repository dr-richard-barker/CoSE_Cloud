"""Edition profiles: one codebase, one YAML file per product edition (editions/*.yaml), validated on load."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Optional

import yaml
from jsonschema import Draft202012Validator

from cose_cloud.agent.tools import NAMES

ORDER = ("hq", "xseed", "rover", "drone", "sense")


@lru_cache(maxsize=1)
def all_editions() -> dict[str, dict]:
    folder = files("cose_cloud").joinpath("editions")
    validator = Draft202012Validator(json.loads(folder.joinpath("edition.schema.json").read_text()))
    out = {}
    for p in folder.iterdir():
        if not p.name.endswith(".yaml"):
            continue
        ed = yaml.safe_load(p.read_text())
        errors = sorted(validator.iter_errors(ed), key=str)
        if errors:
            raise ValueError(f"{p.name}: {errors[0].message}")
        tools = ed["agent_tools"]
        if tools != "all" and set(tools) - set(NAMES):
            raise ValueError(f"{p.name}: unknown agent tools {sorted(set(tools) - set(NAMES))}")
        out[ed["id"]] = ed
    return {k: out[k] for k in sorted(out, key=lambda k: ORDER.index(k) if k in ORDER else 99)}


def get(edition_id: str) -> Optional[dict]:
    return all_editions().get(edition_id)


def allowed_tools(edition_id: str) -> Optional[list[str]]:
    ed = get(edition_id)
    if ed is None:
        raise KeyError(edition_id)
    return None if ed["agent_tools"] == "all" else list(ed["agent_tools"])
