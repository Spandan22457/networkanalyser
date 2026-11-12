# Mini Network Analyzer (NetScope)

A local, Windows-first network monitoring dashboard built with FastAPI, Scapy/Npcap,
SQLite, and a vanilla JavaScript frontend.

It is intended only for **authorized monitoring of networks and devices you own or administer**.

## Run the app

```powershell
# from the project root
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Then open **http://127.0.0.1:8000/** in your browser.

The FastAPI backend now serves the dashboard itself, so the page, the REST API and the
WebSocket all share one origin:

| URL | Purpose |
|---|---|
| `http://127.0.0.1:8000/` | Dashboard |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/api/packets` | Packet history JSON |
| `ws://127.0.0.1:8000/ws/live` | Live statistics |

## Do not open the page through Live Server

Earlier versions opened `frontend/index.html` through VS Code Live Server (port 5500).
Live Server watches the whole project folder, and packet capture writes to
`network_monitor.db` continuously. Every database write was treated as a file change,
so Live Server reloaded the page again and again - the dashboard appeared to flicker
and reload in a loop.

Two fixes are included in this repository:

1. **The backend serves the frontend** (`app.mount("/", StaticFiles(...))` in
   `api/main.py`), so no file-watching dev server is needed. Open port 8000.
2. **Live Server ignores database files** (`.vscode/settings.json`), so even if you
   still start Live Server, SQLite writes no longer trigger reloads.

The packet table is also updated in place instead of being rebuilt from scratch every
few seconds, which removes the remaining visual blink.

## Install dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install fastapi uvicorn[standard] sqlalchemy scapy psutil pydantic
```

Packet capture needs [Npcap](https://npcap.com/#download) installed with the default
"WinPcap API-compatible mode" option.

## API overview

| Method | Path | Description |
|---|---|---|
| GET | `/api` | API status |
| GET | `/api/health` | Health check |
| GET | `/api/interfaces` | Network interfaces |
| GET | `/api/gateway` | Default gateway and local subnet |
| GET | `/api/devices` | Discover devices on the LAN |
| POST | `/api/capture/start` | Start capturing on an interface |
| POST | `/api/capture/stop` | Stop the current capture |
| GET | `/api/capture/status` | Capture status |
| GET | `/api/statistics` | Live statistics snapshot |
| GET | `/api/packets` | Stored packet metadata |
| WS | `/ws/live` | Live statistics push (1 per second) |

## Security

- The server binds to `127.0.0.1` only.
- Packet payloads are not stored; only connection metadata is saved.
- Use this software only on networks you own or are explicitly authorized to monitor.
