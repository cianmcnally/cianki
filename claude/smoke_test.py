"""End-to-end check of the MCP over stdio (server.py).
Headless: runs every tool against a temp COPY of the real collection.
Live: if Anki is open, also does a read-only call through the app.
Usage: out/pyenv/bin/python claude/smoke_test.py"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = HERE.parent / "out/pyenv/bin/python"
SERVER = HERE / "anki_mcp/server.py"
sys.path[:0] = [str(HERE / "anki_mcp"), str(HERE.parent / "pylib"), str(HERE.parent / "out/pylib")]
BASE = Path.home() / "Library/Application Support/Anki2"


class Client:
    def __init__(self, env=None):
        self.p = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                  env={**__import__("os").environ, **(env or {})})
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def call(self, tool, **args):
        res = self.rpc("tools/call", {"name": tool, "arguments": args})["result"]
        assert not res["isError"], res["content"][0]["text"]
        return json.loads(res["content"][0]["text"])

    def close(self):
        self.p.stdin.close()
        self.p.wait(10)


DECK, NT = "anki-mcp-smoke", "anki-mcp-smoke-type"
with tempfile.TemporaryDirectory() as tmp:
    import tools  # only for prefs(); no collection access

    copy = Path(tmp) / "collection.anki2"
    shutil.copy(BASE / tools.prefs()[0] / "collection.anki2", copy)
    c = Client({"ANKI_COLLECTION": str(copy)})
    assert c.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["serverInfo"]["name"] == "anki"
    names = {t["name"] for t in c.rpc("tools/list")["result"]["tools"]}
    assert {"add_notes", "update_notetype", "run_python", "set_ui_css", "sync", "update_anki"} <= names, names

    ids = c.call("add_notes", notes=[{"deck": DECK, "fields": {"Front": "smoke Q", "Back": "A"}, "tags": ["t1"]}])["added"]
    assert len(ids) == 1
    dup = c.call("add_notes", notes=[{"deck": DECK, "fields": {"Front": "smoke Q", "Back": "A"}}])
    assert dup["added"] == [] and dup["skipped_duplicates"] == ["smoke Q"], dup

    c.call("update_notes", updates=[{"id": ids[0], "fields": {"Back": "B2"}, "tags": ["t2"]}])
    n = c.call("find_notes", query=f'deck:"{DECK}"')["notes"][0]
    assert n["fields"]["Back"] == "B2" and n["tags"] == ["t2"] and n["deck"] == DECK, n

    nt = c.call("update_notetype", name=NT, clone_from="Basic", css=".card{color:red}", add_fields=["Extra"],
                templates={"Card 1": {"afmt": "{{FrontSide}}<hr id=answer>{{Back}}<br>{{Extra}}"}})
    assert nt["css"] == ".card{color:red}" and "Extra" in nt["fields"] and "{{Extra}}" in nt["templates"][0]["afmt"]

    r = c.call("run_python", code="print('hi'); result = col.note_count()")
    assert r["stdout"] == "hi\n" and r["result"] >= 1 and c.call("run_python", code="result = mw")["result"] is None

    assert c.call("delete_notes", ids=ids)["deleted"] == 1
    c.close()
    print("headless: all tools passed (on a temp copy)")

live = Client()
try:
    decks = live.call("list_decks")
    who = live.call("run_python", code="result = 'app' if mw else 'headless'")["result"]
    print(f"live ({who}): {len(decks)} decks")
finally:
    live.close()
