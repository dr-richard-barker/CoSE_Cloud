"""How simulated data is labelled wherever it is shown, exported or spoken."""

from __future__ import annotations

SIM_LABEL = "sim-uncalibrated"   # CoSE-Care-Agent's own label for every simulator result


def provenance_note(sim_meta: dict) -> str:
    return (f"SIMULATED — CoSE-Care-Agent SimPod v{sim_meta.get('care_agent', '?')} "
            f"({sim_meta.get('scenario', '?')}, seed {sim_meta.get('seed', '?')}), {SIM_LABEL}")
