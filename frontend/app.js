
// The backend now serves this page, so use the same origin (works on any port).
// Port 8000 is only used when the page is opened through a separate dev server.
const DEV_SERVER_PORTS = new Set(["5500", "5173"]);
const IS_DEV_SERVER = DEV_SERVER_PORTS.has(window.location.port);
const API = IS_DEV_SERVER ? "http://127.0.0.1:8000" : "";
const WS = IS_DEV_SERVER
    ? "ws://127.0.0.1:8000/ws/live"
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/live`;

const $ = (id) => document.getElementById(id);

let socket = null;
let trafficChart = null;
let protocolChart = null;

const trafficLabels = [];
const uploadHistory = [];
const downloadHistory = [];

function formatBytes(bytes) {
    if (!Number.isFinite(Number(bytes))) return "--";

    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = Number(bytes);
    let index = 0;

    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index++;
    }

    return `${value.toFixed(2)} ${units[index]}`;
}

function formatRate(bytesPerSecond) {
    return `${formatBytes(bytesPerSecond)}/s`;
}

function setMessage(message, isError = false) {
    $("captureMessage").textContent = message;
    $("captureMessage").style.color = isError ? "#f87171" : "#86efac";
}

function initializeCharts() {
    trafficChart = new Chart($("trafficChart"), {
        type: "line",
        data: {
            labels: trafficLabels,
            datasets: [
                {
                    label: "Upload",
                    data: uploadHistory,
                    borderColor: "#38bdf8",
                    backgroundColor: "#38bdf822",
                    fill: true,
                    tension: 0.35
                },
                {
                    label: "Download",
                    data: downloadHistory,
                    borderColor: "#a78bfa",
                    backgroundColor: "#a78bfa22",
                    fill: true,
                    tension: 0.35
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    ticks: { color: "#91a2ba" },
                    grid: { color: "#26344a" }
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: "#91a2ba" },
                    grid: { color: "#26344a" }
                }
            },
            plugins: {
                legend: {
                    labels: { color: "#dce7f5" }
                }
            }
        }
    });

    protocolChart = new Chart($("protocolChart"), {
        type: "doughnut",
        data: {
            labels: [],
            datasets: [{
                data: [],
                backgroundColor: [
                    "#38bdf8",
                    "#a78bfa",
                    "#34d399",
                    "#fbbf24",
                    "#fb7185",
                    "#818cf8",
                    "#64748b"
                ],
                borderColor: "#111c30",
                borderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        color: "#dce7f5",
                        padding: 15
                    }
                }
            }
        }
    });
}

async function apiRequest(path, options = {}) {
    const response = await fetch(`${API}${path}`, options);

    let data;
    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
    }

    return data;
}

async function loadInterfaces() {
    const select = $("interfaceSelect");
    select.innerHTML = '<option value="">Loading...</option>';

    try {
        const data = await apiRequest("/api/interfaces");

        select.innerHTML = "";

        if (!data.interfaces || data.interfaces.length === 0) {
            select.innerHTML = '<option value="">No interfaces found</option>';
            return;
        }

        data.interfaces.forEach((item) => {
            const option = document.createElement("option");
            option.value = item.capture_name;
            option.textContent =
                `${item.description} (${item.is_up ? "Up" : "Down"})`;
            option.disabled = item.is_up === false;
            select.appendChild(option);
        });

        if (select.value) {
            setMessage("Network interfaces loaded.");
        }
    } catch (error) {
        select.innerHTML = '<option value="">API unavailable</option>';
        setMessage(`Interface discovery failed: ${error.message}`, true);
    }
}

function updateStatistics(stats) {
    if (!stats) return;

    $("totalPackets").textContent =
        Number(stats.total_packets || 0).toLocaleString();

    $("totalBytes").textContent =
        formatBytes(stats.total_bytes || 0);

    $("uploadRate").textContent =
        formatRate(stats.upload_bytes_per_second || 0);

    $("downloadRate").textContent =
        formatRate(stats.download_bytes_per_second || 0);

    $("sourceIPs").textContent =
        stats.unique_source_ips ?? 0;

    $("destinationIPs").textContent =
        stats.unique_destination_ips ?? 0;

    const protocols = stats.protocol_counts || {};
    protocolChart.data.labels = Object.keys(protocols);
    protocolChart.data.datasets[0].data = Object.values(protocols);
    protocolChart.update("none");

    const now = new Date().toLocaleTimeString();

    trafficLabels.push(now);
    uploadHistory.push(stats.upload_bytes_per_second || 0);
    downloadHistory.push(stats.download_bytes_per_second || 0);

    if (trafficLabels.length > 20) {
        trafficLabels.shift();
        uploadHistory.shift();
        downloadHistory.shift();
    }

    trafficChart.update("none");
}

function updateCaptureStatus(running) {
    $("captureText").textContent =
        running ? "Capture running" : "Capture stopped";

    $("captureDot").classList.toggle("running", running);

    $("startButton").disabled = running;
    $("stopButton").disabled = !running;
    $("interfaceSelect").disabled = running;
}

function connectWebSocket() {
    if (socket && (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
    )) {
        return;
    }

    socket = new WebSocket(WS);

    socket.onopen = () => {
        $("connectionDot").classList.add("online");
        $("connectionText").textContent = "API connected";
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);

        updateCaptureStatus(data.running);

        if (data.statistics) {
            updateStatistics(data.statistics);
        }
    };

    socket.onclose = () => {
        $("connectionDot").classList.remove("online");
        $("connectionText").textContent = "Reconnecting...";
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = () => {
        socket.close();
    };
}

async function startCapture() {
    const interfaceName = $("interfaceSelect").value;

    if (!interfaceName) {
        setMessage("Select an active network interface first.", true);
        return;
    }

    $("startButton").disabled = true;
    setMessage("Starting packet capture...");

    try {
        const result = await apiRequest("/api/capture/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ interface: interfaceName })
        });

        setMessage(result.message);
        updateCaptureStatus(true);
    } catch (error) {
        setMessage(`Could not start capture: ${error.message}`, true);
        $("startButton").disabled = false;
    }
}

async function stopCapture() {
    $("stopButton").disabled = true;
    setMessage("Stopping capture and flushing queued packets...");

    try {
        const result = await apiRequest("/api/capture/stop", {
            method: "POST"
        });

        updateCaptureStatus(false);
        setMessage(result.message);
        await refreshPackets();
    } catch (error) {
        setMessage(`Could not stop capture: ${error.message}`, true);
        $("stopButton").disabled = false;
    }
}

function packetRowValues(packet) {
    return [
        packet.id,
        packet.timestamp,
        `${packet.source_ip}${packet.source_port ? ":" + packet.source_port : ""}`,
        `${packet.destination_ip}${packet.destination_port ? ":" + packet.destination_port : ""}`,
        packet.protocol,
        packet.application_protocol,
        formatBytes(packet.packet_size),
        packet.direction
    ].map((value) => String(value ?? "--"));
}

function createPacketRow(packet) {
    const row = document.createElement("tr");
    row.dataset.packetId = String(packet.id);

    packetRowValues(packet).forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
    });

    return row;
}

function updatePacketRow(row, packet) {
    packetRowValues(packet).forEach((value, index) => {
        const cell = row.children[index];

        if (cell && cell.textContent !== value) {
            cell.textContent = value;
        }
    });
}

// Rows are updated in place instead of clearing the whole table, so the
// dashboard no longer blinks every few seconds while packets are captured.
async function refreshPackets() {
    try {
        const data = await apiRequest("/api/packets?limit=50");
        const table = $("packetTable");
        const items = data.items || [];

        if (items.length === 0) {
            if (!table.querySelector(".empty-state")) {
                const row = document.createElement("tr");
                const cell = document.createElement("td");
                cell.colSpan = 8;
                cell.className = "empty-state";
                cell.textContent = "No packet records found.";
                row.appendChild(cell);
                table.replaceChildren(row);
            }
            return;
        }

        const existingRows = new Map();
        table.querySelectorAll("tr[data-packet-id]").forEach((row) => {
            existingRows.set(row.dataset.packetId, row);
        });

        const fragment = document.createDocumentFragment();

        items.forEach((packet) => {
            const row = existingRows.get(String(packet.id));

            if (row) {
                updatePacketRow(row, packet);
                fragment.appendChild(row);
            } else {
                fragment.appendChild(createPacketRow(packet));
            }
        });

        table.replaceChildren(fragment);
    } catch (error) {
        setMessage(`Packet history error: ${error.message}`, true);
    }
}

async function loadGateway() {
    try {
        const data = await apiRequest("/api/gateway");

        $("gatewayInfo").textContent =
            `Interface: ${data.interface} | Local IP: ${data.local_ip} | ` +
            `Gateway: ${data.gateway_ip} | Subnet: ${data.network}`;
    } catch (error) {
        $("gatewayInfo").textContent =
            `Gateway discovery failed: ${error.message}`;
    }
}

async function scanDevices() {
    $("deviceInfo").textContent = "Scanning local network...";

    try {
        const data = await apiRequest("/api/devices");

        $("deviceInfo").textContent =
            `Discovered ${data.device_count} devices on ${data.network}: ` +
            data.devices.map(
                device => `${device.ip_address} (${device.mac_address})` +
                (device.is_gateway ? " [Gateway]" : "")
            ).join(" | ");
    } catch (error) {
        $("deviceInfo").textContent =
            `Device scan failed: ${error.message}`;
    }
}

$("startButton").addEventListener("click", startCapture);
$("stopButton").addEventListener("click", stopCapture);
$("refreshInterfaces").addEventListener("click", loadInterfaces);
$("refreshPackets").addEventListener("click", () => refreshPackets());
$("scanDevices").addEventListener("click", scanDevices);

initializeCharts();
loadInterfaces();
loadGateway();
refreshPackets();
connectWebSocket();

setInterval(refreshPackets, 3000);
