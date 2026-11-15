/*
 * Dashboard controller.
 *
 * Responsibilities: hash routing, WebSocket lifecycle with backoff, HTTP
 * fallback polling, page loaders and capture controls.  All requests go
 * through NetScope.api; all rendering goes through NetScope.ui.
 */
(function (NetScope) {
    "use strict";

    const { ui, api, charts, config } = NetScope;
    const $ = ui.$;

    const PAGE_META = {
        overview: ["Network Overview", "Live traffic from the FastAPI backend"],
        traffic: ["Traffic Analysis", "Throughput, direction totals and top talkers"],
        packets: ["Packet Explorer", "Search, filter, sort and page through stored packets"],
        connections: ["Connections", "Flows aggregated from captured packets"],
        protocols: ["Protocols", "Transport and application protocol distribution"],
        interfaces: ["Interfaces", "Adapters, default gateway and local devices"],
        history: ["History", "Statistics snapshots persisted in SQLite"],
    };

    const state = {
        page: "overview",
        socket: null,
        wsConnected: false,
        reconnectAttempt: 0,
        reconnectTimer: null,
        lastPacketRefresh: 0,
        lastConnectionRefresh: 0,
        bannerTimer: null,
        interfaces: [],
        gateway: null,
        status: null,
        packets: {
            limit: config.packetPageSize,
            offset: 0,
            total: 0,
        },
        connections: {
            limit: config.connectionPageSize,
            offset: 0,
            total: 0,
        },
    };

    // ------------------------------------------------------------------
    // Banner / connection state
    // ------------------------------------------------------------------

    function showBanner(message) {
        const banner = $("globalError");

        if (!banner) {
            return;
        }

        banner.textContent = message;
        banner.hidden = false;

        window.clearTimeout(state.bannerTimer);
        state.bannerTimer = window.setTimeout(() => {
            banner.hidden = true;
        }, 9000);
    }

    function reportError(label, error) {
        const message = error && error.message ? error.message : String(error);
        showBanner(`${label}: ${message}`);
    }

    function setConnectionState(kind) {
        const dot = $("connectionDot");
        const text = $("connectionText");

        if (!dot || !text) {
            return;
        }

        dot.className = "status-dot";

        if (kind === "live") {
            dot.classList.add("online");
            text.textContent = "Live (WebSocket)";
        } else if (kind === "polling") {
            dot.classList.add("online");
            text.textContent = "Connected (polling)";
        } else {
            text.textContent = "Reconnecting…";
        }
    }

    // ------------------------------------------------------------------
    // Statistics rendering
    // ------------------------------------------------------------------

    function applyStatistics(stats) {
        if (!stats) {
            return;
        }

        const source = stats.source || "empty";

        ui.setText("statPackets", ui.formatNumber(stats.total_packets));
        ui.setText(
            "statPacketsMeta",
            source === "live"
                ? "Live session plus stored history"
                : source === "database"
                    ? "Stored in SQLite"
                    : "No packets yet"
        );

        ui.setText("statBytes", ui.formatBytes(stats.total_bytes));
        ui.setText("statUpload", ui.formatRate(stats.upload_bytes_per_second));
        ui.setText("statDownload", ui.formatRate(stats.download_bytes_per_second));
        ui.setText(
            "statPps",
            ui.isNumber(stats.packets_per_second)
                ? Number(stats.packets_per_second).toFixed(2)
                : "--"
        );

        const badge = $("trafficSource");
        if (badge) {
            badge.textContent = source;
            badge.className = `badge badge-${source}`;
        }

        const detailBadge = $("trafficDetailSource");
        if (detailBadge) {
            detailBadge.textContent = source;
            detailBadge.className = `badge badge-${source}`;
        }

        // Traffic page cards.
        ui.setText("trafficUpload", ui.formatBytes(stats.upload_bytes));
        ui.setText("trafficDownload", ui.formatBytes(stats.download_bytes));
        ui.setText("trafficAvg", ui.formatBytes(stats.average_packet_size));
        ui.setText(
            "trafficPps",
            ui.isNumber(stats.packets_per_second)
                ? Number(stats.packets_per_second).toFixed(2)
                : "--"
        );

        renderDirectionTotals(stats.direction_counts || {});

        if (stats.protocol_counts) {
            charts.updateProtocol(stats.protocol_counts);
            const hasProtocols = Object.values(stats.protocol_counts).some(
                (value) => Number(value) > 0
            );
            ui.setHidden("protocolEmpty", hasProtocols || !charts.available());
        }

        if (source === "live") {
            charts.pushTraffic(
                ui.formatTime(new Date().toISOString()),
                stats.upload_bytes_per_second,
                stats.download_bytes_per_second
            );
            ui.setHidden("trafficEmpty", true);
            ui.setHidden("trafficLargeEmpty", true);
        } else if (stats.total_packets > 0) {
            ui.setHidden("trafficEmpty", true);
            ui.setHidden("trafficLargeEmpty", true);
        }
    }

    function renderDirectionTotals(counts) {
        const entries = Object.entries(counts || {});

        ui.renderCollection({
            tbodyId: "directionBody",
            items: entries,
            cellsFor: ([direction, packets]) => [
                ui.directionCell(direction),
                ui.formatNumber(packets),
            ],
            emptyId: "directionEmpty",
        });
    }

    function applyCounters(data) {
        ui.setText("pipeCaptured", ui.formatNumber(data.captured_packets));
        ui.setText("pipeProcessed", ui.formatNumber(data.processed_packets));
        ui.setText("pipeStored", ui.formatNumber(data.stored_packets));
        ui.setText("pipeQueued", ui.formatNumber(data.queued_packets));
        ui.setText("pipeDropped", ui.formatNumber(data.storage_dropped_packets));
        ui.setText("pipeFailed", ui.formatNumber(data.storage_failed_packets));
        ui.setText("pipeConnErrors", ui.formatNumber(data.connection_errors));
        ui.setText("pipeDeadLetter", ui.formatNumber(data.dead_letter_records));
    }

    function applyStatus(status) {
        if (!status) {
            return;
        }

        state.status = status;

        const pill = $("captureState");

        if (pill) {
            if (status.error) {
                pill.textContent = "Error";
                pill.className = "pill pill-error";
                pill.title = status.error;
                showBanner(`Capture: ${status.error}`);
            } else if (status.running) {
                pill.textContent = status.interface
                    ? `Capturing · ${status.interface}`
                    : "Capturing";
                pill.className = "pill pill-running";
                pill.title = status.interface || "";
            } else {
                pill.textContent = "Stopped";
                pill.className = "pill pill-stopped";
                pill.title = status.interface || "";
            }
        }

        const start = $("startButton");
        const stop = $("stopButton");

        if (start) {
            start.disabled = Boolean(status.running);
        }

        if (stop) {
            stop.disabled = !status.running;
        }

        applyCounters(status);

        const dot = $("connectionDot");
        if (dot && state.wsConnected && status.running) {
            dot.classList.add("running");
        }
    }

    // ------------------------------------------------------------------
    // WebSocket
    // ------------------------------------------------------------------

    function connectSocket() {
        if (state.socket) {
            try {
                state.socket.close();
            } catch (ignored) {
                /* already closed */
            }
        }

        let socket;

        try {
            socket = new WebSocket(config.wsUrl);
        } catch (error) {
            setConnectionState("offline");
            scheduleReconnect();
            return;
        }

        state.socket = socket;

        socket.addEventListener("open", () => {
            state.wsConnected = true;
            state.reconnectAttempt = 0;
            setConnectionState("live");
            charts.resetTraffic();
            loadStatistics().catch(() => {});
        });

        socket.addEventListener("message", (event) => {
            let data;

            try {
                data = JSON.parse(event.data);
            } catch (error) {
                return;
            }

            if (data && data.type === "live") {
                applyLive(data);
            }
        });

        socket.addEventListener("close", () => {
            state.wsConnected = false;
            setConnectionState("offline");
            scheduleReconnect();
        });

        socket.addEventListener("error", () => {
            try {
                socket.close();
            } catch (ignored) {
                /* no-op */
            }
        });
    }

    function scheduleReconnect() {
        if (state.reconnectTimer !== null) {
            return;
        }

        const delay = Math.min(
            config.reconnectMaxMs,
            config.reconnectBaseMs * Math.pow(2, state.reconnectAttempt)
        );

        state.reconnectAttempt += 1;

        state.reconnectTimer = window.setTimeout(() => {
            state.reconnectTimer = null;
            connectSocket();
        }, delay);
    }

    function applyLive(data) {
        applyStatistics(data);

        applyStatus({
            running: data.running,
            interface: data.interface,
            captured_packets: data.captured_packets,
            processed_packets: data.processed_packets,
            stored_packets: data.stored_packets,
            queued_packets: data.queued_packets,
            storage_dropped_packets: data.storage_dropped_packets,
            storage_failed_packets: data.storage_failed_packets,
            connection_errors: state.status ? state.status.connection_errors : 0,
            dead_letter_records: state.status
                ? state.status.dead_letter_records
                : 0,
            error: data.error,
        });

        if (data.top_talkers) {
            renderTopTalkers(data.top_talkers);
        }

        const now = Date.now();

        if (state.page === "packets" && now - state.lastPacketRefresh > 3000) {
            state.lastPacketRefresh = now;
            loadPackets({ silent: true }).catch(() => {});
        }

        if (
            state.page === "connections" &&
            now - state.lastConnectionRefresh > 3000
        ) {
            state.lastConnectionRefresh = now;
            loadConnections({ silent: true }).catch(() => {});
        }
    }

    // ------------------------------------------------------------------
    // Loaders
    // ------------------------------------------------------------------

    async function loadHealth() {
        try {
            const health = await api.health();
            ui.setText(
                "databaseText",
                health.database === "connected"
                    ? `Database: connected`
                    : `Database: ${health.database}`
            );
        } catch (error) {
            ui.setText("databaseText", "Database: unavailable");
        }
    }

    async function loadStatistics() {
        const stats = await api.statistics();
        applyStatistics(stats);
        return stats;
    }

    async function loadInterfaces() {
        const select = $("interfaceSelect");

        try {
            const payload = await api.interfaces();
            state.interfaces = payload.interfaces || [];

            renderInterfaces(state.interfaces);

            if (select) {
                const previous = select.value;
                select.textContent = "";

                if (state.interfaces.length === 0) {
                    const option = document.createElement("option");
                    option.value = "";
                    option.textContent = "No interfaces found";
                    select.appendChild(option);
                }

                state.interfaces.forEach((iface) => {
                    const option = document.createElement("option");
                    option.value = iface.capture_name;
                    option.textContent = iface.is_up === false
                        ? `${iface.name} (down)`
                        : iface.name;
                    select.appendChild(option);
                });

                const stillValid = state.interfaces.some(
                    (iface) => iface.capture_name === previous
                );

                if (stillValid) {
                    select.value = previous;
                } else {
                    const preferred =
                        state.interfaces.find(
                            (iface) =>
                                iface.is_up === true &&
                                Array.isArray(iface.ipv4_addresses) &&
                                iface.ipv4_addresses.length > 0
                        ) || state.interfaces.find((iface) => iface.is_up === true);

                    if (preferred) {
                        select.value = preferred.capture_name;
                    }
                }
            }
        } catch (error) {
            reportError("Load interfaces", error);
            ui.renderError({
                tbodyId: "interfacesBody",
                emptyId: "interfacesEmpty",
                errorId: "interfacesError",
                message: error.message,
            });
        }
    }

    function renderInterfaces(interfaces) {
        ui.renderCollection({
            tbodyId: "interfacesBody",
            items: interfaces,
            cellsFor: (iface) => [
                iface.name,
                iface.description,
                (iface.ipv4_addresses || []).join(", ") || "--",
                iface.mac_address || "--",
                iface.is_up === true
                    ? { text: "up", className: "state state-open" }
                    : iface.is_up === false
                        ? { text: "down", className: "state state-closed" }
                        : { text: "unknown", className: "state" },
                iface.capture_name,
            ],
            emptyId: "interfacesEmpty",
            errorId: "interfacesError",
        });
    }

    async function loadGateway() {
        try {
            const gateway = await api.gateway();
            state.gateway = gateway;

            renderCounters("gatewayInfo", [
                ["Interface", gateway.capture_name || gateway.interface],
                ["Local IP", gateway.local_ip],
                ["Gateway", gateway.gateway_ip],
                ["Subnet", gateway.network],
            ]);

            ui.setHidden("gatewayError", true);
        } catch (error) {
            ui.showError("gatewayError", error.message);
        }
    }

    function renderCounters(id, pairs) {
        const list = $(id);

        if (!list) {
            return;
        }

        list.textContent = "";

        pairs.forEach(([label, value]) => {
            const wrapper = document.createElement("div");
            const term = document.createElement("dt");
            const detail = document.createElement("dd");

            term.textContent = label;
            detail.textContent = value === null || value === undefined ? "--" : String(value);

            wrapper.appendChild(term);
            wrapper.appendChild(detail);
            list.appendChild(wrapper);
        });
    }

    async function loadDevices() {
        const button = $("scanDevices");

        if (button) {
            button.disabled = true;
            button.textContent = "Scanning…";
        }

        try {
            const iface = state.gateway ? state.gateway.capture_name : null;
            const result = await api.devices(iface);
            const devices = result.devices || [];

            ui.renderCollection({
                tbodyId: "devicesBody",
                items: devices,
                cellsFor: (device) => [device.ip, device.mac],
                emptyId: "devicesEmpty",
                errorId: "devicesError",
            });
        } catch (error) {
            ui.renderError({
                tbodyId: "devicesBody",
                emptyId: "devicesEmpty",
                errorId: "devicesError",
                message: error.message,
            });
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = "Scan subnet";
            }
        }
    }

    async function loadProtocols() {
        try {
            const payload = await api.protocols();

            ui.setText("protocolTotal", ui.formatNumber(payload.total_packets));
            ui.setText(
                "protocolTransportCount",
                ui.formatNumber((payload.protocols || []).length)
            );
            ui.setText(
                "protocolApplicationCount",
                ui.formatNumber((payload.application_protocols || []).length)
            );

            renderProtocolTable("protocolTransportBody", payload.protocols, "protocolTransportEmpty");
            renderProtocolTable(
                "protocolApplicationBody",
                payload.application_protocols,
                "protocolApplicationEmpty"
            );

            ui.showError("protocolError", "");
        } catch (error) {
            ui.showError("protocolError", error.message);
        }
    }

    function renderProtocolTable(tbodyId, rows, emptyId) {
        ui.renderRows($(tbodyId), rows || [], (row) => [
            ui.protocolCell(row.protocol),
            ui.formatNumber(row.packets),
            ui.formatBytes(row.bytes),
            ui.formatPercent(row.percentage),
        ]);

        ui.setHidden(emptyId, (rows || []).length > 0);
    }

    async function loadTopTalkers() {
        try {
            const talkers = await api.topTalkers(config.topTalkerLimit);
            renderTopTalkers(talkers);
        } catch (error) {
            reportError("Load top talkers", error);
        }
    }

    function renderTopTalkers(talkers) {
        const cellsFor = (talker) => [
            talker.ip,
            ui.formatNumber(talker.packets),
            ui.formatBytes(talker.bytes),
        ];

        ui.renderRows($("topTalkersBody"), talkers || [], cellsFor);
        ui.renderRows($("topTalkersTrafficBody"), talkers || [], cellsFor);
        ui.setHidden("talkersEmpty", (talkers || []).length > 0);
        ui.setHidden("talkersTrafficEmpty", (talkers || []).length > 0);
    }

    function packetCells(packet) {
        return [
            packet.timestamp ? ui.formatTime(packet.timestamp) : "--",
            ui.formatEndpoint(packet.source_ip, packet.source_port),
            ui.formatEndpoint(packet.destination_ip, packet.destination_port),
            ui.protocolCell(packet.protocol),
            packet.application_protocol || "--",
            ui.formatBytes(packet.packet_size),
            ui.directionCell(packet.direction),
            packet.interface || "--",
        ];
    }

    async function loadRecentPackets() {
        try {
            const page = await api.packets({
                limit: 10,
                offset: 0,
                sort: "id",
                order: "desc",
            });

            ui.renderCollection({
                tbodyId: "recentPacketsBody",
                items: page.items || [],
                cellsFor: packetCells,
                emptyId: "recentPacketsEmpty",
                errorId: "recentPacketsError",
            });
        } catch (error) {
            ui.renderError({
                tbodyId: "recentPacketsBody",
                emptyId: "recentPacketsEmpty",
                errorId: "recentPacketsError",
                message: error.message,
            });
        }
    }

    function readPacketParams() {
        return {
            limit: state.packets.limit,
            offset: state.packets.offset,
            search: $("packetSearch") ? $("packetSearch").value.trim() : "",
            protocol: $("packetProtocol") ? $("packetProtocol").value : "",
            application_protocol: $("packetApplication")
                ? $("packetApplication").value
                : "",
            direction: $("packetDirection") ? $("packetDirection").value : "",
            sort: $("packetSort") ? $("packetSort").value : "id",
            order: $("packetOrder") ? $("packetOrder").value : "desc",
        };
    }

    async function loadPackets(options) {
        const settings = options || {};
        const params = readPacketParams();

        try {
            const page = await api.packets(params);

            state.packets.total = page.total;
            state.lastPacketRefresh = Date.now();

            ui.renderCollection({
                tbodyId: "packetTableBody",
                items: page.items || [],
                cellsFor: (packet) => [
                    packet.id,
                    ui.formatTime(packet.timestamp),
                    ui.formatEndpoint(packet.source_ip, packet.source_port),
                    ui.formatEndpoint(packet.destination_ip, packet.destination_port),
                    ui.protocolCell(packet.protocol),
                    packet.application_protocol || "--",
                    ui.formatBytes(packet.packet_size),
                    ui.directionCell(packet.direction),
                    packet.interface || "--",
                    packet.source_mac
                        ? `${packet.source_mac} → ${packet.destination_mac || "?"}`
                        : "--",
                ],
                emptyId: "packetEmpty",
                errorId: "packetError",
            });

            updatePacketPagination(page.total);
        } catch (error) {
            if (!settings.silent) {
                ui.renderError({
                    tbodyId: "packetTableBody",
                    emptyId: "packetEmpty",
                    errorId: "packetError",
                    message: error.message,
                });
            }
        }
    }

    function updatePacketPagination(total) {
        const info = ui.pageInfo(total, state.packets.offset, state.packets.limit);

        ui.setText(
            "packetRange",
            info.total === 0
                ? "No rows"
                : `Showing ${info.from}–${info.to} of ${info.total}`
        );
        ui.setText("packetPageLabel", `Page ${info.page} of ${info.pages}`);

        const prev = $("packetPrev");
        const next = $("packetNext");

        if (prev) {
            prev.disabled = state.packets.offset <= 0;
        }

        if (next) {
            next.disabled = state.packets.offset + state.packets.limit >= info.total;
        }
    }

    async function loadConnections(options) {
        const settings = options || {};

        try {
            const page = await api.connections({
                limit: state.connections.limit,
                offset: state.connections.offset,
                search: $("connectionSearch") ? $("connectionSearch").value.trim() : "",
                protocol: $("connectionProtocol") ? $("connectionProtocol").value : "",
                state: $("connectionState") ? $("connectionState").value : "",
                sort: "last_seen",
                order: "desc",
            });

            state.connections.total = page.total;
            state.lastConnectionRefresh = Date.now();

            ui.renderCollection({
                tbodyId: "connectionTableBody",
                items: page.items || [],
                cellsFor: (connection) => [
                    ui.formatEndpoint(connection.source_ip, connection.source_port),
                    ui.formatEndpoint(connection.destination_ip, connection.destination_port),
                    ui.protocolCell(connection.protocol),
                    ui.stateCell(connection.state),
                    ui.formatNumber(connection.packet_count),
                    ui.formatBytes(connection.byte_count),
                    ui.formatDateTime(connection.first_seen),
                    ui.relativeTime(connection.last_seen),
                ],
                emptyId: "connectionEmpty",
                errorId: "connectionError",
            });

            updateConnectionPagination(page.total);
            ui.setText("statConnections", ui.formatNumber(page.total));
        } catch (error) {
            if (!settings.silent) {
                ui.renderError({
                    tbodyId: "connectionTableBody",
                    emptyId: "connectionEmpty",
                    errorId: "connectionError",
                    message: error.message,
                });
            }
        }
    }

    function updateConnectionPagination(total) {
        const info = ui.pageInfo(
            total,
            state.connections.offset,
            state.connections.limit
        );

        ui.setText(
            "connectionRange",
            info.total === 0
                ? "No rows"
                : `Showing ${info.from}–${info.to} of ${info.total}`
        );
        ui.setText("connectionPageLabel", `Page ${info.page} of ${info.pages}`);

        const prev = $("connectionPrev");
        const next = $("connectionNext");

        if (prev) {
            prev.disabled = state.connections.offset <= 0;
        }

        if (next) {
            next.disabled =
                state.connections.offset + state.connections.limit >= info.total;
        }
    }

    async function loadConnectionCount() {
        try {
            const page = await api.connections({ limit: 1, offset: 0 });
            ui.setText("statConnections", ui.formatNumber(page.total));
        } catch (error) {
            /* Count is cosmetic; the connections page reports real errors. */
        }
    }

    async function loadHistory() {
        try {
            const snapshots = await api.statisticsHistory({
                limit: config.historyLimit,
            });

            ui.renderCollection({
                tbodyId: "historyBody",
                items: snapshots || [],
                cellsFor: (snapshot) => [
                    ui.formatDateTime(snapshot.timestamp),
                    ui.formatNumber(snapshot.total_packets),
                    ui.formatBytes(snapshot.total_bytes),
                    ui.formatBytes(snapshot.upload_bytes),
                    ui.formatBytes(snapshot.download_bytes),
                    Number(snapshot.packets_per_second || 0).toFixed(2),
                ],
                emptyId: "historyEmpty",
                errorId: "historyError",
            });

            charts.updateHistory(snapshots || []);

            const empty = (snapshots || []).length === 0;
            ui.setHidden("historyEmpty", !empty);
            ui.setHidden("historyChartEmpty", !empty || !charts.available());
        } catch (error) {
            ui.renderError({
                tbodyId: "historyBody",
                emptyId: "historyEmpty",
                errorId: "historyError",
                message: error.message,
            });
        }
    }

    async function refreshStatus() {
        try {
            const status = await api.captureStatus();
            applyStatus(status);
        } catch (error) {
            const pill = $("captureState");

            if (pill) {
                pill.textContent = "Offline";
                pill.className = "pill pill-error";
            }
        }
    }

    // ------------------------------------------------------------------
    // Routing
    // ------------------------------------------------------------------

    function pageFromHash() {
        const name = window.location.hash.replace("#", "");
        return PAGE_META[name] ? name : "overview";
    }

    function showPage(name) {
        state.page = name;

        document.querySelectorAll(".page").forEach((section) => {
            section.classList.toggle("active", section.id === `page-${name}`);
        });

        document.querySelectorAll("#mainNav a").forEach((link) => {
            link.classList.toggle("active", link.dataset.page === name);
        });

        const [title, subtitle] = PAGE_META[name];

        ui.setText("pageTitle", title);
        ui.setText("pageSubtitle", subtitle);

        loadPage(name);
    }

    function loadPage(name) {
        switch (name) {
            case "packets":
                loadPackets().catch(() => {});
                break;
            case "connections":
                loadConnections().catch(() => {});
                break;
            case "protocols":
                loadProtocols();
                break;
            case "interfaces":
                loadInterfaces();
                loadGateway();
                break;
            case "history":
                loadHistory();
                break;
            case "traffic":
                loadStatistics().catch(() => {});
                loadTopTalkers();
                break;
            case "overview":
            default:
                loadRecentPackets();
                break;
        }
    }

    // ------------------------------------------------------------------
    // Capture controls
    // ------------------------------------------------------------------

    async function startCapture() {
        const select = $("interfaceSelect");
        const iface = select ? select.value : "";

        if (!iface) {
            showBanner("Choose a network interface before starting capture.");
            return;
        }

        const button = $("startButton");

        if (button) {
            button.disabled = true;
        }

        try {
            const status = await api.startCapture(iface);
            applyStatus(status);
            await loadStatistics().catch(() => {});
            await loadRecentPackets();
        } catch (error) {
            reportError("Start capture", error);
        } finally {
            await refreshStatus().catch(() => {});
        }
    }

    async function stopCapture() {
        const button = $("stopButton");

        if (button) {
            button.disabled = true;
        }

        try {
            const status = await api.stopCapture();
            applyStatus(status);
            await loadStatistics().catch(() => {});
            await loadHistory().catch(() => {});
        } catch (error) {
            reportError("Stop capture", error);
        } finally {
            await refreshStatus().catch(() => {});
        }
    }

    // ------------------------------------------------------------------
    // Event wiring
    // ------------------------------------------------------------------

    function bindEvents() {
        window.addEventListener("hashchange", () => showPage(pageFromHash()));

        const start = $("startButton");
        const stop = $("stopButton");

        if (start) {
            start.addEventListener("click", startCapture);
        }

        if (stop) {
            stop.addEventListener("click", stopCapture);
        }

        const packetSearch = $("packetSearch");

        if (packetSearch) {
            packetSearch.addEventListener(
                "input",
                ui.debounce(() => {
                    state.packets.offset = 0;
                    loadPackets();
                }, 350)
            );
        }

        ["packetProtocol", "packetApplication", "packetDirection", "packetSort", "packetOrder"].forEach(
            (id) => {
                const node = $(id);

                if (node) {
                    node.addEventListener("change", () => {
                        state.packets.offset = 0;
                        loadPackets();
                    });
                }
            }
        );

        const pageSize = $("packetPageSize");

        if (pageSize) {
            pageSize.addEventListener("change", () => {
                state.packets.limit = Number(pageSize.value) || config.packetPageSize;
                state.packets.offset = 0;
                loadPackets();
            });
        }

        const packetPrev = $("packetPrev");
        const packetNext = $("packetNext");
        const packetRefresh = $("packetRefresh");

        if (packetPrev) {
            packetPrev.addEventListener("click", () => {
                state.packets.offset = Math.max(
                    0,
                    state.packets.offset - state.packets.limit
                );
                loadPackets();
            });
        }

        if (packetNext) {
            packetNext.addEventListener("click", () => {
                state.packets.offset += state.packets.limit;
                loadPackets();
            });
        }

        if (packetRefresh) {
            packetRefresh.addEventListener("click", () => loadPackets());
        }

        const connectionSearch = $("connectionSearch");

        if (connectionSearch) {
            connectionSearch.addEventListener(
                "input",
                ui.debounce(() => {
                    state.connections.offset = 0;
                    loadConnections();
                }, 350)
            );
        }

        ["connectionProtocol", "connectionState"].forEach((id) => {
            const node = $(id);

            if (node) {
                node.addEventListener("change", () => {
                    state.connections.offset = 0;
                    loadConnections();
                });
            }
        });

        const connectionPrev = $("connectionPrev");
        const connectionNext = $("connectionNext");
        const connectionRefresh = $("connectionRefresh");

        if (connectionPrev) {
            connectionPrev.addEventListener("click", () => {
                state.connections.offset = Math.max(
                    0,
                    state.connections.offset - state.connections.limit
                );
                loadConnections();
            });
        }

        if (connectionNext) {
            connectionNext.addEventListener("click", () => {
                state.connections.offset += state.connections.limit;
                loadConnections();
            });
        }

        if (connectionRefresh) {
            connectionRefresh.addEventListener("click", () => loadConnections());
        }

        const interfaceRefresh = $("interfaceRefresh");

        if (interfaceRefresh) {
            interfaceRefresh.addEventListener("click", () => {
                loadInterfaces();
                loadGateway();
            });
        }

        const scan = $("scanDevices");

        if (scan) {
            scan.addEventListener("click", loadDevices);
        }

        const historyRefresh = $("historyRefresh");

        if (historyRefresh) {
            historyRefresh.addEventListener("click", () => loadHistory());
        }
    }

    // ------------------------------------------------------------------
    // Background refresh
    // ------------------------------------------------------------------

    function startTimers() {
        window.setInterval(refreshStatus, config.statusPollIntervalMs);
        window.setInterval(loadConnectionCount, 10000);

        window.setInterval(() => {
            if (state.wsConnected) {
                return;
            }

            // HTTP fallback: keep the dashboard honest when the WebSocket
            // cannot connect, without pretending it is live.
            setConnectionState("polling");
            loadStatistics().catch(() => {});
            loadTopTalkers();
        }, config.fallbackStatsIntervalMs);

        window.setInterval(() => {
            if (state.page === "packets") {
                loadPackets({ silent: true });
            } else if (state.page === "connections") {
                loadConnections({ silent: true });
            } else if (state.page === "overview") {
                loadRecentPackets();
            } else if (state.page === "history" && state.status && state.status.running) {
                loadHistory();
            }
        }, config.pollIntervalMs);
    }

    // ------------------------------------------------------------------
    // Boot
    // ------------------------------------------------------------------

    function boot() {
        if (config.openedFromDisk) {
            ui.setHidden("fileWarning", false);
        }

        const chartsReady = charts.init();

        if (!chartsReady) {
            ["trafficEmpty", "trafficLargeEmpty", "protocolEmpty"].forEach((id) => {
                const node = $(id);

                if (node) {
                    node.textContent =
                        "Charts unavailable: Chart.js could not be loaded.";
                    node.hidden = false;
                }
            });
        }

        bindEvents();
        showPage(pageFromHash());

        loadHealth();
        loadInterfaces();
        loadGateway();
        loadStatistics().catch((error) => reportError("Load statistics", error));
        loadProtocols();
        loadTopTalkers();
        loadRecentPackets();
        loadConnectionCount();
        refreshStatus();

        connectSocket();
        startTimers();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})(window.NetScope = window.NetScope || {});
