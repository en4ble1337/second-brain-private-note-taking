# Second Brain

A local voice note appliance. Press your phone's Action Button, speak, get a cleaned-up note at `http://mybrain.local`. Runs entirely on your own hardware — no cloud, no subscriptions, no data leaving your network.

Designed to run on any Linux machine: a VM, a home server, a mini PC, or a single-board computer like a Raspberry Pi.

---

## How It Works

```
Phone (iOS Shortcut / Android Tasker)
  └─► POST /api/ingest  (audio + Bearer token)
        └─► Job queued → 202 returned immediately

Background worker
  └─► Transcribe  →  faster-whisper (on-device)
  └─► Clean       →  Ollama llama3.2:3b (on-device)
  └─► Store       →  SQLite + FTS5 full-text index

Browser → http://mybrain.local
  └─► Inbox, search, note detail, setup wizard
```

---

## Requirements

**Hardware**
- Any machine capable of running Ubuntu/Debian Linux (VM, mini PC, home server, SBC)
- 4 GB RAM minimum recommended (for Whisper + Ollama running concurrently)
- 20 GB+ free disk space

**Software**
- Ubuntu 24.04 / Debian Bookworm (or any Debian-based distro)
- Python 3.11+
- [Ollama](https://ollama.com/install) — install with:
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```

> **Tested on:** Ubuntu 24.04 VM and Raspberry Pi OS 64-bit (Bookworm). Any Debian-based system with Python 3.11+ should work.

---

## Deployment

### 1. Clone the repo

Clone to whatever directory suits your setup:

```bash
# Example paths — use whatever works for your environment
git clone <repo-url> ~/brain          # home directory
git clone <repo-url> /opt/brain       # system-wide
git clone <repo-url> /home/myuser/brain
cd <clone-path>
```

### 2. Run the install script

```bash
sudo bash deployment/install.sh
```

Run this from inside the cloned directory. It detects the current user and install path automatically.

This will:
- Install system dependencies (`python3-venv`, `authbind`, `avahi-daemon`)
- Set the hostname to `mybrain`
- Create a Python virtualenv and install Python dependencies
- Generate a `.env` file with a random `INGEST_TOKEN` and `SECRET_KEY`
- Configure Ollama to bind localhost-only
- Pull the `llama3.2:3b` model (takes a few minutes on first run)
- Register and start `brain.service` via systemd
- Advertise `mybrain.local` on the LAN via avahi mDNS

### 3. Check services are running

```bash
systemctl status brain  --no-pager
systemctl status ollama --no-pager
```

Both should show `active (running)`.

### 4. Open the setup wizard

From any device on the same network:

```
http://mybrain.local/setup
```

The wizard shows your ingest URL, masked token, and step-by-step iOS Shortcut / Android Tasker configuration.

### 5. Get your token (for the Shortcut)

```bash
grep INGEST_TOKEN .env
```

### 6. Run the smoke test

From a machine with Python and `httpx` installed:

```bash
pip install httpx
python execution/smoke_test.py --host http://mybrain.local --token <your-token>
```

Expected: all 7 checks pass, performance metrics printed against PRD targets.

---

## Configuration

All config is in `.env` at the project root. Generated automatically by the install script; edit to override defaults.

| Variable | Default | Description |
|---|---|---|
| `INGEST_TOKEN` | *(required)* | Bearer token for POST /api/ingest |
| `SECRET_KEY` | *(required)* | App secret key |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API address |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model used for transcript cleanup |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Timeout for LLM calls |
| `WHISPER_MODEL` | `base` | faster-whisper model size (`tiny`, `base`, `small`, `medium`) |
| `DATA_DIR` | `./data` | Directory for audio files and SQLite DB |
| `MAX_AUDIO_SIZE_MB` | `500` | Maximum accepted audio file size |
| `WORKER_POLL_INTERVAL` | `2` | Seconds between background worker polls |
| `HOST` | `0.0.0.0` | Bind address for the HTTP server |
| `PORT` | `80` | HTTP port (authbind allows non-root on port 80) |

**Whisper model trade-offs:**

| Model | RAM | Speed | Accuracy |
|---|---|---|---|
| `tiny` | ~400 MB | fastest | lower |
| `base` | ~550 MB | fast | good |
| `small` | ~1 GB | moderate | better |
| `medium` | ~3 GB | slow | best |

On a VM or modern mini PC, `small` or `medium` are viable. On lower-powered hardware (e.g., SBC), `base` or `tiny` are safer choices.

---

## Remote Access

By default the appliance is LAN-only. If you want to capture notes away from home:

- **Tailscale** (recommended) — free account, peer-to-peer encrypted tunnel, no audio passes through third-party servers. Install on both the appliance and your phone, update the Shortcut URL to the Tailscale IP.
- **WireGuard** — fully self-hosted VPN, no account required, more setup.
- **Cloudflare Tunnel** — no port forwarding needed, but audio passes through Cloudflare's network.

Full instructions for each option are in the setup wizard at `http://mybrain.local/setup`.

> **Do not** port-forward this service directly to the internet.

---

## Development Setup

### Prerequisites

- Python 3.11+
- No Ollama or Whisper needed for running tests (both are mocked)

### Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Environment

Create a `.env` file:

```bash
INGEST_TOKEN=dev-token
SECRET_KEY=dev-secret
DATA_DIR=./data
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:3b
WHISPER_MODEL=base
```

### Run tests

```bash
pytest
```

### Run locally

```bash
source .venv/bin/activate
uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open `http://localhost:8000`.

---

## Project Structure

```
src/
  core/        Config, database, auth, error helpers
  models/      SQLAlchemy ORM — Job, Note
  schemas/     Pydantic I/O shapes
  services/    Transcription, LLM cleanup, note CRUD, pipeline
  api/         Ingest, notes JSON API, audio file serving
  web/         Jinja2 templates, static CSS, web routes
  worker/      Background polling loop
deployment/    systemd unit, avahi mDNS, install script
execution/     End-to-end smoke test
tests/         Full test suite (mirrors src/)
docs/          PRD, ARCH, RESEARCH, deployment checklist
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `mybrain.local` doesn't resolve | `sudo systemctl restart avahi-daemon` |
| HTTP 403 on port 80 | `ls -la /etc/authbind/byport/80` — must be owned by your user with mode `500` |
| `brain.service` fails to start | `journalctl -u brain -n 50` — check for Python import errors or missing `.env` |
| Ollama model missing | `ollama pull llama3.2:3b` |
| Notes stuck in `transcribing` | `journalctl -u brain -f` — check for faster-whisper errors or low disk space |
| Disk full | `df -h <install-path>/data` — delete old audio files in `data/raw/` |

See `docs/plans/deployment-checklist.md` for the full step-by-step validation guide.

---

## Privacy

- All audio processing (Whisper STT, Ollama LLM) runs on-device.
- Ollama is bound to `127.0.0.1` — not accessible from the LAN.
- Audio files and raw transcripts are retained permanently in `data/raw/` as a fallback.
- No analytics, no telemetry, no external API calls during normal operation.

To verify during a processing cycle:

```bash
sudo tcpdump -i eth0 -n 'not (arp or port 5353 or port 80 or port 443 or port 22)' -c 20 -t
# Expected: no output
```
