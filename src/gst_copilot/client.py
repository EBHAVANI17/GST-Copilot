"""Watch a streamed answer in the terminal and measure what the user waits.

    python -m gst_copilot.client "Can I claim ITC on a car for my sales staff?"
    python -m gst_copilot.client --url http://localhost:8000 --top-k 3 "..."

Prints the passages' refs, then the answer as it arrives, then the time to the
passages, to the first word and to the end, measured here on the client (so it
includes the network and the server's queueing, not only the server's timings).
"""

import argparse
import json
import sys
import time
from collections.abc import Iterator
from typing import Any

import httpx


def parse_sse(lines: Iterator[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """(event, data) pairs from server-sent event lines; a blank line ends an event."""
    event, data = "message", ""
    for line in lines:
        if not line:
            if data:
                yield event, json.loads(data)
            event, data = "message", ""
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data += line[5:].strip()
    if data:
        yield event, json.loads(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("question")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--top-k", type=int, default=None)
    args = p.parse_args(argv)

    body: dict[str, Any] = {"question": args.question}
    if args.top_k:
        body["top_k"] = args.top_k
    start = time.perf_counter()
    marks: dict[str, float] = {}

    def mark(name: str) -> None:
        marks.setdefault(name, round((time.perf_counter() - start) * 1000))

    with httpx.stream("POST", f"{args.url}/ask/stream", json=body, timeout=120) as r:
        if r.status_code != 200:
            r.read()
            print(f"HTTP {r.status_code}: {r.text}", file=sys.stderr)
            return 1
        for event, data in parse_sse(r.iter_lines()):
            if event == "passages":
                mark("passages")
                refs = ", ".join(p["ref"] for p in data["passages"]) or "none"
                print(f"[passages: {refs}]\n", flush=True)
            elif event == "token":
                mark("first_token")
                print(data["text"], end="", flush=True)
            elif event == "done":
                mark("done")
                print(f"\n\n[ask_id {data['ask_id']}, cited: {', '.join(data['cited']) or 'none'}]")
                print(f"[server timings_ms: {data['timings_ms']}]")
            elif event == "error":
                mark("done")
                print(f"\n[error: {data['detail']}]", file=sys.stderr)
    print(f"[client ms: {marks}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
