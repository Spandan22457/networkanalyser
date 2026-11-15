/*
 * Reusable API service.
 *
 * Every network call in the dashboard goes through this module so the base
 * URL, timeout, error shape and JSON handling exist in exactly one place.
 * Failures surface as ApiError; callers show an error state and never
 * substitute fabricated data.
 */
(function (NetScope) {
    "use strict";

    class ApiError extends Error {
        constructor(message, status, url) {
            super(message);
            this.name = "ApiError";
            this.status = status || 0;
            this.url = url || "";
        }
    }

    function buildUrl(path, params) {
        const base = NetScope.config.apiBase || window.location.origin;
        const url = new URL(path, base);

        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                if (value === undefined || value === null || value === "") {
                    return;
                }
                url.searchParams.set(key, String(value));
            });
        }

        return url;
    }

    async function request(path, options) {
        const settings = options || {};
        const url = buildUrl(path, settings.params);
        const controller = new AbortController();
        const timeout = window.setTimeout(
            () => controller.abort(),
            NetScope.config.requestTimeoutMs
        );

        let response;

        try {
            response = await fetch(url.toString(), {
                method: settings.method || "GET",
                headers: settings.body
                    ? { "Content-Type": "application/json" }
                    : undefined,
                body: settings.body
                    ? JSON.stringify(settings.body)
                    : undefined,
                signal: controller.signal,
            });
        } catch (error) {
            const reason =
                error.name === "AbortError"
                    ? "Request timed out"
                    : error.message;
            throw new ApiError(reason, 0, url.toString());
        } finally {
            window.clearTimeout(timeout);
        }

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;

            try {
                const payload = await response.json();
                if (payload && payload.detail) {
                    detail =
                        typeof payload.detail === "string"
                            ? payload.detail
                            : JSON.stringify(payload.detail);
                }
            } catch (ignored) {
                /* Non-JSON error body; keep the status text. */
            }

            throw new ApiError(detail, response.status, url.toString());
        }

        if (response.status === 204) {
            return null;
        }

        return response.json();
    }

    NetScope.ApiError = ApiError;

    NetScope.api = {
        health: () => request("/api/health"),

        interfaces: () => request("/api/interfaces"),
        gateway: () => request("/api/gateway"),
        devices: (iface) =>
            request("/api/devices", { params: { interface: iface } }),

        captureStatus: () => request("/api/capture/status"),
        startCapture: (iface) =>
            request("/api/capture/start", {
                method: "POST",
                body: { interface: iface },
            }),
        stopCapture: () =>
            request("/api/capture/stop", { method: "POST" }),

        statistics: () => request("/api/statistics/current"),
        statisticsHistory: (params) =>
            request("/api/statistics/history", { params }),
        protocols: () => request("/api/statistics/protocols"),
        topTalkers: (limit) =>
            request("/api/top-talkers", {
                params: { limit: limit || NetScope.config.topTalkerLimit },
            }),

        packets: (params) => request("/api/packets", { params }),
        packet: (id) => request(`/api/packets/${encodeURIComponent(id)}`),
        connections: (params) => request("/api/connections", { params }),
    };
})(window.NetScope = window.NetScope || {});
