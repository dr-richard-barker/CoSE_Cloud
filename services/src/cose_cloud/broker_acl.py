"""The broker's access rules for a CoSE Cloud deployment (mosquitto ACL file).

The device lines are CoSE-Care-Agent's: identity is the client certificate's CN, each device's CN is its UUID,
and `pattern` lines confine every device to its own tree. CoSE Cloud adds one read-only user, the ingest service.
There is deliberately no user that may write `commands`: in M1 nothing in CoSE Cloud can command a device. M3
adds the Care-Agent host (its own certificate, its own `user` block from Care-Agent's acl_text()).
"""

from __future__ import annotations

from cose_care_agent.contract import topics
from cose_care_agent.transport.acl import DEVICE_PUBLISHES, DEVICE_SUBSCRIBES, check_identity

INGEST_USER = "cose-cloud-ingest"


def acl_text(ingest_user: str = INGEST_USER) -> str:
    check_identity(ingest_user, "ingest user")
    own = topics.ROOT.format(device_uuid="%u")
    lines = ["# CoSE Cloud broker access rules (generated: cose-cloud acl). Username = client certificate CN.",
             "# Anything not granted here is denied. No user may write `commands` in M1.", "",
             "# the ingest service: reads every device's reports, writes nothing", f"user {ingest_user}"]
    lines += [f"topic read {topics.topic('+', leaf)}" for leaf in DEVICE_PUBLISHES]
    lines += ["", "# every device (certificate CN = device UUID): its own tree only"]
    lines += [f"pattern write {own}{leaf}" for leaf in DEVICE_PUBLISHES]
    lines += [f"pattern read {own}{leaf}" for leaf in DEVICE_SUBSCRIBES]
    return "\n".join(lines) + "\n"
