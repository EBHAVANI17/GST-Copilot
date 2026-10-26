# 16. Streaming answers over server-sent events

Date: 2026-10-26
Status: Accepted

## Context

After warm-up (ADR 0015) the first request no longer pays for model loading, but a
long answer still takes about 10 s to generate on qwen2.5:3b (ask_id 6: 10 points,
generate 10016 ms). `/ask` returns nothing until the whole answer is written, so the
user stares at a spinner for the full time. A smaller model or a shorter cap would
cut answer quality; the wait the user notices is the time before anything appears.

## Decision

- New endpoint `POST /ask/stream`, same request body as `/ask`, answering with
  server-sent events (`text/event-stream`):
  1. `passages`: the passages the model will read, sent as soon as retrieval,
     reranking and expansion are done (before generation starts);
  2. `token`: each piece of text as the LLM writes it;
  3. `done`: ask_id, the full answer, refused/partial/truncated, cited and invalid
     citations, timings; or `error` if the LLM fails.
- `/ask` stays unchanged: evals, the judge and scripts keep the simple JSON API.
  Both go through the same retrieval code (`rag/service.py: _retrieve`), so a
  streamed answer is built from exactly the same context.
- The LLM client streams with the OpenAI-compatible `"stream": true` and
  `stream_options.include_usage` (token counts in the last event). Ollama, vLLM,
  OpenAI and Groq all speak it, so switching provider still needs only env variables.
- New timing `first_token`: ms from the start of generation to the first piece of
  text. It is part of `generate`, not an extra stage, so the usage report leaves it
  out of `total` and reports `time_to_first_token` (all stages before generation
  + `first_token`) for streamed answers. ask_logs records `config.streamed`.
- Citation, refusal and partial checks need the whole answer, so they arrive only in
  `done`. In the `passages` event every passage has `cited: false`.
- `python -m gst_copilot.client "question"` prints a streamed answer and measures
  time to passages / first word / end on the client side.

Why SSE and not WebSockets: the flow is one request, one stream of answer back.
SSE is plain HTTP (works through proxies and load balancers, easy to test with
httpx), and the browser has a built-in reader for it.

## Consequences

- Measured on the laptop (qwen2.5:3b, RTX 4050, warm), "What are the conditions for
  taking input tax credit?" (ask_id 8, 10-point answer), times seen by the client:

  | Event | ms |
  |---|---|
  | passages | 2915 |
  | first word | 5008 |
  | end | 13177 |

  The user starts reading after 5.0 s instead of 13.2 s. Before the first word the
  time goes to rerank (2339 ms, CPU, 20 candidates) and the model reading the prompt
  (first_token 2104 ms for about 8000 chars of context). These two are the next
  latency targets; generation itself (about 8 s for this answer) is not.
- A refusal or other one-sentence answer arrives in one piece (ask_id 7: first_token
  2593 ms, generate 2602 ms), so streaming helps only long answers.
- Once streaming starts the HTTP status is already 200, so an LLM failure arrives
  as an `error` event, not a 502. Clients must handle that event.
- If the client disconnects mid-answer, the server stops reading and closes the
  connection to the LLM, so Ollama stops generating (no wasted GPU time). Such an
  abandoned answer is not written to ask_logs (known gap).
- The request log line (`gst_copilot.request`) measures the time to the response
  headers, not to the end of the stream; use `generate` in ask_logs for that.
- The total time does not change: streaming makes the wait visible and useful, it
  does not make generation faster. Requires FastAPI >= 0.118 so the database session
  stays open while the response streams.
