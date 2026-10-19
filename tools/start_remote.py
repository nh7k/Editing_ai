"""Start everything claude.ai needs, in one go: the CutMind backend (127.0.0.1:8010), the MCP server over HTTP
(127.0.0.1:8020, secret URL path) and a Cloudflare quick tunnel to the MCP server only. Prints the connector URL and
writes it to ~/CutMind/connector_url.txt (the app's Settings → "Connect to Claude" shows it).

    backend/.venv/Scripts/python.exe tools/start_remote.py          # start (keeps running; Ctrl+C stops all)
    backend/.venv/Scripts/python.exe tools/start_remote.py --rotate # new secret token first (old URL stops working)

Needs cloudflared at ~/CutMind/bin/cloudflared.exe (Cloudflare's signed release; docs/MCP_USAGE.md). The tunnel
exposes ONLY the MCP server; the backend stays on 127.0.0.1. A quick-tunnel URL changes on every start.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
HOME = Path.home() / "CutMind"
CLOUDFLARED = HOME / "bin" / "cloudflared.exe"
URL_FILE = HOME / "connector_url.txt"
TOKEN_FILE = HOME / "mcp_http_token.txt"
LOGS = HOME / "logs"


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start(name: str, args: list[str], env: dict[str, str] | None = None) -> subprocess.Popen:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = (LOGS / f"{name}.log").open("w", encoding="utf-8")
    print(f"starting {name} ...", flush=True)
    return subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})})


def wait_port(port: int, seconds: float = 90) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if listening(port):
            return True
        time.sleep(1)
    return False


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console (cp1252) cannot print every character
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotate", action="store_true", help="make a new secret token (the old URL stops working)")
    a = ap.parse_args()
    HOME.mkdir(parents=True, exist_ok=True)
    if a.rotate or not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
        print("new secret token made", flush=True)
    if not CLOUDFLARED.exists():
        print(f"cloudflared not found at {CLOUDFLARED} — see docs/MCP_USAGE.md", file=sys.stderr)
        return 2
    procs: list[subprocess.Popen] = []
    env = {"PYTHONPATH": str(ROOT / "backend"), "CUTMIND_URL": "http://localhost:8010", "PLANNER_MODE": "mock",
           "CUTMIND_TRANSLATOR": "off"}
    try:
        if not listening(8010):
            procs.append(start("backend", [str(PY), "-m", "uvicorn", "cutmind.api:create_app", "--factory", "--app-dir",
                                           "backend", "--host", "127.0.0.1", "--port", "8010"], env))
            if not wait_port(8010):
                print("the backend did not start — see ~/CutMind/logs/backend.log", file=sys.stderr)
                return 1
        if listening(8020):
            print("an MCP server is already on 8020 (restart it after --rotate)", flush=True)
        else:
            procs.append(start("mcp", [str(PY), "-m", "cutmind.mcp_server", "--mode", "edit", "--http", "8020"], env))
            if not wait_port(8020, 60):
                print("the MCP server did not start — see ~/CutMind/logs/mcp.log", file=sys.stderr)
                return 1
        tunnel = start("tunnel", [str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8020",
                                  "--http-host-header", "127.0.0.1:8020"])
        procs.append(tunnel)
        url = None
        end = time.time() + 60
        while time.time() < end and url is None:
            time.sleep(1)
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", (LOGS / "tunnel.log").read_text(errors="ignore"))
            url = m.group(0) if m else None
        if url is None:
            print("no tunnel URL — see ~/CutMind/logs/tunnel.log", file=sys.stderr)
            return 1
        full = f"{url}/{TOKEN_FILE.read_text().strip()}/mcp"
        URL_FILE.write_text(full)
        print("\nREADY. claude.ai → Settings → Connectors → Add custom connector → name: cutmind, URL:\n")
        print(f"  {full}\n")
        print("(also in ~/CutMind/connector_url.txt and in the app: Settings > Connect to Claude)")
        print("Keep this window open. Ctrl+C stops the tunnel and the servers started here.", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(2)
        print("a process stopped — see ~/CutMind/logs", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        URL_FILE.unlink(missing_ok=True)
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
