"""MCP tools + JSON-RPC handling shared by the in-Anki server (__init__.py) and the
headless server (server.py). No aqt imports: `MW` is set only when running inside Anki."""

import contextlib
import io
import json
import pickle
import sqlite3
import subprocess
import time
import traceback
from pathlib import Path

import anki
import anki.collection  # noqa: F401  must load before anki.notes (circular import)
from anki.notes import NoteFieldsCheckResult
from anki.sync import SyncAuth

MW = None  # aqt main window when loaded as an add-on
HERE = Path(__file__).resolve().parent
USER = HERE / "user_files"  # survives add-on updates
USER.mkdir(exist_ok=True)
CSS_FILE = USER / "ui.css"
BASE = Path.home() / "Library/Application Support/Anki2"
UPDATER = HERE.parent / "update-anki.sh"

INSTRUCTIONS = """Direct access to the user's Anki collection. Works whether or not Anki is open:
open -> edits the live app (UI refreshes; each write = one Edit>Undo step "MCP: <tool>");
closed -> edits the collection file directly.
Search uses Anki search syntax (e.g. 'deck:"Lovable" tag:growth', 'note:Basic', 'added:1').
Card design = note type templates + CSS (get_notetype / update_notetype).
App-wide look = set_ui_css. sync = AnkiWeb sync (also works headless).
Anything else = run_python (col always; mw only when Anki is open). For persistent app
behaviour write a real add-on into ~/Library/Application Support/Anki2/addons21.
update_anki merges the newest upstream Anki release into the user's source build and reinstalls it."""

TOOLS: dict = {}


def tool(desc, props=None, required=(), writes=False):
    def deco(fn):
        schema = {"type": "object", "properties": props or {}, "required": list(required)}
        TOOLS[fn.__name__] = (desc, schema, fn, writes)
        return fn

    return deco


S, I, B, OBJ = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "object"}
ARR = lambda item: {"type": "array", "items": item}


def prefs():
    """(profile name, profile dict) of the last-used Anki profile, read from prefs21.db."""
    db = sqlite3.connect(f"file:{BASE / 'prefs21.db'}?mode=ro", uri=True)
    try:
        rows = {n: pickle.Unpickler(io.BytesIO(d), errors="ignore").load()
                for n, d in db.execute("select name, data from profiles")}
    finally:
        db.close()
    name = rows["_global"].get("last_loaded_profile_name") or next(n for n in rows if n != "_global")
    return name, rows[name]


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


@tool("Get a note type's fields, card templates (qfmt/afmt HTML) and CSS.", {"name": S}, ["name"])
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
    "add_fields: [names]. css replaces the note type's whole stylesheet - read it first.",
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
    "add-on. Persists; empty string removes it. Returns the previous CSS.",
    {"css": S},
    ["css"],
)
def set_ui_css(col, css):
    old = CSS_FILE.read_text() if CSS_FILE.exists() else ""
    CSS_FILE.write_text(css)
    if MW:  # live-apply; otherwise picked up at next launch
        js = (
            "(()=>{let s=document.getElementById('anki-mcp-css')||document.head.appendChild("
            "Object.assign(document.createElement('style'),{id:'anki-mcp-css'}));"
            f"s.textContent={json.dumps(css)};}})()"
        )
        for web in (MW.web, MW.toolbar.web, MW.bottomWeb):
            web.eval(js)
    return {"previous_css": old}


@tool(
    "Run Python against the collection with col, anki (and mw, aqt when Anki is open) in scope. "
    "Set `result` to return a value; stdout is captured.",
    {"code": S},
    ["code"],
    writes=True,
)
def run_python(col, code):
    env = {"col": col, "anki": anki, "mw": MW, "result": None}
    if MW:
        import aqt

        env["aqt"] = aqt
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(code, env)
    return {"result": env["result"], "stdout": out.getvalue()}


@tool("Sync with AnkiWeb (collection + media). Works with Anki closed too.")
def sync(col):
    if MW:
        MW.on_sync_button_clicked()
        return "sync started in Anki"
    _, prof = prefs()
    if not prof.get("syncKey"):
        raise RuntimeError("not logged in to AnkiWeb - log in once in Anki")
    auth = SyncAuth(hkey=prof["syncKey"], endpoint=prof.get("currentSyncUrl") or prof.get("customSyncUrl"))
    out = col.sync_collection(auth, sync_media=prof.get("syncMedia", True))
    if out.required in (out.FULL_SYNC, out.FULL_DOWNLOAD, out.FULL_UPLOAD):
        return {"status": "AnkiWeb needs a full one-way sync - open Anki and press Sync to choose direction"}
    while col.media_sync_status().active:
        time.sleep(0.5)
    return {"status": "synced", "server_message": out.server_message}


@tool(
    "Merge the newest upstream stable Anki release into the user's source fork (~/src/anki, branch "
    "cian), rebuild and reinstall /Applications/Anki.app. Runs in the background (several minutes); "
    "install is deferred while Anki is open. force=true rebuilds even if already up to date.",
    {"force": B},
)
def update_anki(col, force=False):
    log = Path.home() / "Library/Logs/anki-update.log"
    with log.open("a") as f:
        subprocess.Popen([str(UPDATER)] + (["--install"] if force else []),
                         stdout=f, stderr=f, start_new_session=True)
    return {"started": True, "log": str(log)}


NO_COLLECTION = {"update_anki"}


def result(fn):
    try:
        text, err = json.dumps(fn(), ensure_ascii=False, default=str), False
    except Exception:
        text, err = traceback.format_exc(limit=4), True
    return {"content": [{"type": "text", "text": text}], "isError": err}


def handle(msg, call):
    """One JSON-RPC message -> response (None for notifications). call(name, args) -> tool result."""
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {
            "protocolVersion": p.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "anki", "version": "0.2.0"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": [{"name": k, "description": d, "inputSchema": s} for k, (d, s, _, _) in TOOLS.items()]}
    elif method == "tools/call" and p.get("name") in TOOLS:
        res = call(p["name"], p.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}
