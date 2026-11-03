#!/bin/sh
# Installs Cianki's local TTS: an isolated venv with mlx-audio + Kokoro-82M
# (no torch), linked to the worker in this repo. Apple Silicon + ffmpeg needed.
set -eu
HOME_DIR="${CIANKI_TTS_HOME:-$HOME/.local/share/cianki}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
command -v ffmpeg >/dev/null || { echo "need ffmpeg: brew install ffmpeg"; exit 1; }
mkdir -p "$HOME_DIR"
cd "$HOME_DIR"
[ -d tts-venv ] || uv venv -q --python 3.12 tts-venv
export VIRTUAL_ENV="$HOME_DIR/tts-venv"
# misaki[en] would pull torch via spacy-curated-transformers; Kokoro only needs these.
uv pip install -q mlx-audio misaki num2words spacy phonemizer-fork espeakng-loader \
  "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
ln -sf "$REPO/cianki/tts_worker.py" tts_worker.py
echo '{"text":"Cianki text to speech is ready.","path":"/tmp/cianki-tts-test.mp3","voice":"af_heart","speed":1.0}' \
  | tts-venv/bin/python tts_worker.py
