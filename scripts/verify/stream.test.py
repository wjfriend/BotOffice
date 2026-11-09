"""Check token streaming in the OpenAI-compatible adapter.

Starts a local HTTP server that speaks SSE, then asserts that:

  - each chunk arrives at the callback in order
  - the final text matches the joined chunks
  - without a callback the plain request path still works
  - usage is recorded either way

Run: python scripts/verify/stream.test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from botoffice.llm.client import LLMClient  # noqa: E402
from botoffice.llm.providers import Provider, ProviderRegistry  # noqa: E402

CHUNKS = ["Hel", "lo ", "world"]
FAILURES: list[str] = []

SEEN: list[bool] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        streaming = bool(body.get("stream"))
        SEEN.append(streaming)
        if streaming:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in CHUNKS:
                frame = {"choices": [{"delta": {"content": chunk}}]}
                self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = {
            "choices": [{"message": {"content": "".join(CHUNKS)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # noqa: D401 - silence the server
        pass


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


async def main_async(port: int) -> None:
    registry = ProviderRegistry()
    provider = Provider(
        id="local",
        protocol="openai",
        base_url=f"http://127.0.0.1:{port}",
        api_key="test",
        model="test-model",
    )
    client = LLMClient(registry)
    seen: list[str] = []

    print("=== 1. streaming delivers each chunk in order ===")
    text = await client.chat(
        provider,
        "system",
        [{"role": "user", "content": "hi"}],
        on_delta=seen.append,
    )
    check("callback ran", len(seen) == len(CHUNKS), str(seen))
    check("chunks are cumulative", seen[-1] == "".join(CHUNKS) if seen else False,
          str(seen[-1]) if seen else "")
    check("final text matches", text == "".join(CHUNKS), repr(text))
    check("a stream request was made", any(SEEN) is True, str(SEEN))

    print("=== 2. without a callback the plain path is used ===")
    seen.clear()
    SEEN.clear()
    text = await client.chat(
        provider, "system", [{"role": "user", "content": "hi"}]
    )
    check("plain request path", SEEN == [False], str(SEEN))
    check("text matches", text == "".join(CHUNKS), repr(text))

    print("=== 3. usage is recorded either way ===")
    rows = registry.cost_summary()
    check("usage recorded", len(rows) == 1, str(rows))


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(main_async(port))
    finally:
        server.shutdown()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
