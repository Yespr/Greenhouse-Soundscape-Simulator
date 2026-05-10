# Greenhouse Soundscape Simulator

Local FastAPI app for configuring and running greenhouse ambient soundscapes on a Raspberry Pi.

This is a clean v1 skeleton. It stores sound configuration in SQLite, serves a basic local web UI, and exposes realistic audio-engine interfaces without changing system audio settings.

## Features

- List, create, update, and delete sound entries.
- Configure name, file path, enabled state, profile, type, volume, intervals, probability, fades, and repeat bursts.
- Engine modes: `off`, `day`, `evening`, `auto`.
- Start/stop API and web controls.
- Real-time audio engine using `sounddevice`, `soundfile`, and `numpy`.
- MQTT/Home Assistant integration boundary prepared in `app/mqtt_client.py`.

## Project Layout

```text
app/
  main.py
  models.py
  database.py
  audio_engine.py
  scheduler.py
  mqtt_client.py
web/
  index.html
  app.js
  style.css
sounds/
data/
README.md
requirements.txt
```

## Raspberry Pi Setup

Use Raspberry Pi OS with Python 3 installed.

```bash
sudo apt update
sudo apt install -y python3 python3-venv portaudio19-dev libsndfile1

cd greenhouse-soundscape
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Put audio files under `sounds/`, then start the app:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open the GUI from another device on the same network:

```text
http://<raspberry-pi-ip>:8000
```

SQLite data is stored at:

```text
data/soundscape.sqlite3
```

## API

- `GET /api/health`
- `GET /api/sounds`
- `POST /api/sounds`
- `POST /api/sounds/upload`
- `PUT /api/sounds/{sound_id}`
- `DELETE /api/sounds/{sound_id}`
- `GET /api/engine`
- `POST /api/engine/start`
- `POST /api/engine/stop`
- `POST /api/engine/mode`

Example sound payload:

```json
{
  "name": "Birds",
  "file_path": "sounds/birds.wav",
  "enabled": true,
  "profile": "day",
  "type": "loop",
  "volume": 70,
  "min_interval_seconds": 30,
  "max_interval_seconds": 120,
  "probability": 100,
  "fade_in_seconds": 0.0,
  "fade_out_seconds": 0.0,
  "repeat_count_min": 1,
  "repeat_count_max": 1,
  "repeat_gap_seconds": 1.0
}
```

`POST /api/sounds/upload` accepts `multipart/form-data` with a `file` field plus the same sound settings. Uploaded files are saved under `sounds/`. Only `.mp3`, `.wav`, and `.ogg` files are accepted.

## Audio Engine Notes

`app/audio_engine.py` uses a streaming `sounddevice` backend. Audio files are decoded with `soundfile`, mixed in real time with `numpy`, clamped to `-1.0` to `+1.0`, and sent to the local audio device. Loop sounds and one-shot/random sounds can play together.

- `volume` and `probability` use `0` to `100` percentage values.

Changing a sound and saving it updates playback without regenerating uploaded files. Running loop sounds are restarted by the scheduler refresh so new settings take effect.

## Home Assistant / MQTT Notes

MQTT is intentionally not implemented in v1. `app/mqtt_client.py` is the boundary for later state publishing and Home Assistant integration.
