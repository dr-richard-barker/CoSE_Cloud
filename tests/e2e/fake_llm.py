"""A scripted stand-in for a local model server, for end-to-end tests only (OpenAI-style /v1/chat/completions).

It answers one kind of question the way a model would, through CoSE Cloud's real LocalProvider path:
summarize_stats -> query_timeseries -> make_chart -> a sentence quoting the mean from the stats tool result.
It reports its model as `e2e-scripted`, so nothing it says can be taken for a real model's answer.

    python tests/e2e/fake_llm.py --port 8439 --device xseed-sim-0001
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "e2e-scripted"


def _call(name: str, args: dict, n: int) -> dict:
    return {"id": f"call_{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def reply(messages: list[dict], device: str) -> dict:
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    last_user = max(i for i, m in enumerate(messages) if m.get("role") == "user")
    fresh = [m for i, m in enumerate(messages) if m.get("role") == "tool" and i > last_user]
    n = len(tool_msgs)
    window = {"day": "yesterday", "start": None, "end": None}
    if len(fresh) == 0:
        calls = [_call("summarize_stats", {"device_uuid": device, "metric": "sensors.dome_temp_c", **window}, n)]
    elif len(fresh) == 1:
        calls = [_call("query_timeseries", {"device_uuid": device, "metrics": ["sensors.dome_temp_c"], **window,
                                            "bucket_minutes": None}, n)]
    elif len(fresh) == 2:
        ds = json.loads(fresh[1]["content"])["dataset_id"]
        calls = [_call("make_chart", {"dataset_ids": [ds], "kind": "line", "title": "Dome temperature yesterday"}, n)]
    else:
        stats = json.loads(fresh[0]["content"])
        text = (f"The simulated XSeed's mean dome temperature yesterday ({stats['window']}) was {stats['mean']:.1f} °C, "
                f"from {stats['n']} readings, ranging {stats['min']:.1f} to {stats['max']:.1f} °C.")
        return {"role": "assistant", "content": text}
    return {"role": "assistant", "content": "", "tool_calls": calls}


class Handler(BaseHTTPRequestHandler):
    device = "xseed-sim-0001"

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        msg = reply(body["messages"], self.device)
        out = {"id": "e2e", "object": "chat.completion", "model": MODEL,
               "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8439)
    ap.add_argument("--device", default="xseed-sim-0001")
    a = ap.parse_args()
    Handler.device = a.device
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
