"""The AWS IoT Core path into the same normalise() the MQTT service uses (not deployed in M1).

The IoT rule must hand over the payload bytes untouched, so the stored sha256 (and with it duplicate detection)
matches what the Mosquitto path computes. Rule SQL, to be verified against AWS IoT Core when M7 is built:

    SELECT encode(*, 'base64') AS payload_b64, topic() AS topic, timestamp() AS received_ms
    FROM 'cose/v1/devices/+/+'

`SELECT *` would merge the device's JSON into the rule output and break the payload schemas
(`additionalProperties: false`). docs/AWS_PORTABILITY.md lists the remaining items to check.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone


class BadEvent(ValueError):
    pass


def event_to_args(event: dict) -> tuple[str, bytes, datetime]:
    """(topic, payload bytes, received_at) from an IoT rule event shaped by the SQL above."""
    try:
        topic = event["topic"]
        payload = base64.b64decode(event["payload_b64"], validate=True)
        received_at = datetime.fromtimestamp(int(event["received_ms"]) / 1000.0, timezone.utc)
    except (KeyError, TypeError, ValueError, binascii.Error) as e:
        raise BadEvent(f"not an IoT rule event: {e}") from e
    if not isinstance(topic, str):
        raise BadEvent("topic is not a string")
    return topic, payload, received_at
