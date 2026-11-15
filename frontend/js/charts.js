/*
 * Chart.js wrappers.
 *
 * Instances are created exactly once. Every later update mutates the existing
 * chart data and calls update("none"), so charts never flicker or leak.
 * If Chart.js failed to load the rest of the dashboard still works.
 */
(function (NetScope) {
    "use strict";

    const palette = [
        "#38bdf8", "#22c55e", "#f59e0b", "#a855f7",
        "#ef4444", "#14b8a6", "#f472b6", "#84cc16",
        "#64748b",
    ];

    const state = {
        trafficCharts: [],
        protocolChart: null,
        historyChart: null,
        labels: [],
        upload: [],
        download: [],
    };

    function available() {
        return typeof window.Chart !== "undefined";
    }

    function baseOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { intersect: false, mode: "index" },
            plugins: {
                legend: {
                    labels: {
                        color: "#9fb0c7",
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                    },
                },
                tooltip: {
                    backgroundColor: "#0f1b2d",
                    borderColor: "#2a3b55",
                    borderWidth: 1,
                    titleColor: "#e7edf7",
                    bodyColor: "#c7d4e6",
                },
            },
            scales: {
                x: {
                    ticks: { color: "#71849e", maxTicksLimit: 6 },
                    grid: { color: "rgba(255,255,255,.04)" },
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: "#71849e" },
                    grid: { color: "rgba(255,255,255,.06)" },
                },
            },
        };
    }

    function createTrafficChart(canvas) {
        return new window.Chart(canvas, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Download",
                        data: [],
                        borderColor: "#38bdf8",
                        backgroundColor: "rgba(56,189,248,.15)",
                        fill: true,
                        tension: 0.35,
                        pointRadius: 0,
                        borderWidth: 2,
                    },
                    {
                        label: "Upload",
                        data: [],
                        borderColor: "#22c55e",
                        backgroundColor: "rgba(34,197,94,.12)",
                        fill: true,
                        tension: 0.35,
                        pointRadius: 0,
                        borderWidth: 2,
                    },
                ],
            },
            options: baseOptions(),
        });
    }

    function init() {
        if (!available()) {
            return false;
        }

        ["trafficChart", "trafficChartLarge"].forEach((id) => {
            const canvas = document.getElementById(id);

            if (canvas) {
                state.trafficCharts.push(createTrafficChart(canvas));
            }
        });

        const protocolCanvas = document.getElementById("protocolChart");

        if (protocolCanvas) {
            state.protocolChart = new window.Chart(protocolCanvas, {
                type: "doughnut",
                data: {
                    labels: [],
                    datasets: [
                        {
                            data: [],
                            backgroundColor: palette,
                            borderColor: "#111c30",
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    cutout: "62%",
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: {
                                color: "#9fb0c7",
                                boxWidth: 10,
                                boxHeight: 10,
                                usePointStyle: true,
                            },
                        },
                    },
                },
            });
        }

        const historyCanvas = document.getElementById("historyChart");

        if (historyCanvas) {
            state.historyChart = new window.Chart(historyCanvas, {
                type: "line",
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: "Total packets",
                            data: [],
                            borderColor: "#a855f7",
                            backgroundColor: "rgba(168,85,247,.15)",
                            fill: true,
                            tension: 0.3,
                            pointRadius: 0,
                            borderWidth: 2,
                        },
                    ],
                },
                options: baseOptions(),
            });
        }

        return true;
    }

    function pushTraffic(label, uploadBytesPerSecond, downloadBytesPerSecond) {
        const max = NetScope.config.chartPoints;

        state.labels.push(label);
        state.upload.push(Number(uploadBytesPerSecond) || 0);
        state.download.push(Number(downloadBytesPerSecond) || 0);

        if (state.labels.length > max) {
            state.labels.shift();
            state.upload.shift();
            state.download.shift();
        }

        state.trafficCharts.forEach((chart) => {
            chart.data.labels = state.labels.slice();
            chart.data.datasets[0].data = state.download.slice();
            chart.data.datasets[1].data = state.upload.slice();
            chart.update("none");
        });
    }

    function resetTraffic() {
        state.labels.length = 0;
        state.upload.length = 0;
        state.download.length = 0;

        state.trafficCharts.forEach((chart) => {
            chart.data.labels = [];
            chart.data.datasets[0].data = [];
            chart.data.datasets[1].data = [];
            chart.update("none");
        });
    }

    function updateProtocol(counts) {
        if (!state.protocolChart) {
            return;
        }

        const entries = Object.entries(counts || {})
            .filter(([, value]) => Number(value) > 0)
            .sort((a, b) => Number(b[1]) - Number(a[1]));

        if (entries.length === 0) {
            state.protocolChart.data.labels = [];
            state.protocolChart.data.datasets[0].data = [];
            state.protocolChart.update("none");
            return;
        }

        const top = entries.slice(0, 8);
        const rest = entries.slice(8);

        if (rest.length > 0) {
            top.push([
                "Other",
                rest.reduce((sum, [, value]) => sum + Number(value), 0),
            ]);
        }

        state.protocolChart.data.labels = top.map(([name]) => name);
        state.protocolChart.data.datasets[0].data = top.map(([, value]) =>
            Number(value)
        );
        state.protocolChart.update("none");
    }

    function updateHistory(snapshots) {
        if (!state.historyChart) {
            return;
        }

        const ordered = (snapshots || []).slice().reverse();

        state.historyChart.data.labels = ordered.map((snapshot) =>
            NetScope.ui.formatTime(snapshot.timestamp)
        );
        state.historyChart.data.datasets[0].data = ordered.map((snapshot) =>
            Number(snapshot.total_packets) || 0
        );
        state.historyChart.update("none");
    }

    function destroy() {
        state.trafficCharts.forEach((chart) => chart.destroy());
        state.trafficCharts = [];

        if (state.protocolChart) {
            state.protocolChart.destroy();
            state.protocolChart = null;
        }

        if (state.historyChart) {
            state.historyChart.destroy();
            state.historyChart = null;
        }
    }

    NetScope.charts = {
        available,
        init,
        pushTraffic,
        resetTraffic,
        updateProtocol,
        updateHistory,
        destroy,
    };
})(window.NetScope = window.NetScope || {});
