# Cianki

Cianki is my personal build of [Anki](https://github.com/ankitects/anki): upstream Anki,
kept current with every stable release, plus two built-in additions.

1. **MCP servers for Claude and Codex** (`claude/`). Agents can read and edit the
   collection whether or not the app is open, with live UI and undo when it is.
2. **Local text-to-speech** (`cianki/`, `pylib/anki/cianki_tts.py`). This uses
   [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) running on Apple Silicon through
   [mlx-audio](https://github.com/Blaizzy/mlx-audio). It needs no cloud service and no API
   key, and it never sends card text off the machine.

## Local text-to-speech

To turn it on for a field, go to **Tools → Manage Note Types → Fields**, select the field and tick
**Generate audio with local text-to-speech**. Cianki then makes these changes:

- It adds a `<Field> Audio` field and puts `{{<Field> Audio}}` after `{{<Field>}}` in the card templates.
- Each time a note is saved, it writes `[sound:tts-<url-safe text>-<hash8>.mp3]` into the
  audio field. This applies to saves from the editor, Browse, Add, the MCP or scripts. If that
  file is not in the media folder yet, a long-running worker generates it in the background.
  The worker loads the model once, so a warm sentence takes about 0.3 s.
- The filename is the check. It comes from the text, so when you edit the text the name
  changes and new audio is generated. The 8-character hash covers the voice and the full
  text, so long texts that truncate to the same slug never collide.
- Existing notes are filled in when you save the dialog.

Setup on Apple Silicon needs `uv` and `ffmpeg`. It installs about 600 MB into
`~/.local/share/cianki` and leaves Anki's own Python alone:

```sh
cianki/setup-tts.sh                    # venv + Kokoro (no torch) and one test sentence
out/pyenv/bin/python cianki/test_tts.py  # end-to-end check on a temporary collection
```

Settings are environment variables: `CIANKI_TTS_VOICE` (default `af_heart`; see the
[Kokoro voices](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)),
`CIANKI_TTS_SPEED` and `CIANKI_TTS_MODEL`.

## Build and install

```sh
RELEASE=1 ./ninja installer:build      # builds out/installer/build/anki/macos/app/Anki.app
claude/update-anki.sh --install        # or let launchd merge upstream releases and reinstall
```

Cianki is licensed under the AGPL-3.0, the same as Anki. Everything below is upstream's README.

---

# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ankitects_anki&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ankitects_anki)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
