"""
FastAPI application.

Layer boundaries:

* routes only validate input, call a repository/service and shape a response;
* SQL lives in ``monitor/storage/*_repository.py``;
* statistics merging lives in ``monitor/statistics/statistics_service.py``;
* capture orchestration lives in ``monitor/capture/capture_manager.py``.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.schemas import (
    CaptureStatusOut,
    ConnectionPage,
    ConnectionOut,
    HealthOut,
    NetworkStatisticsOut,
    PacketOut,
    PacketPage,
    ProtocolStatistics,
    StartCaptureRequest,
    StatisticsResponse,
    TopTalker,
)
from monitor.capture.capture_manager import CaptureManager
from monitor.core.timeutils import from_iso, utcnow
from monitor.discovery.device_discovery import DeviceDiscovery
from monitor.discovery.gateway_discovery import GatewayDiscovery
from monitor.discovery.interface_discovery import InterfaceDiscovery
from monitor.statistics.statistics_service import statistics_service
from monitor.storage.connection_repository import ConnectionRepository
from monitor.storage.database import engine, get_db, init_database
from monitor.storage.packet_repository import PacketRepository, SORT_COLUMNS


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

PACKET_SORT_FIELDS = set(SORT_COLUMNS)
CONNECTION_SORT_FIELDS = {
    "id",
    "first_seen",
    "last_seen",
    "packet_count",
    "byte_count",
}


# Shared capture manager and the lock that serialises start/stop.
capture_manager: CaptureManager | None = None
capture_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_database()

    yield

    with capture_lock:
        if capture_manager is not None:
            capture_manager.stop()


app = FastAPI(
    title="Mini Network Analyzer API",
    description="Real-time network traffic monitoring backend",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SQLAlchemyError)
async def _database_error_handler(_request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Database error: {exc}"},
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _parse_timestamp(value: str | None, label: str) -> datetime | None:
    if value is None or value == "":
        return None

    try:
        return from_iso(value)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} timestamp: {value}",
        ) from exc


def _resolve_interface(value: str) -> dict[str, Any] | None:
    """Accept a capture name, a friendly name, or the NPF device path."""

    interfaces = InterfaceDiscovery().discover()

    for interface in interfaces:
        if value in (interface["capture_name"], interface["name"]):
            return interface

    if value.startswith("\\Device\\NPF") or value.startswith("\\Device"):
        gateway = GatewayDiscovery().discover()
        local_ip = gateway.get("local_ip")

        if local_ip:
            for interface in interfaces:
                if local_ip in interface["ipv4_addresses"]:
                    return interface

    return None


def _capture_status(manager: CaptureManager) -> CaptureStatusOut:
    return CaptureStatusOut(**manager.status())


def _live_payload() -> dict[str, Any]:
    manager = capture_manager
    statistics = statistics_service.current(manager)

    if manager is not None:
        status = manager.status()

        counters = {
            "running": status["running"],
            "interface": status["interface"],
            "captured_packets": status["captured_packets"],
            "processed_packets": status["processed_packets"],
            "stored_packets": status["stored_packets"],
            "queued_packets": status["queued_packets"],
            "storage_dropped_packets": status["storage_dropped_packets"],
            "storage_failed_packets": status["storage_failed_packets"],
            "error": status["error"],
        }

    else:
        counters = {
            "running": False,
            "interface": None,
            "captured_packets": 0,
            "processed_packets": 0,
            "stored_packets": 0,
            "queued_packets": 0,
            "storage_dropped_packets": 0,
            "storage_failed_packets": 0,
            "error": None,
        }

    return {
        "type": "live",
        "timestamp": utcnow().isoformat(),
        **counters,
        "total_packets": statistics["total_packets"],
        "total_bytes": statistics["total_bytes"],
        "average_packet_size": statistics["average_packet_size"],
        "upload_bytes": statistics["upload_bytes"],
        "download_bytes": statistics["download_bytes"],
        "upload_speed": statistics["upload_bytes_per_second"],
        "download_speed": statistics["download_bytes_per_second"],
        "upload_bytes_per_second": statistics["upload_bytes_per_second"],
        "download_bytes_per_second": statistics[
            "download_bytes_per_second"
        ],
        "bytes_per_second": statistics["bytes_per_second"],
        "packets_per_second": statistics["packets_per_second"],
        "protocol_counts": statistics["protocol_counts"],
        "application_protocol_counts": statistics[
            "application_protocol_counts"
        ],
        "direction_counts": statistics["direction_counts"],
        "unique_source_ips": statistics["unique_source_ips"],
        "unique_destination_ips": statistics["unique_destination_ips"],
        "top_talkers": statistics.get("top_talkers", []),
        "source": statistics.get("source", "empty"),
    }


# ----------------------------------------------------------------------
# Service info
# ----------------------------------------------------------------------


@app.get("/api")
def api_root():
    return {
        "message": "Mini Network Analyzer API is running",
        "docs": "/docs",
        "version": "2.0.0",
    }


@app.get("/api/health", response_model=HealthOut)
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            stored = connection.execute(
                text("SELECT COUNT(*) FROM packets")
            ).scalar_one()

    except Exception as exc:
        return HealthOut(
            status="degraded",
            database="unavailable",
            detail=str(exc),
        )

    return HealthOut(
        status="healthy",
        database="connected",
        detail=f"{int(stored)} packets stored",
    )


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


@app.get("/api/interfaces")
def get_interfaces():
    interfaces = InterfaceDiscovery().discover()

    return {"count": len(interfaces), "interfaces": interfaces}


@app.get("/api/gateway")
def get_gateway():
    result = GatewayDiscovery().discover()

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    # The route reports the NPF device path; expose the friendly capture name
    # the UI uses for POST /api/capture/start.
    capture_name = None
    local_ip = result.get("local_ip")

    if local_ip:
        for interface in InterfaceDiscovery().discover():
            if local_ip in interface["ipv4_addresses"]:
                capture_name = interface["capture_name"]
                break

    result["capture_name"] = capture_name or result.get("interface")

    return result


@app.get("/api/devices")
def get_devices(interface: str | None = None):
    result = DeviceDiscovery().discover(interface=interface)

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    return result


# ----------------------------------------------------------------------
# Capture control
# ----------------------------------------------------------------------


@app.post("/api/capture/start", response_model=CaptureStatusOut)
def start_capture(request: StartCaptureRequest):
    global capture_manager

    selected = _resolve_interface(request.interface)

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail="Selected network interface was not found.",
        )

    if selected["is_up"] is False:
        raise HTTPException(
            status_code=400,
            detail="Selected network interface is down.",
        )

    with capture_lock:
        if capture_manager is not None and capture_manager.is_running():
            raise HTTPException(
                status_code=409,
                detail="A capture session is already running.",
            )

        manager = CaptureManager(interface=selected["capture_name"])

        if not manager.start():
            status = manager.status()
            raise HTTPException(
                status_code=500,
                detail=(
                    status.get("error")
                    or "Could not start packet capture."
                ),
            )

        capture_manager = manager

    return _capture_status(capture_manager)


@app.post("/api/capture/stop", response_model=CaptureStatusOut)
def stop_capture():
    with capture_lock:
        manager = capture_manager

        if manager is None:
            return CaptureStatusOut(running=False)

        if not manager.stop():
            raise HTTPException(
                status_code=500,
                detail=(
                    manager.status().get("error")
                    or "Capture did not stop cleanly."
                ),
            )

        return _capture_status(manager)


@app.get("/api/capture/status", response_model=CaptureStatusOut)
def get_capture_status():
    manager = capture_manager

    if manager is None:
        return CaptureStatusOut(running=False)

    return _capture_status(manager)


# ----------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------


@app.get(
    "/api/statistics",
    response_model=StatisticsResponse,
    include_in_schema=False,
)
@app.get("/api/statistics/current", response_model=StatisticsResponse)
def get_current_statistics():
    return statistics_service.current(capture_manager)


@app.get(
    "/api/statistics/history",
    response_model=list[NetworkStatisticsOut],
)
def get_statistics_history(
    limit: int = Query(default=100, ge=1, le=5000),
    since: str | None = None,
    until: str | None = None,
):
    return statistics_service.history(
        limit=limit,
        since=_parse_timestamp(since, "since"),
        until=_parse_timestamp(until, "until"),
    )


@app.get(
    "/api/statistics/protocols",
    response_model=ProtocolStatistics,
)
def get_protocol_statistics():
    return statistics_service.protocols()


@app.get("/api/top-talkers", response_model=list[TopTalker])
def get_top_talkers(limit: int = Query(default=10, ge=1, le=100)):
    return statistics_service.top_talkers(limit)


# ----------------------------------------------------------------------
# Packets
# ----------------------------------------------------------------------


@app.get("/api/packets", response_model=PacketPage)
def get_packets(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    protocol: str | None = None,
    application_protocol: str | None = None,
    direction: str | None = None,
    interface: str | None = None,
    search: str | None = None,
    min_packet_size: int | None = Query(default=None, ge=0),
    max_packet_size: int | None = Query(default=None, ge=0),
    sort: str = Query(default="id"),
    order: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    if sort not in PACKET_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid sort field '{sort}'. "
                f"Allowed: {', '.join(sorted(PACKET_SORT_FIELDS))}"
            ),
        )

    if order.lower() not in {"asc", "desc"}:
        raise HTTPException(
            status_code=400, detail="order must be 'asc' or 'desc'."
        )

    total, records = PacketRepository(db).get_packets(
        limit=limit,
        offset=offset,
        sort_by=sort,
        descending=order.lower() == "desc",
        protocol=protocol,
        application_protocol=application_protocol,
        direction=direction,
        interface=interface,
        search=search,
        min_packet_size=min_packet_size,
        max_packet_size=max_packet_size,
    )

    return PacketPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[PacketOut.model_validate(record) for record in records],
    )


@app.get("/api/packets/{packet_id}", response_model=PacketOut)
def get_packet(packet_id: int, db: Session = Depends(get_db)):
    record = PacketRepository(db).get_by_id(packet_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Packet not found.")

    return PacketOut.model_validate(record)


# ----------------------------------------------------------------------
# Connections
# ----------------------------------------------------------------------


@app.get("/api/connections", response_model=ConnectionPage)
def get_connections(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    protocol: str | None = None,
    state: str | None = None,
    search: str | None = None,
    sort: str = Query(default="last_seen"),
    order: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    if sort not in CONNECTION_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid sort field '{sort}'. "
                f"Allowed: {', '.join(sorted(CONNECTION_SORT_FIELDS))}"
            ),
        )

    total, records = ConnectionRepository(db).get_connections(
        limit=limit,
        offset=offset,
        protocol=protocol,
        state=state,
        search=search,
        sort_by=sort,
        descending=order.lower() != "asc",
    )

    return ConnectionPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            ConnectionOut.model_validate(record) for record in records
        ],
    )


# ----------------------------------------------------------------------
# WebSocket
# ----------------------------------------------------------------------


@app.websocket("/ws/live")
async def live_updates(websocket: WebSocket):
    # Capture is owned by the app, never by a socket.  A client may disconnect
    # at any time without affecting the session.
    await websocket.accept()

    try:
        while True:
            await websocket.send_json(_live_payload())
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        return

    except Exception:
        return


# ----------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------
#
# Serving the UI from the API origin is what fixes the original reload loop:
# VS Code Live Server watched network_monitor.db and reloaded the page on
# every captured packet.  Open http://127.0.0.1:8000/ instead of port 5500.
app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIR, html=True),
    name="frontend",
)
