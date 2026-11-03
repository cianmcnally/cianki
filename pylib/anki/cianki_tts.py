# Cianki: built-in local text-to-speech (Kokoro-82M on MLX).
#
# A field flagged with "cianki_tts" in its notetype config gets a sibling
# "<Field> Audio" field. Whenever a note is saved, the audio field is set to
# [sound:tts-<url-safe text>-<hash>.mp3]; if that file isn't in the media
# folder yet it is generated in the background by a persistent worker process
# (cianki/tts_worker.py running in its own venv, see cianki/setup-tts.sh).
# Edit the text -> the expected filename changes -> new audio is generated.

from __future__ import annotations

import hashlib
import html
import json
import os
import queue
import re
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki.collection import Collection, OpChanges
    from anki.models import NotetypeDict
    from anki.notes import Note

FLAG = "cianki_tts"
HOME = Path(os.environ.get("CIANKI_TTS_HOME", Path.home() / ".local/share/cianki"))
PYTHON = HOME / "tts-venv/bin/python"
WORKER = HOME / "tts_worker.py"
VOICE = os.environ.get("CIANKI_TTS_VOICE", "af_heart")
SPEED = float(os.environ.get("CIANKI_TTS_SPEED", "1.0"))


def audio_field_name(field: str) -> str:
    return f"{field} Audio"


def available() -> bool:
    return PYTHON.exists() and WORKER.exists()


def speakable_text(field_html: str) -> str:
    text = re.sub(r"\{\{c\d+::(.*?)(::.*?)?\}\}", r"\1", field_html, flags=re.S)
    # stdlib only: anki.utils.strip_html needs GUI i18n, absent in headless/MCP use
    text = re.sub(
        r"<(script|style)\b.*?</\1>|\[sound:[^\]]*\]|<[^>]+>",
        " ",
        text,
        flags=re.S | re.I,
    )
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def audio_filename(text: str) -> str:
    """URL-safe text slug + hash of (voice, speed, full text).

    The slug keeps names readable; the hash keeps truncated/non-latin texts
    unique and changes when the voice does, so stale audio is never reused.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:80].rstrip("-")
    digest = hashlib.sha1(f"{VOICE}|{SPEED}|{text}".encode()).hexdigest()[:8]
    return f"tts-{slug or 'audio'}-{digest}.mp3"


def tts_fields(notetype: NotetypeDict) -> list[str]:
    return [f["name"] for f in notetype["flds"] if f.get(FLAG)]


def enable_field(col: Collection, notetype: NotetypeDict, field: str) -> None:
    """Flag `field` for TTS, adding '<field> Audio' and template references.
    Caller saves the notetype (this only mutates the dict)."""
    mm = col.models
    fld = next(f for f in notetype["flds"] if f["name"] == field)
    fld[FLAG] = True
    audio = audio_field_name(field)
    if audio in mm.field_names(notetype):
        return
    mm.add_field(notetype, mm.new_field(audio))
    for tmpl in notetype["tmpls"]:
        for side in ("qfmt", "afmt"):
            if "{{%s}}" % field in tmpl[side]:
                tmpl[side] = tmpl[side].replace(
                    "{{%s}}" % field, "{{%s}}{{%s}}" % (field, audio), 1
                )


# Note hook: keeps the audio field in step with the text field.
##########################################################################


def on_note_will_flush(note: Note) -> None:
    fields = tts_fields(note.note_type())
    if not fields or not available():
        return
    media_dir = note.col.media.dir()
    for field in fields:
        audio = audio_field_name(field)
        if audio not in note:
            continue
        text = speakable_text(note[field])
        if not text:
            note[audio] = ""
            continue
        name = audio_filename(text)
        note[audio] = f"[sound:{name}]"
        path = os.path.join(media_dir, name)
        if not os.path.exists(path):
            _jobs.put((text, path))


def backfill(col: Collection, notetype: NotetypeDict, search: str = "") -> OpChanges:
    """Re-save every note of `notetype` (optionally narrowed by `search`) so
    the hook fills audio fields and queues any missing audio."""
    query = f"mid:{notetype['id']}" + (f" ({search})" if search else "")
    return col.update_notes([col.get_note(nid) for nid in col.find_notes(query)])


# Background worker: one long-lived process keeps the model warm.
##########################################################################

_jobs: queue.Queue[tuple[str, str]] = queue.Queue()
_proc: subprocess.Popen[str] | None = None


def _generate(text: str, path: str) -> None:
    global _proc
    if os.path.exists(path):
        return
    if _proc is None or _proc.poll() is not None:
        _proc = subprocess.Popen(
            [str(PYTHON), str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
    assert _proc.stdin and _proc.stdout
    _proc.stdin.write(
        json.dumps(dict(text=text, path=path, voice=VOICE, speed=SPEED)) + "\n"
    )
    _proc.stdin.flush()
    reply: dict[str, Any] = json.loads(
        _proc.stdout.readline() or '{"error": "worker died"}'
    )
    if "error" in reply:
        print(f"cianki tts: {reply['error']}", file=sys.stderr)


def _run() -> None:
    while True:
        text, path = _jobs.get()
        try:
            _generate(text, path)
        except Exception as e:  # keep the thread alive; next job respawns worker
            print(f"cianki tts: {e}", file=sys.stderr)
        finally:
            _jobs.task_done()


def wait() -> None:
    """Block until all queued audio is written (for scripts/headless use)."""
    _jobs.join()


threading.Thread(target=_run, daemon=True, name="cianki-tts").start()
