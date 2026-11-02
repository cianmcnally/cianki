"""End-to-end check against a running Anki with anki_mcp loaded. Cleans up after itself.
Usage: python3 smoke_test.py"""

import json
import urllib.error
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:27701/mcp"
TOKEN = (Path(__file__).parent / "anki_mcp/user_files/token").read_text().strip()
DECK, NT = "anki-mcp-smoke", "anki-mcp-smoke-type"


def rpc(method, params=None, token=TOKEN):
    req = urllib.request.Request(
        URL,
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))


def call(tool, **args):
    res = rpc("tools/call", {"name": tool, "arguments": args})["result"]
    assert not res["isError"], res["content"][0]["text"]
    return json.loads(res["content"][0]["text"])


try:
    rpc("ping", token="wrong")
    raise AssertionError("bad token accepted")
except urllib.error.HTTPError as e:
    assert e.code == 401

assert rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["serverInfo"]["name"] == "anki"
names = {t["name"] for t in rpc("tools/list")["result"]["tools"]}
assert {"add_notes", "update_notetype", "run_python", "set_ui_css"} <= names, names

ids = call("add_notes", notes=[{"deck": DECK, "fields": {"Front": "smoke Q", "Back": "A"}, "tags": ["t1"]}])["added"]
assert len(ids) == 1
dup = call("add_notes", notes=[{"deck": DECK, "fields": {"Front": "smoke Q", "Back": "A"}}])
assert dup["added"] == [] and dup["skipped_duplicates"] == ["smoke Q"], dup

call("update_notes", updates=[{"id": ids[0], "fields": {"Back": "B2"}, "tags": ["t2"]}])
n = call("find_notes", query=f'deck:"{DECK}"')["notes"][0]
assert n["fields"]["Back"] == "B2" and n["tags"] == ["t2"] and n["deck"] == DECK, n

nt = call("update_notetype", name=NT, clone_from="Basic", css=".card{color:red}", add_fields=["Extra"],
          templates={"Card 1": {"afmt": "{{FrontSide}}<hr id=answer>{{Back}}<br>{{Extra}}"}})
assert nt["css"] == ".card{color:red}" and "Extra" in nt["fields"] and "{{Extra}}" in nt["templates"][0]["afmt"]

prev = call("set_ui_css", css="body{outline:1px solid red}")["previous_css"]
call("set_ui_css", css=prev)

r = call("run_python", code="print('hi'); result = col.note_count()")
assert r["stdout"] == "hi\n" and r["result"] >= 1, r

assert call("delete_notes", ids=ids)["deleted"] == 1
call("run_python", code=f"col.models.remove(col.models.id_for_name({NT!r})); col.decks.remove([col.decks.id_for_name({DECK!r})])")
assert not any(d["name"] == DECK for d in call("list_decks"))
print("smoke test passed")
