"""Vega-Lite specs built on the server from stored datasets, so plotted numbers never pass through the model.

Rules (dataviz method): one y-axis per panel; metrics with different units become stacked panels sharing the
time axis, never a dual axis. Series colours come from the web app's theme config (validated light/dark
categorical palettes, apps/web/src/chartTheme.ts) in a fixed order by metric, so a colour follows its metric.
Lines are 2 px with a crosshair + tooltip; a panel with 2+ series gets a legend and end-of-line labels.
A spec never carries a data URL or a link: data is inline, and `assert_safe` enforces that.
"""

from __future__ import annotations

from typing import Any, Iterable

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
KINDS = ("line", "bar", "scatter")
FORBIDDEN_KEYS = {"url", "href", "loader", "signals"}   # no external data, no links, no custom code paths


def _series_name(m: dict) -> str:
    return f"{m['label']} ({m['unit']})"


def _field(name: str) -> str:
    """A pivoted column name as a Vega-Lite field reference: dots and brackets would read as nested access."""
    return name.replace(".", "\\.").replace("[", "\\[").replace("]", "\\]")


def _panel(rows: list[dict], metrics: list[dict], kind: str, height: int) -> dict:
    names = [_series_name(m) for m in metrics]
    color = {"field": "series", "type": "nominal", "scale": {"domain": names},
             "legend": {"orient": "top", "title": None} if len(names) > 1 else None}
    y_title = metrics[0]["unit"] if len(metrics) > 1 else _series_name(metrics[0])
    x = {"field": "ts", "type": "temporal", "title": None, "axis": {"format": "%b %d %H:%M", "labelOverlap": True}}
    y = {"field": "value", "type": "quantitative", "title": y_title, "scale": {"zero": False}}
    hover = {"name": "hover", "select": {"type": "point", "fields": ["ts"], "nearest": True, "on": "pointerover",
                                         "clear": "pointerout"}}
    if kind == "bar":
        layers = [{"mark": {"type": "bar", "cornerRadiusEnd": 4}, "encoding": {
            "x": x, "y": {**y, "scale": {"zero": True}}, "color": color, "xOffset": {"field": "series"},
            "tooltip": [{"field": "series"}, {"field": "ts", "type": "temporal", "format": "%Y-%m-%d %H:%M"},
                        {"field": "value", "type": "quantitative", "format": ".3~f"}]}}]
    elif kind == "scatter":
        layers = [{"mark": {"type": "point", "filled": True, "size": 64}, "encoding": {
            "x": x, "y": y, "color": color,
            "tooltip": [{"field": "series"}, {"field": "ts", "type": "temporal", "format": "%Y-%m-%d %H:%M"},
                        {"field": "value", "type": "quantitative", "format": ".3~f"}]}}]
    else:
        layers = [
            {"mark": {"type": "line", "strokeWidth": 2, "interpolate": "monotone"},
             "encoding": {"x": x, "y": y, "color": color}},
            {"mark": {"type": "rule", "strokeWidth": 1, "opacity": 0.6},
             "params": [hover],
             "encoding": {"x": {"field": "ts", "type": "temporal"},
                          "opacity": {"condition": {"param": "hover", "empty": False, "value": 0.6}, "value": 0},
                          "tooltip": [{"field": "ts", "type": "temporal", "title": "Time",
                                       "format": "%Y-%m-%d %H:%M"}] +
                                     [{"field": _field(n), "title": n, "type": "quantitative", "format": ".3~f"}
                                      for n in names]},
             "transform": [{"pivot": "series", "value": "value", "groupby": ["ts"]}]},
            {"mark": {"type": "point", "filled": True, "size": 64},
             "encoding": {"x": {"field": "ts", "type": "temporal"}, "y": {"field": "value", "type": "quantitative"},
                          "color": color,
                          "opacity": {"condition": {"param": "hover", "empty": False, "value": 1}, "value": 0}}},
        ]
        if len(names) > 1:   # end-of-line labels, so identity is never colour alone
            layers.append({
                "transform": [{"window": [{"op": "rank", "as": "r"}], "sort": [{"field": "ts", "order": "descending"}],
                               "groupby": ["series"]}, {"filter": "datum.r == 1"}],
                "mark": {"type": "text", "align": "left", "dx": 6, "fontSize": 11},
                "encoding": {"x": {"field": "ts", "type": "temporal"}, "y": {"field": "value", "type": "quantitative"},
                             "text": {"field": "short"}}})
    return {"height": height, "width": "container", "data": {"values": rows}, "layer": layers}


def build(points: Iterable[dict], metrics: list[dict], *, title: str, kind: str = "line",
          provenance_notes: list[str], provenance: list[str]) -> dict[str, Any]:
    """points: {metric, ts, value, n}; metrics: registry rows (key, label, unit) in the order to colour them."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not metrics:
        raise ValueError("no metrics")
    by_key = {m["key"]: m for m in metrics}
    rows = [{"ts": p["ts"].isoformat() if hasattr(p["ts"], "isoformat") else p["ts"],
             "series": _series_name(by_key[p["metric"]]), "short": by_key[p["metric"]]["label"],
             "value": None if p["value"] is None else round(float(p["value"]), 4)}
            for p in points if p["metric"] in by_key]
    groups: dict[str, list[dict]] = {}
    for m in metrics:
        groups.setdefault(m["unit"], []).append(m)
    height = 220 if len(groups) == 1 else 150
    panels = [_panel([r for r in rows if r["series"] in {_series_name(m) for m in ms}], ms, kind, height)
              for ms in groups.values()]
    subtitle = [n for n in provenance_notes if n]
    spec: dict[str, Any] = {
        "$schema": SCHEMA,
        "title": {"text": title, "subtitle": subtitle, "anchor": "start"},
        "usermeta": {"provenance": sorted(set(provenance)), "notes": subtitle, "series_order":
                     [_series_name(m) for m in metrics]},
        "autosize": {"type": "fit-x", "contains": "padding"},
    }
    if len(panels) == 1:
        spec.update(panels[0])
    else:
        spec["vconcat"] = panels
        spec["resolve"] = {"scale": {"y": "independent", "color": "independent"}}
    assert_safe(spec)
    return spec


def assert_safe(node: Any, path: str = "") -> None:
    """No external data, links or code-bearing keys anywhere in a spec (the chat UI checks again)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in FORBIDDEN_KEYS:
                raise ValueError(f"chart spec may not contain {k!r} (at {path or 'root'})")
            assert_safe(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            assert_safe(v, f"{path}/{i}")
