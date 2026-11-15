
import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import or_, text

from monitor.capture.capture_manager import CaptureManager
from monitor.discovery.interface_discovery import InterfaceDiscovery
from monitor.discovery.gateway_discovery import GatewayDiscovery
from monitor.discovery.device_discovery import DeviceDiscovery
from monitor.storage.database import engine, init_database, SessionLocal
from monitor.storage.models import PacketRecord


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"


app = FastAPI(
    title="Mini Network Analyzer API",
    description="Real-time network traffic monitoring backend",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5500",
        "http://127.0.0.1:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# Shared capture manager.
capture_manager = None
capture_lock = threading.Lock()


class StartCaptureRequest(BaseModel):
    interface: str


@app.on_event("startup")
def startup():
    init_database()


@app.get("/api")
def api_root():
    return {
        "message": "Mini Network Analyzer API is running",
        "docs": "/docs"
    }


@app.get("/api/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "connected"
    except Exception:
        database = "unavailable"

    return {"status": "healthy", "database": database}


@app.get("/api/interfaces")
def get_interfaces():
    discovery = InterfaceDiscovery()
    interfaces = discovery.discover()

    return {
        "count": len(interfaces),
        "interfaces": interfaces
    }


@app.get("/api/gateway")
def get_gateway():
    result = GatewayDiscovery().discover()

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    return result


@app.get("/api/devices")
def get_devices(interface: str | None = None):
    result = DeviceDiscovery().discover(interface=interface)

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    return result


@app.post("/api/capture/start")
def start_capture(request: StartCaptureRequest):
    global capture_manager

    discovery = InterfaceDiscovery()
    interfaces = discovery.discover()

    selected = next(
        (
            item for item in interfaces
            if item["capture_name"] == request.interface
        ),
        None
    )

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail="Selected network interface was not found."
        )

    if selected["is_up"] is False:
        raise HTTPException(
            status_code=400,
            detail="Selected network interface is down."
        )

    with capture_lock:
        if capture_manager and capture_manager.status()["running"]:
            raise HTTPException(
                status_code=409,
                detail="A capture session is already running."
            )

        capture_manager = CaptureManager(
            interface=request.interface
        )

        started = capture_manager.start()

        if not started:
            status = capture_manager.status()

            raise HTTPException(
                status_code=500,
                detail=status.get("error") or "Could not start packet capture."
            )

    return {
        "message": "Capture start requested.",
        "interface": request.interface,
        "status": capture_manager.status()
    }


@app.post("/api/capture/stop")
def stop_capture():
    if capture_manager is None:
        return {"message": "No capture session exists."}

    with capture_lock:
        stopped = capture_manager.stop()

    if not stopped:
        raise HTTPException(
            status_code=500,
            detail=capture_manager.status().get("error")
            or "Capture did not stop cleanly."
        )

    return {
        "message": "Capture stopped.",
        "status": capture_manager.status()
    }


@app.get("/api/capture/status")
def get_capture_status():
    if capture_manager is None:
        return {
            "running": False,
            "message": "Capture has not been started."
        }

    return capture_manager.status()


@app.get("/api/statistics")
def get_statistics():
    if capture_manager is None:
        return {
            "message": "No capture session exists.",
            "statistics": None
        }

    return capture_manager.statistics_engine.snapshot()


@app.get("/api/packets")
def get_packets(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    protocol: str | None = None,
    application_protocol: str | None = None,
    direction: str | None = None,
    search: str | None = None
):
    db = SessionLocal()

    try:
        query = db.query(PacketRecord)

        if protocol:
            query = query.filter(
                PacketRecord.protocol == protocol.upper()
            )

        if application_protocol:
            query = query.filter(
                PacketRecord.application_protocol
                == application_protocol.upper()
            )

        if direction:
            query = query.filter(
                PacketRecord.direction == direction.lower()
            )

        if search:
            term = f"%{search}%"
            query = query.filter(
                or_(
                    PacketRecord.source_ip.ilike(term),
                    PacketRecord.destination_ip.ilike(term),
                    PacketRecord.protocol.ilike(term),
                    PacketRecord.application_protocol.ilike(term)
                )
            )

        total = query.count()

        records = (
            query.order_by(PacketRecord.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = [
            {
                "id": packet.id,
                "timestamp": packet.timestamp,
                "source_ip": packet.source_ip,
                "destination_ip": packet.destination_ip,
                "source_port": packet.source_port,
                "destination_port": packet.destination_port,
                "protocol": packet.protocol,
                "application_protocol": packet.application_protocol,
                "packet_size": packet.packet_size,
                "tcp_flags": packet.tcp_flags,
                "direction": packet.direction,
                "ip_version": packet.ip_version
            }
            for packet in records
        ]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items
        }

    finally:
        db.close()


@app.websocket("/ws/live")
async def live_updates(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            if capture_manager is None:
                data = {
                    "running": False,
                    "statistics": None,
                    "queue_size": 0
                }
            else:
                status = capture_manager.status()

                data = {
                    "running": status["running"],
                    "statistics": status["statistics"],
                    "queue_size": status["queued_packets"],
                    "processed_packets": status["processed_packets"],
                    "storage_dropped_packets": (
                        status["storage_dropped_packets"]
                    ),
                    "storage_failed_packets": (
                        status["storage_failed_packets"]
                    ),
                    "error": status["error"]
                }

            await websocket.send_json(data)
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass


@app.on_event("shutdown")
def shutdown():
    global capture_manager

    if capture_manager is not None:
        capture_manager.stop()


# Serve the dashboard from the same origin as the API.
#
# This is the fix for the "dashboard keeps reloading" problem: the frontend was
# opened through VS Code Live Server, which watches the whole project folder.
# Packet capture writes to network_monitor.db continuously, so Live Server saw a
# file change every second and forced a full browser reload over and over.
#
# With this mount the backend serves the UI itself, so no file-watching dev
# server is involved. Open http://127.0.0.1:8000/ instead of port 5500.
app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIR, html=True),
    name="frontend"
)
