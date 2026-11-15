# Mini Network Analyzer (NetScope)

A local, Windows-first network monitoring dashboard built with FastAPI, Scapy/Npcap,
SQLite, and a vanilla JavaScript frontend.

It is intended only for **authorized monitoring of networks and devices you own or administer**.
Only packet metadata is stored; payloads are never saved.

## Run the app

```powershell
# from the project root
python run.py
```

Then open **http://127.0.0.1:8000/** in your browser.

`run.py` is a small wrapper around uvicorn. On Windows it selects the selector event
loop because uvicorn 0.54 otherwise forces the Proactor loop, which can lose its
listening socket when a browser aborts a connection during accept
(`OSError: [WinError 64] The specified network name is no longer available`). The
process would stay alive but stop answering requests. The selector loop retries the
accept instead of tearing the listener down.

A plain uvicorn start still works, but is not recommended on Windows:

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The backend serves the dashboard itself, so the page, the REST API and the WebSocket
share one origin:

| URL | Purpose |
|---|---|
| `http://127.0.0.1:8000/` | Dashboard |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/api/packets` | Packet history JSON |
| `ws://127.0.0.1:8000/ws/live` | Live statistics |

### Dashboard pages

| Page | Contents |
|---|---|
| Overview | Totals, live throughput, protocol mix, top talkers, storage pipeline, recent packets |
| Traffic | Upload/download rates, directional totals, top talkers |
| Packet Explorer | Server-side search, filters, sorting and pagination |
| Connections | Flows aggregated per 5-tuple, with state and counters |
| Protocols | Transport and application protocol distribution with share |
| Interfaces | Adapters, default gateway, LAN device scan |
| History | Persisted statistics snapshots and a trend chart |

Every page has loading, empty and error states. Chart.js instances are created once and
updated in place, so charts never flicker or leak.

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

`frontend/js/config.js` detects a dev-server port (5500/5173) and points the API at
`http://127.0.0.1:8000`; otherwise it uses the same origin. Opening the file directly
shows a warning banner instead of silently failing.

## Install dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Packet capture needs [Npcap](https://npcap.com/#download) installed with the default
"WinPcap API-compatible mode" option.

## Database and migrations

The SQLite file location is resolved once, from an absolute path, in
`monitor/core/config.py`. Override it with the `NETSCOPE_DATABASE_PATH` environment
variable (or a `.env` file); every process and every Alembic command then uses the
same file regardless of the current working directory.

```powershell
# Apply schema changes to an existing database
python -m alembic upgrade head

# Confirm the models and the database agree
python -m alembic check
```

Existing databases created before migrations were introduced must be marked as
already containing the baseline table, then upgraded:

```powershell
python -m alembic stamp 0001_baseline
python -m alembic upgrade head
```

Tables: `packets` (metadata only, no payloads), `network_statistics` (periodic
snapshots), `connections` (tracked 5-tuples). The migration adds columns with
`ADD COLUMN` and never rewrites existing packet rows. `init_database()` also applies
the same additive column changes at startup, so a stale database remains usable
without migrations; Alembic is still the versioned path.

## Capture and persistence pipeline

```
Scapy sniff
  -> packet processor (metadata only)
  -> in-memory statistics engine
  -> bounded queue
  -> database writer thread (batches + connection upserts)
  -> SQLite
```

Two background threads run beside the capture thread: one drains the queue in bounded
batches, the other writes a statistics snapshot every 10 seconds and once more on
shutdown. The capture callback never touches the database, so a slow disk cannot stall
packet capture.

Counters reported by `/api/capture/status` and the dashboard:

| Counter | Meaning |
|---|---|
| `captured_packets` | Frames Scapy handed to the callback |
| `processed_packets` | Packets parsed into metadata |
| `queued_packets` | Packets waiting for the writer |
| `stored_packets` | Rows committed to SQLite this session |
| `storage_dropped_packets` | Queue was full; packet was counted, not silently lost |
| `storage_failed_packets` | Batch failed twice and was dead-lettered |

A failed batch is retried once. If it fails again it is appended to
`storage_failures.jsonl` as JSON, counted, and reported - it is never silently
discarded.

## API overview

| Method | Path | Description |
|---|---|---|
| GET | `/api` | API status |
| GET | `/api/health` | Health check (database connectivity + row count) |
| GET | `/api/interfaces` | Network interfaces |
| GET | `/api/gateway` | Default gateway, local subnet and friendly capture name |
| GET | `/api/devices` | Discover devices on the LAN |
| POST | `/api/capture/start` | Start capturing on an interface |
| POST | `/api/capture/stop` | Stop the current capture and flush |
| GET | `/api/capture/status` | Capture, queue and storage counters |
| GET | `/api/statistics/current` | Live snapshot, or database totals when stopped |
| GET | `/api/statistics/history` | Persisted snapshots (`limit`, `since`, `until`) |
| GET | `/api/statistics/protocols` | Transport + application distribution |
| GET | `/api/top-talkers` | Hosts by bytes sent (`limit`) |
| GET | `/api/packets` | Paginated packets (`limit`, `offset`, `protocol`, `application_protocol`, `direction`, `interface`, `search`, `min_packet_size`, `max_packet_size`, `sort`, `order`) |
| GET | `/api/packets/{id}` | One packet |
| GET | `/api/connections` | Paginated flows (`limit`, `offset`, `protocol`, `state`, `search`, `sort`, `order`) |
| WS | `/ws/live` | Live statistics push (once per second) |

`/api/statistics` remains as an alias of `/api/statistics/current`.

Statistics responses include `source`: `live` while capturing, `database` when totals
come from stored packets, `empty` on a fresh install. The frontend never invents
numbers when a request fails; it shows an error state instead.

The WebSocket pushes one central snapshot to every connected client. A page reload or
disconnect never stops capture, and database aggregates are cached for a few seconds so
the 1 Hz fan-out does not become a full table scan per client.

## Tests

```powershell
python -m pytest
```

86 tests cover the schema, all three repositories, flow aggregation, the writer /
retry / dead-letter path, the statistics read model, every REST endpoint, and the
WebSocket contract. `tests/conftest.py` redirects `NETSCOPE_DATABASE_PATH` to a
throwaway directory before importing project modules, so the real
`network_monitor.db` is never touched. Only synthetic packets are used.

## Troubleshooting

- **The page shows `--` and the browser console has no `/api` requests.**
  Start the backend and open `http://127.0.0.1:8000/`. Chart.js is bundled in
  `frontend/vendor/chart.umd.min.js`, so a blocked CDN can no longer stop the
  API calls from running.
- **The sidebar says "Reconnecting…".** The backend is not running, or the page is
  open on a different port (for example an old Live Server tab). The dashboard falls
  back to HTTP polling and labels itself "Connected (polling)".
- **`OSError: [WinError 64]` and later requests fail.** Start with `python run.py`
  instead of plain uvicorn (see "Run the app").
- **`database is locked`.** Close other tools holding `network_monitor.db`. WAL mode
  and a 5 second busy timeout are configured, so short overlaps are tolerated.

## Security

- The server binds to `127.0.0.1` only.
- Packet payloads are not stored; only connection metadata is saved.
- Use this software only on networks you own or are explicitly authorized to monitor.
