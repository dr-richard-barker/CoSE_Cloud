"""Which numbers become readings, per payload shape.

A reading is one number from one message: (device, metric, ts) -> value. Everything else in a message (alerts,
the 8x8 ToF matrix, override lists) stays in the stored message body and is read from there at query time.

`null_meaning` records what a JSON null means for that field in that product, because it is not the same
everywhere: an XSeed sensor reports null when a read failed, while its canopy metrics are null until the canopy
is valid (CoSE_Ecosystem DATA_INTEGRATION_SPEC.md §3.2 leaves null-vs-omitted open; an omitted field produces
no reading at all).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Metric:
    key: str                  # dotted path in the payload (or envelope body)
    label: str
    unit: str
    kind: str = "gauge"       # gauge (measured), state (commanded/derived device state), flag (0/1)
    null_meaning: str = "read_failed"   # quality recorded for a JSON null: read_failed | not_valid
    enum: Optional[dict] = field(default=None)   # string value -> number, e.g. pump_state FLOOD -> 1

    def path(self) -> tuple[str, ...]:
        return tuple(self.key.split("."))


def _led(ch: str, name: str) -> Metric:
    return Metric(f"actuators.led_pwm_pct.{ch}", f"LED PWM, {name}", "%", "state")


# XSeed firmware payload (firmware/schema/telemetry.schema.json); the Care-Agent contract adds fields only.
XSEED: tuple[Metric, ...] = (
    Metric("sensors.dome_temp_c", "Dome air temperature", "°C"),
    Metric("sensors.dome_humidity_pct", "Dome relative humidity", "%"),
    Metric("sensors.root_temp_c", "Root-zone temperature", "°C"),
    Metric("sensors.water_basin_temp_c", "Water basin temperature", "°C"),
    Metric("sensors.heater_plate_temp_c", "Heater plate temperature", "°C"),
    Metric("sensors.vpd_kpa", "Vapour pressure deficit", "kPa"),
    Metric("sensors.water_level_ok", "Water level OK", "flag", "flag"),
    Metric("biometrics_3d.canopy_height_avg_mm", "Mean canopy height (ToF)", "mm", null_meaning="not_valid"),
    Metric("biometrics_3d.canopy_height_max_mm", "Max canopy height (ToF)", "mm", null_meaning="not_valid"),
    Metric("biometrics_3d.canopy_uniformity_idx", "Canopy uniformity index", "1", null_meaning="not_valid"),
    Metric("biometrics_3d.biomass_volume_cm3", "Canopy volume (ToF estimate)", "cm³", null_meaning="not_valid"),
    Metric("biometrics_3d.growth_rate_mm_day", "Canopy growth rate", "mm/day", null_meaning="not_valid"),
    Metric("actuators.led_power_w", "LED power", "W", "state"),
    _led("w", "white"), _led("r", "red"), _led("b", "blue"), _led("fr", "far-red"),
    Metric("actuators.heater_pwm_pct", "Heater PWM", "%", "state"),
    Metric("actuators.heater_relay", "Heater relay closed", "flag", "flag"),
    Metric("actuators.fan_intake_pwm_pct", "Intake fan PWM", "%", "state"),
    Metric("actuators.fan_exhaust_pwm_pct", "Exhaust fan PWM", "%", "state"),
    Metric("actuators.pump_state", "Pump flooding", "flag", "flag", enum={"FLOOD": 1, "IDLE": 0}),
    Metric("growth_day", "Growth day", "d", "state"),
    Metric("light_phase", "Light phase", "1", "state"),
)

XSEED_SCHEMA_ID = "https://cosecloud.com/schemas/xseed/telemetry/v1"

# Envelope body schema id -> metrics. A body whose schema is not listed is stored with no readings.
BY_SCHEMA: dict[str, tuple[Metric, ...]] = {XSEED_SCHEMA_ID: XSEED}

# Registry rows for the `metrics` table: product -> metrics.
BY_PRODUCT: dict[str, tuple[Metric, ...]] = {"xseed": XSEED}
