# Runnable check: out/pyenv/bin/python cianki/test_tts.py  (fresh temp collection)
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "pylib"), str(REPO / "out/pylib")]
import anki.collection  # noqa: E402  (must precede other anki imports)
from anki import cianki_tts as tts  # noqa: E402

assert tts.available(), "run cianki/setup-tts.sh first"
assert tts.audio_filename("Hello, World!").startswith("tts-hello-world-")
assert tts.audio_filename("a" * 500) != tts.audio_filename("a" * 499)

col = anki.collection.Collection(os.path.join(tempfile.mkdtemp(), "c.anki2"))
assert tts.speakable_text("<b>Hi</b> {{c1::there::x}}<br>[sound:a.mp3]") == "Hi there"
nt = col.models.copy(col.models.by_name("Basic"))
tts.enable_field(col, nt, "Front")
col.models.update_dict(nt)
nt = col.models.get(nt["id"])
assert tts.tts_fields(nt) == ["Front"], "flag must survive the Rust round-trip"
assert "{{Front}}{{Front Audio}}" in nt["tmpls"][0]["qfmt"]

note = col.new_note(nt)
note["Front"], note["Back"] = "What is a rent review?", "x"
t = time.time()
col.add_note(note, col.decks.id("Default"))
tts.wait()
first = note["Front Audio"]
path = Path(col.media.dir(), first[7:-1])
assert path.stat().st_size > 1000, first
print(f"generated {path.name} in {time.time() - t:.1f}s (cold)")

note["Front"] = "What is a rent review notice?"
t = time.time()
col.update_note(note)
tts.wait()
assert (
    note["Front Audio"] != first
    and Path(col.media.dir(), note["Front Audio"][7:-1]).exists()
)
print(
    f"edited text -> regenerated {note['Front Audio']} in {time.time() - t:.1f}s (warm)"
)
col.close()
print("ok")
