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

Two backends are supported and both are configured in one place,
`monitor/core/config.py`:

| Backend | How to select it | Notes |
|---|---|---|
| SQLite (default) | nothing to do | one file at an absolute path, no server |
| PostgreSQL | set `NETSCOPE_DATABASE_URL` | needs the `psycopg` driver and a one-time role/database |

Every process and every Alembic command resolves the same URL, so the working
directory never changes which database is used. For SQLite the file location can be
overridden with `NETSCOPE_DATABASE_PATH` (or a `.env` file).

```powershell
# Apply schema changes to the configured database
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

### External database (PostgreSQL)

SQLite is the default and needs no setup. To store everything in PostgreSQL instead,
set one variable - `NETSCOPE_DATABASE_URL` - and the engine, sessions, repositories
and Alembic all switch over. There is no code path that still assumes SQLite.

**1. Create a role and database once** (run as the `postgres` superuser):

```powershell
$psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
& $psql -U postgres -h 127.0.0.1 -c "CREATE ROLE netscope LOGIN PASSWORD 'choose-a-password';"
& $psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE netscope OWNER netscope;"
```

**2. Point the app at it** - create `.env` in the project root (it is git-ignored):

```ini
NETSCOPE_DATABASE_URL=postgresql+psycopg://netscope:choose-a-password@127.0.0.1:5432/netscope
```

`postgres://` and `postgresql://` are accepted too; they are rewritten to the
installed `psycopg` driver. A plain path or a URL without a scheme is rejected at
startup rather than failing later.

**3. Create the tables:**

```powershell
python -m alembic upgrade head
python -m alembic check
```

**4. Start the app as usual** and confirm the backend:

```powershell
python run.py
# http://127.0.0.1:8000/api/health  ->  {"backend":"postgresql", ...}
```

`/api` and `/api/health` report which backend is in use, and `settings.safe_database_url`
masks the password when the URL is displayed.

Notes:

- The SQLite file is *not* migrated automatically. A new PostgreSQL database starts
  empty; keep `network_monitor.db` as an archive or copy rows across with a one-off
  script if you need the history.
- Connection pooling is configured by `NETSCOPE_DB_POOL_SIZE` (5),
  `NETSCOPE_DB_MAX_OVERFLOW` (5) and `NETSCOPE_DB_POOL_RECYCLE` (1800 s).
- Flow upserts use `INSERT ... ON CONFLICT DO UPDATE` on both backends; only the
  dialect-specific insert constructor and `least()`/`greatest()` differ.
- `.env` is read from the project root, so the command must run from there.
- Tests always use SQLite: `tests/conftest.py` clears `NETSCOPE_DATABASE_URL`, so a
  configured server is never touched by `python -m pytest`.

## Capture and persistence pipeline

```
Scapy sniff
  -> packet processor (metadata only)
  -> in-memory statistics engine
  -> bounded queue
  -> database writer thread (batches + connection upserts)
  -> SQLite (default) or PostgreSQL
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

97 tests cover the schema, all three repositories, flow aggregation, the writer /
retry / dead-letter path, the statistics read model, every REST endpoint, and the
WebSocket contract. `tests/conftest.py` redirects `NETSCOPE_DATABASE_PATH` to a
throwaway directory and clears `NETSCOPE_DATABASE_URL` before importing project
modules, so neither the real `network_monitor.db` nor a configured PostgreSQL server
is ever touched. Only synthetic packets are used.

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
- **`password authentication failed for user "netscope"`.** The password in
  `.env` does not match the role. Reset it with
  `ALTER ROLE netscope PASSWORD 'new-password';` as the `postgres` superuser.
- **`connection refused` on port 5432.** Check the service:
  `Get-Service postgresql*`, then `Start-Service postgresql-x64-18`.
- **`relation "packets" does not exist`.** The server database was never migrated:
  run `python -m alembic upgrade head`.
- **Data "disappeared" after switching backend.** The SQLite file and PostgreSQL are
  separate stores; switching backends shows whichever one is configured. Set or
  remove `NETSCOPE_DATABASE_URL` in `.env` and restart.

## Security

- The server binds to `127.0.0.1` only.
- Packet payloads are not stored; only connection metadata is saved.
- Use this software only on networks you own or are explicitly authorized to monitor.
