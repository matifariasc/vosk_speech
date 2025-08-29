# Deploy on Ubuntu (systemd)

This guide sets up two services:

- `vosk-api.service`: serves transcriptions over HTTP.
- `vosk-multiprocessor.service` + `vosk-multiprocessor.timer`: runs the
  multi-channel processor periodically (skips newest file and processes up to 50).
  Retention policy: keeps only the last 48 hours per channel.

## 1) Prerequisites

- Ubuntu 22.04+
- Packages: `sudo apt update && sudo apt install -y python3-venv ffmpeg`
- A media folder with per-channel subfolders containing files named like
  `<id>_YYYY-MM-DD_HH-MM-SS.mp4`

## 2) App install

```bash
sudo mkdir -p /opt/vosk_speech
sudo chown "$USER":"$USER" /opt/vosk_speech
cd /opt/vosk_speech
git clone <your-repo-url> .
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# Copy or download Vosk model into /opt/vosk_speech/vosk-model-es-0.42
```

Test locally:

```bash
python api_server.py 8000
python procesar_videos.py /path/to/media/Canal13
```

## 3) Configure systemd units

Install the unit files:

```bash
sudo cp deploy/vosk-api.service /etc/systemd/system/
sudo cp deploy/vosk-multiprocessor.service /etc/systemd/system/
sudo cp deploy/vosk-multiprocessor.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### API service

```bash
sudo systemctl enable --now vosk-api.service
sudo systemctl status vosk-api.service
```

## 4) Single service with JSON config (recommended)

To avoid many services, a single orchestrator reads a JSON config and
processes multiple channels in parallel.

1) Prepare config:

```bash
sudo mkdir -p /etc/vosk_speech
sudo cp channels.json.rename /etc/vosk_speech/channels.json
# Edit channels.json and set your channels and media_base
sudoedit /etc/vosk_speech/channels.json
```

2) Enable timer (runs every minute, processes channels in parallel threads):

```bash
sudo systemctl enable --now vosk-multiprocessor.timer
systemctl status vosk-multiprocessor.timer
```

3) Logs:

```bash
journalctl -u vosk-multiprocessor.service -f
```

Notes:
- Concurrency is controlled by `parallel` in the JSON (default 4).
- The per-channel outputs remain `transcripciones_<canal>.json` in the app directory.
- The API server merges all `transcripciones_*.json` files in its working directory.
