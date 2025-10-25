# Vosk Speech Transcription Tools

This repository contains utilities for processing videos with Vosk and serving
transcriptions through a small HTTP API. Each transcription block now includes
the keys `inicio`, `fin`, `fecha`, `texto` and `medio`.

## Usage

1. Generate transcriptions using `procesar_videos.py`.
   - Processing prioritizes the most recent items while avoiding in-progress files:
     it skips the newest file and processes from the second newest backwards.
   - Up to 50 files are considered per run, walking backwards in time.
   - Already processed files are skipped automatically.
   - Retention: only the last 48 hours are kept per channel; older entries are
     cleaned automatically when new items are processed.
2. Start the API server:
   ```bash
   python api_server.py 8000
   ```
3. Query the API. You can filter results by `fecha` (date), `medio` (media
   folder name) and `hours` (time window, default 48). Each transcription block
   records the `medio` it belongs to. The server returns clear error messages when no
   `transcripciones_*.json` files are found or a video has no transcription.
   Example:
   ```
   http://localhost:8000/?fecha=2025-07-22&medio=Canal13
   ```
   This request returns all transcripts recorded on `2025-07-22` inside the
   `Canal13` folder.
   API help: `http://localhost:8000/docs`

## Vosk model path

By default the scripts look for the model inside `vosk-model-es-0.42/` relative
to the project root. If your model lives elsewhere, set the environment
variables in `.env`:

- `DEV=true` together with `DEV_VOSK_MODEL_PATH=/abs/path/...` to point to a
  local model only when running in development.
- `VOSK_MODEL_PATH=/abs/path/...` to override the model location regardless of
  the `DEV` flag.

## CUOS API integration

Set the environment variable `CUOS_ENDPOINT` in your `.env` file when you want
to forward newly generated transcription blocks to the CUOS API. Mark the desired
channels in `channels.json` using objects with a truthy `send_to_api` field:

```json
{
  "media_base": "/srv/media",
  "channels": [
    "Canal13",
    { "name": "tvn", "send_to_api": true }
  ],
  "parallel": 2
}
```

Only channels flagged with `send_to_api` will post each new transcription entry,
using a 5 second request timeout per payload.
