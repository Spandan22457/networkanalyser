/*
 * Central frontend configuration.
 *
 * The backend serves this page, so the API is same-origin by default.
 * Port 8000 is only used when the page is opened through a separate dev
 * server (Live Server 5500, Vite 5173).
 */
(function (NetScope) {
    "use strict";

    const DEV_SERVER_PORTS = new Set(["5500", "5173"]);
    const isDevServer = DEV_SERVER_PORTS.has(window.location.port);

    const apiBase = isDevServer ? "http://127.0.0.1:8000" : "";

    let wsUrl;

    if (isDevServer) {
        wsUrl = "ws://127.0.0.1:8000/ws/live";
    } else {
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        wsUrl = `${scheme}://${window.location.host}/ws/live`;
    }

    NetScope.config = {
        apiBase,
        wsUrl,
        isDevServer,
        openedFromDisk: window.location.protocol === "file:",

        packetPageSize: 25,
        connectionPageSize: 25,
        historyLimit: 200,
        topTalkerLimit: 10,

        // HTTP fallback polling when the WebSocket is unavailable.
        pollIntervalMs: 3000,
        statusPollIntervalMs: 5000,
        fallbackStatsIntervalMs: 3000,

        // WebSocket reconnect backoff.
        reconnectBaseMs: 1000,
        reconnectMaxMs: 15000,

        chartPoints: 30,
        requestTimeoutMs: 20000,
    };
})(window.NetScope = window.NetScope || {});
