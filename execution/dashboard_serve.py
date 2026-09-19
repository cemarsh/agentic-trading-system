"""
Serve the web dashboard: dashboard/index.html plus the snapshot it polls.

    python execution/dashboard_serve.py            # 127.0.0.1:8765, snapshot every 60 s
    ssh -L 8765:127.0.0.1:8765 workstation          # then open http://127.0.0.1:8765/

One process, separate from trading.service (deploy/trading-dashboard.service). A worker
thread calls dashboard_export.write_snapshot() on an interval; the HTTP handler only
reads files. It serves exactly two paths, so nothing else under the repo (.env, logs,
agent_state) is reachable.

The page has no auth of its own. It binds loopback by default (reach it with an ssh
tunnel). For the public link, trading-dashboard.service binds all interfaces so the
Cloudflare connector on pve01 can reach it, and DASHBOARD_ALLOW_FROM limits which
client addresses get an answer — VM 117 runs no host firewall, so the allowlist is the
LAN boundary. The login itself is Cloudflare Access on trading.cloudmagic.software.

The page raises its own alert when the snapshot is older than 3 minutes, so a stuck
exporter thread is visible from the browser rather than showing old numbers as current.
"""

import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution import dashboard_export

PAGE_PATH = Path("dashboard/index.html")
BIND = os.environ.get("DASHBOARD_BIND", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
INTERVAL = max(15, int(os.environ.get("DASHBOARD_INTERVAL_SECONDS", "60")))
# Client IPs that may connect. Loopback always; add the tunnel connector's address.
ALLOW_FROM = {"127.0.0.1", "::1"} | {
    a.strip() for a in os.environ.get("DASHBOARD_ALLOW_FROM", "").split(",") if a.strip()}


def export_forever(stop: threading.Event) -> None:
    settings = cfg_module.load()
    while not stop.is_set():
        started = time.monotonic()
        try:
            snap = dashboard_export.write_snapshot(settings=settings)
            if snap["errors"]:
                print(f"[DASH] snapshot with {len(snap['errors'])} error(s): "
                      f"{'; '.join(snap['errors'])[:300]}")
        except Exception as e:  # keep serving the last good snapshot; the page flags its age
            print(f"[DASH] export failed: {e}")
        stop.wait(max(5.0, INTERVAL - (time.monotonic() - started)))


class Handler(BaseHTTPRequestHandler):
    ROUTES = {
        "/": (PAGE_PATH, "text/html; charset=utf-8"),
        "/index.html": (PAGE_PATH, "text/html; charset=utf-8"),
        "/state.json": (dashboard_export.SNAPSHOT_PATH, "application/json"),
    }

    def do_GET(self):
        if self.client_address[0] not in ALLOW_FROM:
            self.send_error(403)
            return
        route = self.ROUTES.get(self.path.split("?", 1)[0])
        if not route:
            self.send_error(404)
            return
        path, ctype = route
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(503, "snapshot not written yet" if path.suffix == ".json" else None)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # the page polls every 15 s; don't flood the journal
        pass


def main():
    stop = threading.Event()
    threading.Thread(target=export_forever, args=(stop,), daemon=True,
                     name="dashboard-export").start()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"[DASH] serving http://{BIND}:{PORT}/ — snapshot every {INTERVAL}s, "
          f"answering {', '.join(sorted(ALLOW_FROM))}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
