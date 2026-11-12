"""The big screen (rulebook 4.3: "a big screen shows the live board, scores and events").

A tiny web server, standard library only. Open http://localhost:<port>/ in a browser
(full screen on the projector). Two modes:

  live:    the game loop calls publish(snapshot) after every turn and the page updates at once
           (Server-Sent Events: the browser keeps one connection open and we push each turn).
  replay:  the page gets every turn of a recorded game and plays it back with its own controls.

Pages:  /          the screen (screen.html)
        /map       the operator's map view: only the board, colour-coded, with each robot's
                   heading, marker and camera check (map.html)
        /state     the latest snapshot as JSON
        /stream    live updates
        /replay    all snapshots of a recorded game (replay mode only)
"""
import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen.html")
MAP_PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.html")   # operator's map view


class Screen:
    def __init__(self, port: int = 8080, host: str = "127.0.0.1", replay_frames: list = None):
        self.port = port
        self.host = host
        self.latest = None
        self.replay_frames = replay_frames       # list of snapshots, or None for a live game
        self._clients = []
        self._lock = threading.Lock()
        self._server = None

    @property
    def url(self) -> str:
        host = "localhost" if self.host in ("127.0.0.1", "0.0.0.0") else self.host
        return f"http://{host}:{self.port}/"

    def publish(self, snap: dict):
        """Show a new snapshot on every open screen."""
        data = json.dumps(snap)
        with self._lock:
            self.latest = data
            for client in self._clients:
                client.put(data)

    def start(self):
        """Start serving in a background thread."""
        screen = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):        # keep the console quiet
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                if path in ("/", "/map"):
                    with open(PAGE if path == "/" else MAP_PAGE, "rb") as f:
                        self._send(200, "text/html; charset=utf-8", f.read())
                elif path == "/state":
                    self._send(200, "application/json", (screen.latest or "null").encode())
                elif path == "/replay":
                    if screen.replay_frames is None:
                        self._send(404, "text/plain", b"not a replay")
                    else:
                        self._send(200, "application/json",
                                   json.dumps(screen.replay_frames).encode())
                elif path == "/stream":
                    self._stream()
                else:
                    self._send(404, "text/plain", b"not found")

            def _send(self, code, kind, body):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _stream(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                inbox = queue.Queue()
                with screen._lock:
                    screen._clients.append(inbox)
                    if screen.latest:
                        inbox.put(screen.latest)
                try:
                    while True:
                        try:
                            message = "data: " + inbox.get(timeout=15) + "\n\n"
                        except queue.Empty:
                            message = ": still here\n\n"      # keeps the connection open
                        self.wfile.write(message.encode("utf-8"))
                        self.wfile.flush()
                except OSError:                               # the browser went away
                    pass
                finally:
                    with screen._lock:
                        screen._clients.remove(inbox)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
