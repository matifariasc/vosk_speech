# Vosk Speech Transcription Tools

This repository contains utilities for processing videos with Vosk and serving
transcriptions through a small HTTP API. Each transcription block now includes
the keys `inicio`, `fin`, `fecha`, `texto` and `medio`.

## Usage

1. Generate transcriptions using `procesar_videos.py`.
2. Start the API server:
   ```bash
   python api_server.py 8000
   ```
3. Query the API. You can filter results by `fecha` (date) and `medio` (media
   folder name). Each transcription block also records the `medio` it belongs
   to. The server now returns clear error messages when
   `transcripciones.json` is missing or a video has no transcription.
   Example:
   ```
   http://localhost:8000/?fecha=2025-07-22&medio=Canal13
   ```
   This request returns all transcripts recorded on `2025-07-22` inside the
   `Canal13` folder.

