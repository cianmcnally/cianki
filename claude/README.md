# Claude/Codex MCP for Anki (branch `cian`)

This fork is Anki built from source and installed as /Applications/Anki.app, plus an MCP that
gives agents direct access to the collection whether or not Anki is open.

- `anki_mcp/server.py`: the MCP agents launch (stdio). Anki open → forwards to the in-app server
  (live UI, one undo step per call). Anki closed → opens `User 1/collection.anki2` itself.
- `anki_mcp/__init__.py`: Anki add-on (symlinked into `addons21/anki_mcp`), in-app server on
  127.0.0.1:27701 with a bearer token in `anki_mcp/user_files/token`.
- `anki_mcp/tools.py`: the tools: list_decks, list_notetypes, find_notes, add_notes, update_notes,
  delete_notes, get_notetype, update_notetype, set_ui_css, run_python, sync, update_anki.
- `update-anki.sh` + `com.cian.anki-update.plist` (launchd: at login, 04:00, 13:00): merges the newest
  upstream stable tag into `cian`, rebuilds, reinstalls /Applications/Anki.app (waits if Anki is open).
  Log: ~/Library/Logs/anki-update.log.

## Connect an agent

```sh
claude mcp add -s user anki -- ~/src/anki/out/pyenv/bin/python ~/src/anki/claude/anki_mcp/server.py
```

```toml
# ~/.codex/config.toml
[mcp_servers.anki]
command = "/Users/cianmcnally/src/anki/out/pyenv/bin/python"
args = ["/Users/cianmcnally/src/anki/claude/anki_mcp/server.py"]
```

Any other agent: run the same command as a stdio MCP server.

## Check

`out/pyenv/bin/python claude/smoke_test.py`: every tool, run headless on a temp copy of the collection,
plus a read-only live call.
