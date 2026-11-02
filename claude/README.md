# anki-mcp

MCP server that runs *inside* Anki (as an add-on), so any agent edits the live collection
while Anki is open — no closing Anki, no collection-lock dance.

- Lives in the `cian` branch of the Anki fork at `~/Desktop/anki/claude/`. Built app: /Applications/Anki.app.
- `update-anki.sh` (launchd `com.cian.anki-update`, at login + 04:00/13:00) merges new upstream stable tags, rebuilds, reinstalls; log ~/Library/Logs/anki-update.log.
- Add-on: `anki_mcp/` symlinked into `~/Library/Application Support/Anki2/addons21/anki_mcp`.
- Endpoint: `http://127.0.0.1:27701/mcp` (MCP streamable HTTP), header
  `Authorization: Bearer $(cat anki_mcp/user_files/token)`.

Tools: `list_decks`, `list_notetypes`, `find_notes`, `add_notes`, `update_notes`, `delete_notes`,
`get_notetype`, `update_notetype` (card templates/CSS/fields, clone), `set_ui_css` (theme Anki's own UI),
`run_python` (anything an add-on can do), `sync` (AnkiWeb).
Each write call = one Anki undo step named `MCP: <tool>`.

## Connect an agent

```sh
# Claude Code (done)
claude mcp add --scope user --transport http anki http://127.0.0.1:27701/mcp \
  --header "Authorization: Bearer $(cat anki_mcp/user_files/token)"
```

```toml
# Codex ~/.codex/config.toml (done)
[mcp_servers.anki]
url = "http://127.0.0.1:27701/mcp"
http_headers = { Authorization = "Bearer <token>" }
```

Anything else: point its MCP HTTP client at the URL with that header.

## Check

With Anki open: `python3 smoke_test.py` (creates and removes its own deck/note type).
