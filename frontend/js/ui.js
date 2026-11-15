/*
 * Presentation helpers: formatting, table rendering and empty/error states.
 *
 * Cells are written with textContent only. Nothing coming from the API is
 * interpreted as HTML.
 */
(function (NetScope) {
    "use strict";

    const $ = (id) => document.getElementById(id);

    function isNumber(value) {
        return value !== null && value !== undefined && value !== "" &&
            Number.isFinite(Number(value));
    }

    function formatNumber(value) {
        return isNumber(value) ? Number(value).toLocaleString() : "--";
    }

    function formatBytes(value) {
        if (!isNumber(value)) {
            return "--";
        }

        const units = ["B", "KB", "MB", "GB", "TB", "PB"];
        let size = Number(value);
        let index = 0;

        while (size >= 1024 && index < units.length - 1) {
            size /= 1024;
            index += 1;
        }

        const decimals = index === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;

        return `${size.toFixed(decimals)} ${units[index]}`;
    }

    function formatRate(value) {
        if (!isNumber(value)) {
            return "--";
        }

        return `${formatBytes(value)}/s`;
    }

    function formatPercent(value) {
        return isNumber(value) ? `${Number(value).toFixed(1)}%` : "--";
    }

    function parseDate(value) {
        if (!value) {
            return null;
        }

        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    function formatTime(value) {
        const date = parseDate(value);

        if (!date) {
            return "--";
        }

        return date.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
    }

    function formatDateTime(value) {
        const date = parseDate(value);

        if (!date) {
            return "--";
        }

        return date.toLocaleString([], {
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
    }

    function relativeTime(value) {
        const date = parseDate(value);

        if (!date) {
            return "--";
        }

        const seconds = Math.round((Date.now() - date.getTime()) / 1000);

        if (seconds < 5) {
            return "just now";
        }

        if (seconds < 60) {
            return `${seconds}s ago`;
        }

        if (seconds < 3600) {
            return `${Math.floor(seconds / 60)}m ago`;
        }

        if (seconds < 86400) {
            return `${Math.floor(seconds / 3600)}h ago`;
        }

        return `${Math.floor(seconds / 86400)}d ago`;
    }

    function formatEndpoint(ip, port) {
        if (!ip) {
            return "--";
        }

        return port === null || port === undefined || port === ""
            ? ip
            : `${ip}:${port}`;
    }

    function setText(id, value) {
        const node = $(id);

        if (node) {
            node.textContent = value === undefined || value === null ? "--" : String(value);
        }
    }

    function setHidden(id, hidden) {
        const node = $(id);

        if (node) {
            node.hidden = Boolean(hidden);
        }
    }

    function showError(id, message, errorId) {
        if (!id) {
            return;
        }

        const node = $(id);

        if (!node) {
            return;
        }

        node.textContent = message || "";
        node.hidden = !message;
    }

    function normaliseCell(cell) {
        if (cell && typeof cell === "object") {
            return {
                text: cell.text === undefined || cell.text === null ? "" : String(cell.text),
                className: cell.className || "",
            };
        }

        return {
            text: cell === undefined || cell === null ? "" : String(cell),
            className: "",
        };
    }

    function buildRow(item, cellsFor) {
        const row = document.createElement("tr");

        cellsFor(item).forEach((raw) => {
            const cell = normaliseCell(raw);
            const td = document.createElement("td");
            td.textContent = cell.text;

            if (cell.className) {
                td.className = cell.className;
            }

            row.appendChild(td);
        });

        return row;
    }

    /**
     * Update a tbody. When the row count is unchanged each cell is written in
     * place, which avoids the flicker of rebuilding the table every second.
     */
    function renderRows(tbody, items, cellsFor) {
        if (!tbody) {
            return;
        }

        const rows = items || [];

        if (tbody.rows.length !== rows.length) {
            const fragment = document.createDocumentFragment();

            rows.forEach((item) => fragment.appendChild(buildRow(item, cellsFor)));

            tbody.textContent = "";
            tbody.appendChild(fragment);
            return;
        }

        rows.forEach((item, index) => {
            const row = tbody.rows[index];
            const cells = cellsFor(item);

            while (row.cells.length < cells.length) {
                row.appendChild(document.createElement("td"));
            }

            while (row.cells.length > cells.length) {
                row.removeChild(row.lastElementChild);
            }

            cells.forEach((raw, cellIndex) => {
                const cell = normaliseCell(raw);
                const td = row.cells[cellIndex];

                if (td.textContent !== cell.text) {
                    td.textContent = cell.text;
                }

                if (td.className !== cell.className) {
                    td.className = cell.className;
                }
            });
        });
    }

    function renderCollection(options) {
        const {
            tbodyId,
            items,
            cellsFor,
            emptyId,
            errorId,
        } = options;

        if (errorId) {
            showError(errorId, "");
        }

        renderRows($(tbodyId), items || [], cellsFor);

        if (emptyId) {
            setHidden(emptyId, (items || []).length > 0);
        }
    }

    function renderError(options) {
        const { tbodyId, emptyId, errorId, message } = options;

        renderRows($(tbodyId), [], () => []);
        setHidden(emptyId, true);
        showError(errorId, message);
    }

    function pageInfo(total, offset, limit) {
        const safeTotal = isNumber(total) ? Number(total) : 0;
        const safeLimit = isNumber(limit) ? Number(limit) : 1;
        const pages = Math.max(1, Math.ceil(safeTotal / safeLimit));
        const page = Math.floor(offset / safeLimit) + 1;
        const from = safeTotal === 0 ? 0 : offset + 1;
        const to = Math.min(offset + safeLimit, safeTotal);

        return { total: safeTotal, pages, page, from, to };
    }

    function protocolCell(name) {
        return { text: name || "--", className: `proto proto-${slug(name)}` };
    }

    function directionCell(value) {
        return { text: value || "--", className: `direction direction-${slug(value)}` };
    }

    function stateCell(value) {
        return { text: value || "--", className: `state state-${slug(value)}` };
    }

    function slug(value) {
        return String(value || "other")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-|-$/g, "") || "other";
    }

    function debounce(fn, delay) {
        let timer = null;

        return function debounced(...args) {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => fn.apply(this, args), delay);
        };
    }

    NetScope.ui = {
        $,
        isNumber,
        formatNumber,
        formatBytes,
        formatRate,
        formatPercent,
        formatTime,
        formatDateTime,
        relativeTime,
        formatEndpoint,
        setText,
        setHidden,
        showError,
        renderRows,
        renderCollection,
        renderError,
        pageInfo,
        protocolCell,
        directionCell,
        stateCell,
        debounce,
    };
})(window.NetScope = window.NetScope || {});
