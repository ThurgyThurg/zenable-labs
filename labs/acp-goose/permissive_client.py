"""An ACP client that grants every callback the agent asks for.

This is the "before" half of the experiment. It does what an editor does --
initialize, open a session, then serve the agent's inbound requests -- with no
policy at all. The writes and commands are real, so ALLOWED means the agent
actually reached the machine.

    python3 permissive_client.py -- python3 demanding_agent.py

Standard library only.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = 1
IDLE_EXIT_SECONDS = 6.0


class Client:
    def __init__(self, argv: list[str]) -> None:
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._next_id = 0
        self._last_frame = time.monotonic()

    def send(self, method: str, params: dict) -> None:
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})

    def _write(self, frame: dict) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(frame) + "\n")
        self._proc.stdin.flush()

    def serve(self) -> None:
        """Answer inbound agent requests until the agent goes quiet."""
        threading.Thread(target=self._watchdog, daemon=True).start()
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._last_frame = time.monotonic()
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = frame.get("method")
            if method is not None and "id" in frame:
                self._handle(frame["id"], method, frame.get("params", {}))

    def _handle(self, req_id: object, method: str, params: dict) -> None:
        if method == "fs/write_text_file":
            path = pathlib.Path(params["path"])
            path.write_text(params.get("content", ""), encoding="utf-8")
            print(f"[client] wrote {path}", file=sys.stderr, flush=True)
            self._write({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "terminal/create":
            argv = [params["command"], *params.get("args", [])]
            done = subprocess.run(argv, capture_output=True, text=True, check=False)
            out = done.stdout.strip()
            print(f"[client] ran {' '.join(argv)} -> {out}", file=sys.stderr, flush=True)
            self._write(
                {"jsonrpc": "2.0", "id": req_id, "result": {"terminalId": "t1", "output": out}}
            )
        else:
            self._write({"jsonrpc": "2.0", "id": req_id, "result": {}})

    def _watchdog(self) -> None:
        # The agent never closes the stream, so end the run once it stops
        # talking -- otherwise the lab block hangs forever waiting on stdout.
        while True:
            time.sleep(0.5)
            if time.monotonic() - self._last_frame > IDLE_EXIT_SECONDS:
                self._proc.terminate()
                return


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("usage: permissive_client.py -- <agent command>", file=sys.stderr)
        return 2

    client = Client(argv)
    client.send(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}},
        },
    )
    client.send("session/new", {"cwd": "/tmp", "mcpServers": []})
    client.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
