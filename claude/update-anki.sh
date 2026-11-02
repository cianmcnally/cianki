#!/bin/bash
# Merge the newest upstream stable Anki release into our `cian` branch, rebuild Anki.app,
# and install it to /Applications. Run by launchd (claude/com.cian.anki-update.plist).
#   update-anki.sh            update if a newer release exists
#   update-anki.sh --install  rebuild + reinstall even if up to date
set -euo pipefail
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."

APP=/Applications/Anki.app
BUILT=out/installer/build/anki/macos/app/Anki.app
notify() { echo "$1"; osascript -e "display notification \"$1\" with title \"Anki updater\"" || true; }
anki_running() { pgrep -f "$APP/Contents/MacOS/Anki" >/dev/null || pgrep -f "tools/run.py" >/dev/null; }

[ "$(git branch --show-current)" = cian ] || { notify "not on branch cian - skipped"; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { notify "uncommitted changes in ~/Desktop/anki - skipped"; exit 1; }

git fetch --quiet --tags origin
# stable releases only (26.09.3), not betas/rc (26.09b2)
latest=$(git tag -l | grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?$' | sort -V | tail -1)

if git merge-base --is-ancestor "$latest" HEAD && [ "${1:-}" != --install ]; then
  echo "$(date '+%F %T') up to date ($latest)"; exit 0
fi
if anki_running; then
  echo "$(date '+%F %T') $latest available but Anki is open - will retry next run"; exit 0
fi

if ! git merge-base --is-ancestor "$latest" HEAD; then
  git merge --no-edit -m "Merge upstream $latest" "$latest" || {
    git merge --abort; notify "merge of $latest conflicted - aborted, needs a look"; exit 1; }
fi
git submodule update --init --quiet
RELEASE=1 ./ninja installer:build

anki_running && { notify "Anki opened during build - install deferred"; exit 0; }
rm -rf "$APP.new" && ditto "$BUILT" "$APP.new"
rm -rf "$APP" && mv "$APP.new" "$APP"
notify "Anki updated to $latest (+ Claude/Codex MCP)"
