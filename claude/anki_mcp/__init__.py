"""anki-mcp add-on: serves tools.py over MCP streamable HTTP on 127.0.0.1 while Anki is open.
Agents normally use server.py (stdio), which forwards here when Anki is running and opens
the collection file itself when it isn't."""

import contextlib
import hmac
import json
import secrets
import threading
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aqt import gui_hooks, mw

from . import tools

tools.MW = mw
TOKEN_FILE = tools.USER / "token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
TOKEN = TOKEN_FILE.read_text().strip()
PORT = (mw.addonManager.getConfig(__name__) or {}).get("port", 27701)


def on_main(fn):
    fut = Future()

    def run():
        try:
            fut.set_result(fn())
        except BaseException as e:
            fut.set_exception(e)

    mw.taskman.run_on_main(run)
    return fut.result(timeout=300)


def run_tool(name, args):
    _, _, fn, writes = tools.TOOLS[name]
    col = mw.col
    if col is None:
        raise RuntimeError("no Anki profile is open")
    if not writes:
        return fn(col, **args)
    pos = col.add_custom_undo_entry(f"MCP: {name}")
    try:
        return fn(col, **args)
    finally:
        with contextlib.suppress(Exception):
            col.merge_undo_entries(pos)
        mw.reset()


def call(name, args):
    return tools.result(lambda: on_main(lambda: run_tool(name, args)))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # no server-initiated SSE stream
        self.send(405)

    do_DELETE = do_GET

    def do_POST(self):
        # token blocks browsers/other local pages (CSRF, DNS rebinding) from reaching run_python
        if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            return self.send(401, {"error": "bad or missing bearer token"})
        if self.path.rstrip("/") != "/mcp":
            return self.send(404)
        try:
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self.send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        batch = isinstance(msg, list)
        out = [r for m in (msg if batch else [msg]) if (r := tools.handle(m, call)) is not None]
        self.send(200, out if batch else out[0]) if out else self.send(202)


def inject_css(web_content, context):
    if tools.CSS_FILE.exists() and (css := tools.CSS_FILE.read_text()):
        web_content.head += f'<style id="anki-mcp-css">{css}</style>'


def start():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        return print(f"anki-mcp: port {PORT} unavailable ({e})")
    threading.Thread(target=srv.serve_forever, daemon=True).start()


gui_hooks.webview_will_set_content.append(inject_css)
start()
