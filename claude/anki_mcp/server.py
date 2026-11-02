"""Stdio MCP server for Claude Code / Codex / any agent. Anki open -> forwards each call to the
in-app server (live UI). Anki closed -> opens the collection file itself with the source-built
`anki` library, runs the tool, closes it.
Run: ~/src/anki/out/pyenv/bin/python ~/src/anki/claude/anki_mcp/server.py"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(HERE), str(REPO / "pylib"), str(REPO / "out/pylib")]

import tools  # noqa: E402
from anki.collection import Collection  # noqa: E402

OUT, sys.stdout = sys.stdout, sys.stderr  # keep stray prints off the JSON-RPC channel
URL = "http://127.0.0.1:27701/mcp"
COLLECTION = os.environ.get("ANKI_COLLECTION")  # set = always headless on that file (tests)


def via_app(name, args):
    token = (tools.USER / "token").read_text().strip()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    req = urllib.request.Request(
        URL, json.dumps(body).encode(), {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=330) as r:
        return json.load(r)["result"]


def headless(name, args):
    fn = tools.TOOLS[name][2]
    if name in tools.NO_COLLECTION:
        return fn(None, **args)
    col = Collection(COLLECTION or str(tools.BASE / tools.prefs()[0] / "collection.anki2"))
    try:
        return fn(col, **args)
    finally:
        col.close()


def call(name, args):
    if COLLECTION:
        return tools.result(lambda: headless(name, args))
    try:
        return via_app(name, args)
    except (FileNotFoundError, urllib.error.URLError) as e:
        if isinstance(e, urllib.error.URLError) and not isinstance(e.reason, ConnectionRefusedError):
            return {"content": [{"type": "text", "text": f"Anki is open but its MCP add-on failed: {e}"}], "isError": True}
    return tools.result(lambda: headless(name, args))


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if (out := tools.handle(msg, call)) is not None:
        OUT.write(json.dumps(out, ensure_ascii=False) + "\n")
        OUT.flush()
