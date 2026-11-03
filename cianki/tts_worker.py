# Cianki TTS worker: runs in its own venv (see setup-tts.sh), keeps Kokoro warm.
# Protocol: one JSON object per line on stdin {text, path, voice, speed};
# replies one JSON line {"ok": path} or {"error": msg}. Writes mp3 via ffmpeg.
import json
import os
import shutil
import subprocess
import sys

import numpy as np
from huggingface_hub import constants, try_to_load_from_cache
from mlx_audio.tts.utils import load_model

MODEL = os.environ.get("CIANKI_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

# cached model -> skip the hub's network check, so startup is instant/offline
constants.HF_HUB_OFFLINE = isinstance(try_to_load_from_cache(MODEL, "config.json"), str)
model = load_model(MODEL)
reply = sys.stdout
sys.stdout = sys.stderr  # keep library prints off the protocol channel

for line in sys.stdin:
    try:
        job = json.loads(line)
        parts = [
            np.asarray(r.audio, dtype=np.float32)
            for r in model.generate(
                text=job["text"],
                voice=job["voice"],
                speed=job["speed"],
                lang_code=job["voice"][0],
            )
        ]
        tmp = job["path"] + ".part.mp3"
        subprocess.run(
            [
                FFMPEG,
                "-loglevel",
                "error",
                "-y",
                "-f",
                "f32le",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-i",
                "-",
                "-q:a",
                "4",
                tmp,
            ],
            input=np.concatenate(parts).tobytes(),
            check=True,
        )
        os.replace(
            tmp, job["path"]
        )  # atomic: a half-written file never has the real name
        reply.write(json.dumps({"ok": job["path"]}) + "\n")
    except Exception as e:
        reply.write(json.dumps({"error": repr(e)}) + "\n")
    reply.flush()
