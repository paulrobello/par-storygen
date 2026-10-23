# Troubleshooting

Common runtime problems in par-storygen and how to resolve them. Each entry follows **Symptom → Likely cause → Fix → Verify**. For installation and provider setup, start with [README](../README.md); for implementation depth, see [ARCHITECTURE](./ARCHITECTURE.md).

## Table of Contents

- [Text provider errors](#text-provider-errors)
- [Image provider errors](#image-provider-errors)
- [Blank image panel](#blank-image-panel)
- [Text-to-speech produces no audio](#text-to-speech-produces-no-audio)
- [Web UI cannot reach the API](#web-ui-cannot-reach-the-api)

## Text provider errors

### Symptom: `AuthenticationError` / `401` during beat or wizard generation

**Likely cause:** The configured text provider's API key is missing, invalid, or belongs to a different provider than the one selected.

**Fix per provider:**

| Provider | Required variable | Notes |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | Default provider. Key must start with `sk-`. |
| OpenRouter | `OPENROUTER_API_KEY` + `STORYGEN_TEXT_PROVIDER=openrouter` | Key from openrouter.ai. |
| Ollama | _(none)_ | Local only; see [Ollama not reachable](#symptom-ollama-calls-fail-with-connectionerror-or-timeout). |

Set the key in your environment or `.env` file, or enter it under **Settings → Text provider**. Keys set as real environment variables override `.env`, which overrides Settings.

A `401` during catalog character creation occurs during the text step, before
portrait generation. The toast identifies text authentication, and the file log
records `stage: text_generation`. Check that the effective text base URL and key
belong to the same provider. The `openai` provider also supports custom
OpenAI-compatible endpoints; it still reads `OPENAI_API_KEY` when that variable
is set, overriding the key entered in Settings. The Settings status names this
override without showing key values. Image-provider keys and settings do not
repair a text-provider authentication failure. Correct the effective text
configuration before retrying; this error is not evidence of an image-model
request failure.

**Verify:** Run a new story; the wizard's Generate Characters step completes without an auth error.

### Symptom: Ollama calls fail with `ConnectionError` or timeout

**Likely cause:** `ollama serve` is not running, or `STORYGEN_TEXT_BASE_URL` points at the wrong host/port.

**Fix:**

```bash
ollama serve                       # start the local server (default :11434)
ollama pull qwen2.5:32b-instruct   # pull the model you configured
```

For a remote Ollama instance, set `STORYGEN_TEXT_BASE_URL=http://<host>:11434/v1`. The model string in `STORYGEN_TEXT_MODEL` must match the Ollama tag exactly (including the `:tag`).

**Verify:** `curl http://localhost:11434/api/tags` lists the model you configured.

## Image provider errors

### Capture a TUI image-generation failure

Start the TUI normally with `uv run storygen`. File diagnostics are enabled
automatically for the CLI session. Reproduce the character-creation failure
once, then exit the TUI and read the log from your shell:

```bash
tail -n 20 "${XDG_STATE_HOME:-$HOME/.local/state}/storygen/logs/tui.log"
```

The default path on Paul's MacDaddy is
`/Users/probello/.local/state/storygen/logs/tui.log`. An exported `XDG_STATE_HOME`
overrides the state directory. The log contains one JSON record per line, with
UTC timestamps, provider/model, portrait or scene operation, reference count,
exception types, traceback frames, and HTTP status/error code/parameter/request
ID where available. Primary and fallback failures are recorded separately.
Share the `image_generation_failed`, `character_creation` (failed/invalid
outcome), or `tui_exception` record from the failed attempt, including its
`exceptions` array when present. Character creation records dispatch, text
generation, portrait generation, saving, and refresh failures separately;
validation failures and skipped art also leave a record. A `tui_started` record
with `diagnostic_version: 2` confirms the expanded diagnostics are active after
restarting the TUI.

Exception messages, traceback source lines and locals, full prompts, names,
art styles, image data, provider response bodies, and authorization headers are
omitted. Unexpected metadata is redacted. Traceback frames contain only the
source filename, line number, and function. Files are private to the user and
rotate at 1 MiB, retaining three backups (`tui.log.1` through `tui.log.3`).

While the TUI runs, existing logging handlers are detached, raw application/SDK
messages are discarded. Existing exception reports are translated into safe
traceback metadata without copying their messages or arguments; `storygen`
debug-level exception reports are enabled for this capture. Only the sanitized
diagnostic channel writes to the file. Existing handlers and log levels are
restored when the TUI exits; the API server's
logging configuration is unchanged. File setup/write/rotation failures never
fall back to stdout or stderr. If the file is absent, check that the state
directory is writable. These diagnostics collect evidence; they do not resolve
the underlying image-provider failure.

### Symptom: Image generation returns `400` / `404` / `422`

**Likely causes:**

- **Wrong model name** — `STORYGEN_IMAGE_MODEL` (scene/cover) or `STORYGEN_CHARACTER_IMAGE_MODEL` (portraits) does not match a valid model id for the provider. OpenAI expects `gpt-image-2` / `gpt-image-1.5` / `gpt-image-1`; Z.AI expects `glm-image`; Gemini expects `gemini-3.1-flash-image-preview` / `gemini-3-pro-image-preview`.
- **Content policy (`400`)** — the prompt was rejected by the provider's safety filter. This is most common with Z.AI and Gemini on violent or adult-themed art styles. Re-run, soften the art style, or switch to OpenAI which is more permissive.
- **Missing image API key** — each provider needs its own key: `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `ZAI_API_KEY` (or the override `STORYGEN_IMAGE_API_KEY` / `STORYGEN_CHARACTER_IMAGE_API_KEY`).

**Fix:** Correct the model id or key in Settings or `.env`; for a content-policy rejection, retry with a tamer art style.

**Verify:** Regenerate the portrait/scene from the Portraits screen or the `r` regen picker; the image lands.

## Blank image panel

### Symptom: The scene/portrait area is empty or shows a placeholder, but generation reports success

**Likely causes:**

- **Art is disabled.** The global `art_enabled` toggle (Settings → "Enable image generation") is off. The pipeline then skips all image work.
- **Terminal does not support an inline-image protocol.** par-storygen renders half-block inline art via `par-textual-image`, which needs a terminal supporting the Kitty graphics protocol, iTerm2 inline images, or Sixel. Plain `vt100`/`xterm` without one of these shows nothing.
- **Graphics mode mismatch.** Settings → "Graphics mode" lets you force a protocol. If it is pinned to one your terminal does not support, images stay blank.

**Fix:** Turn `art_enabled` on in Settings. If the terminal is the issue, run a supporting terminal (Kitty, iTerm2, WezTerm, Ghostty) or set graphics mode to `halfblock` (works everywhere, lower fidelity).

**Verify:** Start a new story; the scene panel shows the generated illustration on the first beat.

## Text-to-speech produces no audio

### Symptom: TTS controls do nothing, or playback silently completes

**Likely causes:**

- **No TTS API key configured** for the selected provider. OpenAI/Gemini reuse their main keys; ElevenLabs and Deepgram need `ELEVENLABS_API_KEY` / `DEEPGRAM_API_KEY`. Kokoro is local and needs no key.
- **No voice selected.** Settings → Text-to-speech → press **Refresh voices** after picking a provider, then choose a voice.
- **Cache hit on a stale file.** Switching provider or voice should generate a fresh cache entry, but an orphaned partial file can cause a silent skip.

**Fix:** Enter the provider key, refresh voices, pick a voice. On macOS, `afplay` (used for playback) must be able to run — check that the process is not blocked.

**Verify:** Press `t` on the play screen; you hear narration within a few seconds.

## Web UI cannot reach the API

### Symptom: The browser frontend shows a connection error or never loads a game

**Likely causes:**

- **API server not running.** Start it with `make api-dev` (port `:8101`) alongside `make web-dev` (port `:8100`).
- **Port mismatch.** The frontend defaults to `http://localhost:8101`. Point it elsewhere by setting `NEXT_PUBLIC_API_BASE` at build time; both servers must stay on their configured ports.
- **CORS rejection.** The API's CORS allowlist (`STORYGEN_API_ALLOWED_ORIGINS`, default `http://localhost:8100,http://127.0.0.1:8100`) must include the frontend's origin. If you moved the frontend to another port, add its origin to the allowlist.
- **Auth rejected.** Auth is two-mode: when `STORYGEN_API_TOKEN` is unset, loopback peers are trusted and off-box clients get HTTP `503` / WebSocket close `4403`; when the token is set, every client (loopback included) must send it, and the frontend must be built with `NEXT_PUBLIC_API_TOKEN` set to the same value.

**Fix:**

```bash
make api-dev        # :8101
make web-dev        # :8100  (in a separate terminal)
```

For a non-default deploy, set `STORYGEN_API_ALLOWED_ORIGINS` / `STORYGEN_WS_ALLOWED_ORIGINS` on the server and `NEXT_PUBLIC_API_BASE` (and, if the token is set, `NEXT_PUBLIC_API_TOKEN`) on the frontend.

**Verify:** Open [http://localhost:8100](http://localhost:8100); the menu loads and you can start or resume a game. `curl http://localhost:8101/api/health` returns `{"status":"ok"}`.
