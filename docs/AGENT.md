# CoSE_Agent

## What it can do (M1: read-only)

| Tool | Returns |
| :- | :- |
| `list_devices`, `describe_device`, `list_metrics` | the registry, coverage, units, site time zones, provenance |
| `get_latest` | latest reading per metric |
| `summarize_stats` | n, mean, sd, min, max, coverage %, failed-read and not-valid counts, provenance |
| `query_timeseries` | stores a dataset (bucketed means) and returns its id and a summary, not the rows |
| `list_alerts`, `list_experiments` | alert transitions; experiments |
| `search_catalog` | past experiments; source text comes back under `untrusted_text`, capped at 300 characters per field |
| `make_chart` | the **server** builds a Vega-Lite chart from stored datasets, so plotted numbers never pass through the model |
| `prepare_export` | offers CSV or RO-Crate as a download button |

There is no tool that writes data, sends a command, reaches the broker or fetches a URL. The organisation, user and conversation come from the session, never from the model's arguments. Every tool schema is `strict`.

## Models

`entitlements.llm_mode` per organisation:

- **hosted:** Claude through CoSE-Care-Agent's `AnthropicProvider`.
  - Default model `claude-opus-5-5`, effort `medium`.
  - Server-side refusal fallback is on: the API may re-run a declined request on another model, and the ledger records the model that actually served it.
  - Settings: `COSE_CHAT_MODEL`, `COSE_CHAT_EFFORT`, `COSE_CHAT_SERVER_FALLBACK`.
  - Questions and the data the agent reads are sent to Anthropic, and the panel says so.
- **local:** any OpenAI-style server (`COSE_LOCAL_LLM_URL`, `COSE_LOCAL_LLM_MODEL`), through Care-Agent's `LocalProvider`. No charge, and nothing leaves the network.
- **off:** the panel says so.

The conversation sent to the model is append-only. Each turn's content is stored exactly as the provider returned it and replayed unchanged, which thinking blocks require. A conversation stays on one provider. A question stops after 8 tool rounds; past that the model is told its tool budget is used up.

## Spend

Every hosted call is checked before it is made:

- **Reservation.** A worst-case reservation (`usage_ledger`, kind `reserve`) is checked against the organisation's monthly cap and CoSE's global monthly cap. The check runs under advisory locks, so concurrent questions cannot together overspend; a test proves only one of six concurrent reservations fits a cap sized for one.
- **Settlement.** After the call, the reservation is settled to the actual cost from Care-Agent's sourced `pricing.yaml`. Failure cases:

  | Situation | What happens |
  | :- | :- |
  | Organisation has no cap | No hosted calls |
  | Requested model has no listed price | Fails closed before the call |
  | Fallback served by an unlisted model | Charged at the highest listed rate, and the row says so |
  | Call failed | Its worst-case reservation stays |
- **Off switch.** `COSE_LLM_KILL_SWITCH=true` turns the agent off everywhere.

## Evidence rules in every reply

The reply is `{text, speech, charts, exports, provenance, provenance_footer, unverified_numbers}`.

- **Provenance footer.** The server adds it, e.g. "Data provenance: simulated. SIMULATED — CoSE-Care-Agent SimPod v0.1.1 (s0_nominal, seed 0), sim-uncalibrated", whatever the model wrote.
- **Charts.** Charts of simulated data carry the same line as a subtitle.
- **Speech.** Spoken replies start "These are simulated data." when the text does not already say so.
- **Unverified numbers.** Any number in the answer that no tool result supports at the answer's precision is listed; the panel shows "Not found in the data CoSE_Agent read: …". Small integers (counts, days) are not checked.
- **Rendering.** The panel renders text as plain paragraphs, with no links or images. Downloads must match the app's own export routes, and charts carrying a data URL or link are refused.

## Avatar (M1: CoSE logo orb)

An SVG orb in the brand gradient (navy #2F5985 → blue #3B6EA5 → teal #3FB6A8 → mint #54C9BA), with five states:

| State | Motion |
| :- | :- |
| idle | breathes |
| listening | pulses a ring |
| thinking | turns its arcs |
| speaking | ripples |
| offline | greyed |

With reduced motion the state shows as ring colour and a text label.

- **Voice input** is push-to-talk through the browser's speech recognition. In Chrome that audio goes to Google, and the panel says so.
- **Read-aloud** uses the browser's own speech synthesis. It is off by default.
- **Text chat** always works, with or without speech support.

## Testing without a model

`tests/e2e/fake_llm.py` is a scripted OpenAI-style server reporting itself as `e2e-scripted`. The end-to-end test points the HQ organisation's local model at it, which drives the real tool loop. Unit tests use scripted providers.

**Not yet verified: a live Claude call.** No API key was available when M1 was built. With a key, set the organisation to `hosted` with a cap and ask the same question. Expect a `summarize_stats` call, numbers that match SQL, and a ledger cost above $0 and within the cap.
