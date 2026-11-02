"""anki-mcp: an MCP server living inside Anki.

Speaks MCP "streamable HTTP" (stateless, plain JSON responses) on 127.0.0.1, so
Claude Code, Codex or any MCP client can drive the *live* collection while Anki
is open. Every write tool call becomes one undo step ("MCP: <tool>") in Anki.
"""

import contextlib
import hmac
import io
import json
import secrets
import threading
import traceback
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anki
import aqt
from anki.notes import NoteFieldsCheckResult
from aqt import gui_hooks, mw

USER = Path(__file__).parent / "user_files"  # survives add-on updates
USER.mkdir(exist_ok=True)
TOKEN_FILE, CSS_FILE = USER / "token", USER / "ui.css"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
TOKEN = TOKEN_FILE.read_text().strip()
PORT = (mw.addonManager.getConfig(__name__) or {}).get("port", 27701)

INSTRUCTIONS = """Direct access to the user's running Anki (live collection, no restart needed).
Search uses Anki search syntax (e.g. 'deck:"Lovable" tag:growth', 'note:Basic', 'added:1').
Each write call is one undo step in Anki (Edit > Undo "MCP: <tool>").
Card design = note type templates + CSS (get_notetype / update_notetype).
App-wide look = set_ui_css. Anything else (scheduling, deck options, hooks, add-on-like
behaviour) = run_python with mw/col in scope; for persistent behaviour write a real add-on
into the addons21 folder (path: mw.addonManager.addonsFolder())."""

TOOLS: dict = {}


def tool(desc, props=None, required=(), writes=False):
    def deco(fn):
        schema = {"type": "object", "properties": props or {}, "required": list(required)}
        TOOLS[fn.__name__] = (desc, schema, fn, writes)
        return fn

    return deco


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
ARR = lambda item: {"type": "array", "items": item}
OBJ = {"type": "object"}


def note_json(col, n):
    cards = n.cards()
    return {
        "id": n.id,
        "notetype": n.note_type()["name"],
        "deck": col.decks.name(cards[0].did) if cards else None,
        "fields": dict(n.items()),
        "tags": n.tags,
        "card_ids": [c.id for c in cards],
    }


def notetype(col, name):
    if not (m := col.models.by_name(name)):
        raise ValueError(f"no note type {name!r}; see list_notetypes")
    return m


# ---------------------------------------------------------------- tools


@tool("List decks with card counts.")
def list_decks(col):
    return [
        {"id": d.id, "name": d.name, "cards": col.decks.card_count(d.id, include_subdecks=True)}
        for d in col.decks.all_names_and_ids()
    ]


@tool("List note types (card designs) and their field names.")
def list_notetypes(col):
    return [
        {"id": m["id"], "name": m["name"], "fields": [f["name"] for f in m["flds"]]}
        for m in col.models.all()
    ]


@tool(
    "Search notes with Anki search syntax. Returns fields, tags, deck, card ids.",
    {"query": S, "limit": I, "offset": I},
    ["query"],
)
def find_notes(col, query, limit=50, offset=0):
    ids = col.find_notes(query)
    return {
        "total": len(ids),
        "notes": [note_json(col, col.get_note(i)) for i in ids[offset : offset + limit]],
    }


@tool(
    "Add notes. Each: {deck, notetype='Basic', fields:{name:html}, tags:[]}. Deck is created "
    "if missing. Duplicates (same first field in that note type) are skipped unless allow_duplicates.",
    {"notes": ARR(OBJ), "allow_duplicates": B},
    ["notes"],
    writes=True,
)
def add_notes(col, notes, allow_duplicates=False):
    added, skipped = [], []
    for spec in notes:
        n = col.new_note(notetype(col, spec.get("notetype", "Basic")))
        for k, v in spec["fields"].items():
            n[k] = v
        n.tags = spec.get("tags", [])
        if not allow_duplicates and n.fields_check() == NoteFieldsCheckResult.DUPLICATE:
            skipped.append(n.fields[0][:80])
            continue
        col.add_note(n, col.decks.id(spec["deck"], create=True))
        added.append(n.id)
    return {"added": added, "skipped_duplicates": skipped}


@tool(
    "Edit notes. Each: {id, fields?:{name:html}, tags?:[] (replaces), deck?:name (moves its cards)}.",
    {"updates": ARR(OBJ)},
    ["updates"],
    writes=True,
)
def update_notes(col, updates):
    for u in updates:
        n = col.get_note(u["id"])
        for k, v in u.get("fields", {}).items():
            n[k] = v
        if "tags" in u:
            n.tags = u["tags"]
        col.update_note(n)
        if "deck" in u:
            col.set_deck(n.card_ids(), col.decks.id(u["deck"], create=True))
    return {"updated": len(updates)}


@tool("Delete notes (and their cards) by id.", {"ids": ARR(I)}, ["ids"], writes=True)
def delete_notes(col, ids):
    return {"deleted": col.remove_notes(ids).count}


@tool(
    "Get a note type's fields, card templates (qfmt/afmt HTML) and CSS.",
    {"name": S},
    ["name"],
)
def get_notetype(col, name):
    m = notetype(col, name)
    return {
        "name": m["name"],
        "fields": [f["name"] for f in m["flds"]],
        "templates": [{"name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]} for t in m["tmpls"]],
        "css": m["css"],
    }


@tool(
    "Change card design. clone_from creates `name` as a copy of another note type first. "
    "templates: {template_name: {qfmt?, afmt?}} (unknown names are added as new card types). "
    "add_fields: [names]. css replaces the note type's whole stylesheet.",
    {"name": S, "clone_from": S, "css": S, "templates": OBJ, "add_fields": ARR(S)},
    ["name"],
    writes=True,
)
def update_notetype(col, name, clone_from=None, css=None, templates=None, add_fields=()):
    if clone_from:
        m = col.models.copy(notetype(col, clone_from), add=False)
        m["name"] = name
        col.models.add_dict(m)
    m = notetype(col, name)
    for f in add_fields:
        col.models.add_field(m, col.models.new_field(f))
    for tname, t in (templates or {}).items():
        existing = next((x for x in m["tmpls"] if x["name"] == tname), None)
        if not existing:
            existing = col.models.new_template(tname)
            col.models.add_template(m, existing)
        existing.update({k: v for k, v in t.items() if k in ("qfmt", "afmt")})
    if css is not None:
        m["css"] = css
    col.models.update_dict(m)
    return get_notetype(col, name)


@tool(
    "Restyle Anki's own UI (deck list, overview, reviewer, toolbar) with CSS, like a theme "
    "add-on. Persists across restarts; empty string removes it. Returns the previous CSS.",
    {"css": S},
    ["css"],
)
def set_ui_css(col, css):
    old = CSS_FILE.read_text() if CSS_FILE.exists() else ""
    CSS_FILE.write_text(css)
    js = (
        "(()=>{let s=document.getElementById('anki-mcp-css')||document.head.appendChild("
        f"Object.assign(document.createElement('style'),{{id:'anki-mcp-css'}}));s.textContent={json.dumps(css)};}})()"
    )
    for web in (mw.web, mw.toolbar.web, mw.bottomWeb):
        web.eval(js)
    return {"previous_css": old}


@tool(
    "Run Python inside Anki (main thread) with mw, col, aqt, anki in scope - full add-on power. "
    "Set `result` to return a value; stdout is captured. Runs as one undo step.",
    {"code": S},
    ["code"],
    writes=True,
)
def run_python(col, code):
    env = {"mw": mw, "col": col, "aqt": aqt, "anki": anki, "result": None}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, env)
    return {"result": env["result"], "stdout": out.getvalue()}


@tool("Start a normal AnkiWeb sync (same as pressing Sync).")
def sync(col):
    mw.on_sync_button_clicked()
    return "sync started"


# ---------------------------------------------------------------- plumbing


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
    _, _, fn, writes = TOOLS[name]
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


def handle(msg):
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification, e.g. notifications/initialized
        return None
    if method == "initialize":
        res = {
            "protocolVersion": p.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "anki", "version": "0.1.0"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {
            "tools": [
                {"name": k, "description": d, "inputSchema": s} for k, (d, s, _, _) in TOOLS.items()
            ]
        }
    elif method == "tools/call" and p.get("name") in TOOLS:
        try:
            out = on_main(lambda: run_tool(p["name"], p.get("arguments") or {}))
            text, err = json.dumps(out, ensure_ascii=False, default=str), False
        except Exception:
            text, err = traceback.format_exc(limit=4), True
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


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
        out = [r for m in (msg if batch else [msg]) if (r := handle(m)) is not None]
        self.send(200, out if batch else out[0]) if out else self.send(202)


def inject_css(web_content, context):
    if CSS_FILE.exists() and (css := CSS_FILE.read_text()):
        web_content.head += f'<style id="anki-mcp-css">{css}</style>'


def start():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        return print(f"anki-mcp: port {PORT} unavailable ({e})")
    threading.Thread(target=srv.serve_forever, daemon=True).start()


gui_hooks.webview_will_set_content.append(inject_css)
start()
