// Dashboard Application Logic

// ---------------------------------------------------------
// GLOBAL STORE (Single Source of Truth)
// ---------------------------------------------------------
window.EventStore = {
    events: [],       // All events (Logs/Analytics)
    systemStatus: {   // Detection Status
        child_in_roi: false,
        warning_on: false,
        confidence: 0.0,
        roi_status: 'OUTSIDE',
        latency_ms: 0,
        last_update_str: '---',
        connection_status: 'Connecting...',
        // Warning logic helpers
        switch_enabled: true
    },
    latestPayload: null,      // RAW Contract Payload (from Backend/Socket)
    contractValidation: null, // Validation Result
    powerStatus: {    // Power System (hardware pending)
        solar_status: 'N/A',
        battery_percent: 0,
        led_driver: 'N/A'
    },
    // DB Mode Store
    logsRows: [],           // Paginated DB results for Logs page
    dbTotal: 0,             // Total matching DB rows (Logs)
    analyticsAggregate: null, // /api/analytics response for Analytics page
    reportAggregate: null,    // /api/analytics response for Reports page
    // Legacy (kept for backward compat, not used by Analytics/Reports anymore)
    analyticsRows: [],
    analyticsTotal: 0,
    reportRows: [],
    reportTotal: 0
}
    ;

// ---------------------------------------------------------
// CAMERA CONTROLLER (Global Persistence)
// ---------------------------------------------------------
window.CameraController = {
    stream: null,
    isOn: false,
    selectedDeviceId: localStorage.getItem('camDeviceId') || null,
    lastError: null
};

const App = {
    // ---------------------------------------------------------
    // 1. Central State
    // ---------------------------------------------------------
    // ---------------------------------------------------------
    // 1. Central State
    // ---------------------------------------------------------
    state: {
        // App Flags
        isConnected: false,
        lastSocketUpdate: 0,

        // System Configuration
        theme: localStorage.getItem('theme') || 'light',
        roi: JSON.parse(localStorage.getItem('roi_settings')) || { x: 50, y: 50, w: 100, h: 100 },

        // Helper for DB Timestamps
        parseTimestamp(isoStr) {
            if (!isoStr) return null;
            // Fix MySQL strings "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DDTHH:MM:SSZ"
            let s = isoStr.toString();
            if (s.includes(' ') && !s.includes('T')) s = s.replace(' ', 'T');
            if (s.length === 19) s += 'Z'; // e.g. 2023-01-01T12:00:00 -> ...Z
            else if (!s.endsWith('Z') && !s.includes('+') && !s.includes('-')) s += 'Z'; // simplistic UTC assumption

            const d = new Date(s);
            return isNaN(d.getTime()) ? null : d;
        },

        // Logs Page Filter State
        logsPollingTimer: null,
        logsDbError: false,
        logsFilter: {
            range: 'today',
            searchText: '',
            warningOnly: false,
            inRoiOnly: false,
            minConf: 0.00,
            scenario: 'All',
            currentPage: 1,
            pageSize: 25,
            totalPages: 1
        },



        camera: { stream: null, selectedId: null },
        charts: {},
        analytics: {
            range: 'today',
            lastUpdate: 0
        },
        reports: {
            range: 'today',
            lastSummary: null
        }
    },

    // ---------------------------------------------------------
    // 2. Initialization
    // ---------------------------------------------------------
    init() {
        this.initTheme();
        this.setupNavigation();
        this.setupSocket();
        this.setupTick(); // 1s tick for UI refresh and polling (no mock data)
        this.setupAnalytics();

        // Init Logs Controls
        this.setupLogEvents();
        this.renderLogsTable(); // Initial render

        // Init Reports
        this.setupReports();

        this.setupROI();
        this.initCamera();
        this.updateUI(); // Initial render

        // Sidebar Init
        this.initSidebar();

        // Initial Load for Logs if starting there
        if (window.location.hash === '#logs') {
            this.loadLogsFromDB();
        }
    },

    setupTick() {
        // Main System Tick (1Hz) — UI refresh and auto-polling only. No mock data.
        setInterval(() => {
            const now = Date.now();

            // Always update UI on tick
            this.updateUI();

            // Auto-refresh Logs if on logs page
            if (window.location.hash === '#logs') {
                this.renderLogsTable(true);
            }

            // Analytics Live Update (every 2s)
            if (window.location.hash === '#analytics') {
                if (now - this.state.analytics.lastUpdate > 2000) {
                    this.state.analytics.lastUpdate = now;
                }
            }

        }, 1000);
    },

    // ---------------------------------------------------------
    // 4. Data Management & Socket
    // ---------------------------------------------------------
    setupSocket() {
        if (this.socket) return; // Prevent duplicate listeners

        try {
            this.socket = io();
            this.socket.on('connect', () => {
                this.state.isConnected = true;
                this.updateConnectionStatus();
            });
            this.socket.on('disconnect', () => {
                this.state.isConnected = false;
                this.updateConnectionStatus();

                // Fallback for Contract Preview
                const badge = document.getElementById('contract-valid-badge');
                if (badge) {
                    badge.textContent = "Disconnected";
                    badge.className = "status-chip mock";
                }
            });
            this.socket.on('status_update', (data) => {
                this.handleSocketData(data);
            });
            this.socket.on('roi_updated', (msg) => {
                this.handleRoiUpdated(msg);
            });
        } catch (e) {
            console.log("Socket.IO not initialized (Mock Mode only).");
        }
    },

    handleRoiUpdated(msg) {
        const roi = msg?.roi;
        if (!roi) return;

        // 1) Update the ROI Active badge on Live View immediately
        const b = document.getElementById('liveRoiBadge');
        if (b) {
            b.style.display = 'block';
            b.innerHTML = `<i class="fa-solid fa-crosshairs"></i> ROI Active: (${Math.round(roi.x1)}, ${Math.round(roi.y1)}) to (${Math.round(roi.x2)}, ${Math.round(roi.y2)})`;
        }

        // 2) Restart the MJPEG camera stream so the server-side overlay uses the new ROI
        const img = document.getElementById('liveCam');
        if (img && img.src && img.src.includes('/video_feed')) {
            const base = img.src.split('?')[0];
            const params = new URL(img.src, window.location.origin).searchParams;
            params.set('t', Date.now());
            img.src = `${base}?${params.toString()}`;
        }

        console.log('[ROI] Live View updated via socket:', roi);
    },

    handleSocketData(data) {
        // 1. Always process Contract Preview (DEV TOOL) - Updates 'Settings' page
        try {
            // Normalize & Validate
            const payload = DataContract.normalizeStatusUpdate(data);
            const validation = DataContract.validateStatusUpdate(payload);

            // Store for Preview
            window.EventStore.latestPayload = payload;
            window.EventStore.contractValidation = validation;

            // Update UI if on Settings page
            this.updateContractPreview();
        } catch (e) {
            console.error("Contract Preview Error:", e);
        }

        // 2. Always update live status from socket data (no mock gating)
        this.state.isConnected = true;
        this.state.lastSocketUpdate = Date.now();

        const status = window.EventStore.systemStatus;

        status.child_in_roi = data.child_in_roi;
        status.warning_on = data.warning_device_on ?? data.warning_on;
        status.confidence = data.confidence;
        status.roi_status = data.child_in_roi ? 'INSIDE' : 'OUTSIDE';
        status.latency_ms = data.latency_ms || data.latency || 0;
        status.last_update_str = new Date().toLocaleTimeString();

        if (data.source === "yolo") {
            status.connection_status = "Live (YOLO)";
        } else if (data.source === "idle") {
            status.connection_status = "Connected (Camera OFF)";
        } else {
            status.connection_status = "Connected";
        }

        // Update connection chip
        const connChip = document.getElementById('connection-chip');
        if (connChip) {
            connChip.innerHTML = `<div class="status-indicator"></div> ${status.connection_status}`;
            connChip.className = `status-chip connected`;
        }

        this.logEvent(status, data.scenario || "Live Feed");
        this.updateUI();
    },

    updateContractPreview() {
        const previewBox = document.getElementById('contract-json-preview');
        const validBadge = document.getElementById('contract-valid-badge');
        const errorList = document.getElementById('contract-errors-list');

        // Null-safe check: only update if elements exist (User is on Settings page)
        if (!previewBox || !validBadge) return;

        const payload = window.EventStore.latestPayload;
        const validation = window.EventStore.contractValidation;

        if (!payload) {
            previewBox.textContent = "Waiting for data...";
            validBadge.className = "status-chip mock";
            validBadge.textContent = "Waiting...";
            return;
        }

        // Update JSON
        previewBox.textContent = JSON.stringify(payload, null, 2);

        // Update Badge
        if (validation && validation.ok) {
            validBadge.className = "status-chip connected";
            validBadge.textContent = "VALID";
            validBadge.style.backgroundColor = "";
            if (errorList) errorList.innerHTML = "";
        } else {
            validBadge.className = "status-chip";
            validBadge.textContent = "INVALID";
            validBadge.style.backgroundColor = "#d32f2f";
            validBadge.style.color = "white";

            if (errorList && validation) {
                errorList.innerHTML = validation.errors.map(e => `<li>${e}</li>`).join('');
            }
        }
    },

    logEvent(status, scenario) {
        // Ensure ISO timestamp for persistent sorting
        const now = new Date();
        const event = {
            id: Date.now(),
            rawTimestamp: Date.now(),
            timestamp: now.toLocaleTimeString(),
            timestamp_iso: now.toISOString(), // Critical for Analytics
            message: status.child_in_roi ? 'Child-class Detected' : 'No Detection',
            child_in_roi: status.child_in_roi,
            warning_on: status.warning_on,
            confidence: status.confidence,
            roi_status: status.roi_status,
            latency_ms: status.latency_ms,
            scenario: scenario,
            false_warning: status.warning_on && !status.child_in_roi
        };

        window.EventStore.events.unshift(event);
        if (window.EventStore.events.length > 1000) window.EventStore.events.pop();
    },

    updateUI() {
        const status = window.EventStore.systemStatus;

        // Topbar connection chip
        const connChip = document.getElementById('connection-chip');
        if (connChip) {
            connChip.innerHTML = `<div class="status-indicator"></div> ${status.connection_status}`;
            connChip.className = `status-chip ${this.state.isConnected ? 'connected' : 'mock'}`;
        }
        document.getElementById('last-update').textContent = `Last Update: ${status.last_update_str}`;

        // Live View Cards
        document.getElementById('live-child').textContent = status.child_in_roi ? 'YES' : 'NO';
        document.getElementById('live-warning').textContent = status.warning_on ? 'ON' : 'OFF';

        document.getElementById('live-child').style.color = status.child_in_roi ? '#d32f2f' : 'inherit';
        document.getElementById('live-warning').style.color = status.warning_on ? '#d32f2f' : '#2e7d32';

        document.getElementById('live-conf').textContent = status.confidence.toFixed(2);
        document.getElementById('live-roi').textContent = status.roi_status;
        document.getElementById('live-roi').className = `card-value ${status.roi_status === 'INSIDE' ? 'text-danger' : ''}`;

        document.getElementById('live-latency').textContent = status.latency_ms + 'ms';

        // Power System — N/A (hardware pending)
        const solarEl = document.getElementById('power-solar-status');
        if (solarEl) solarEl.textContent = 'N/A — Hardware pending';
        const battBar = document.getElementById('power-battery-bar');
        if (battBar) battBar.style.width = '0%';
        const battText = document.getElementById('power-battery-text');
        if (battText) battText.textContent = 'N/A';

        this.renderLiveFeed();
    },

    renderLiveFeed() {
        const feed = document.getElementById('event-feed');
        if (!feed) return;
        const recent = window.EventStore.events.slice(0, 10);
        feed.innerHTML = recent.map(e => `
            <div class="feed-item">
                <span class="text-muted" style="font-size:0.8rem;">${e.timestamp}</span>
                <strong>${e.message}</strong>
                <div class="feed-meta">Conf: ${e.confidence.toFixed(2)} | Latency: ${e.latency_ms}ms</div>
            </div>
        `).join('');
    },

    // ---------------------------------------------------------
    // 6. Logs Logic: Sorting, Filtering, Pagination
    // ---------------------------------------------------------

    async loadLogsFromDB() {

        const f = this.state.logsFilter;
        // Build Query Params
        const params = new URLSearchParams({
            limit: f.pageSize,
            offset: (f.currentPage - 1) * f.pageSize,
            range: f.range
        });

        if (f.warningOnly) params.append('warning_only', 'true');
        if (f.inRoiOnly) params.append('in_roi_only', 'true');
        if (f.minConf > 0) params.append('min_conf', f.minConf);
        if (f.scenario !== 'All') params.append('scenario', f.scenario);
        if (f.searchText) params.append('search', f.searchText);

        // UI Loading State (optional but good)
        const tbody = document.getElementById('logsTableBody');
        if (tbody && f.currentPage === 1 && !this.state.logsPollingTimer) {
            // Only show explicit loading on first load or manual filter change, not every poll
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px; color:#888;"><i class="fa-solid fa-spinner fa-spin"></i> Loading DB logs...</td></tr>';
        }

        try {
            const res = await fetch(`/api/events?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();

                // Mismatch Guard
                if (data.total > 0 && (!data.rows || data.rows.length === 0)) {
                    console.error("DATA MISMATCH: Backend reports total > 0 but returned no rows.", data);
                    // Fallback to empty to avoid render errors
                    window.EventStore.logsRows = [];
                    window.EventStore.dbTotal = 0;
                } else {
                    window.EventStore.logsRows = data.rows; // Backend sends "rows"
                    window.EventStore.dbTotal = data.total;

                    // Debug Logs
                    console.debug(`[DB-LOGS] Fetched ${data.rows.length} rows (Total: ${data.total})`);
                    if (data.rows.length > 0) console.debug("[DB-LOGS] Sample:", data.rows[0]);
                }

                this.state.logsDbError = false;
                this.renderLogsTable();
            } else {
                throw new Error("DB Fetch Failed");
            }
        } catch (e) {
            console.warn("Logs fetch error:", e);
            this.state.logsDbError = true;
            window.EventStore.logsRows = [];
            window.EventStore.dbTotal = 0;
            this.renderLogsTable(); // Shows empty state + warning banner
        }
    },

    async loadAnalyticsFromDB(range) {
        // Calls /api/analytics which computes ALL KPIs server-side — never limited by page size.
        try {
            const res = await fetch(`/api/analytics?range=${encodeURIComponent(range)}`);
            if (res.ok) {
                const data = await res.json();
                window.EventStore.analyticsAggregate = data;
                console.debug(
                    `[Analytics] range=${data.range} | events=${data.total_events}` +
                    ` | warnings=${data.total_warnings} | window=${data.range_start} → ${data.range_end}`
                );
                this.toggleAnalyticsWarning(false);
                return true;
            }
            throw new Error(`HTTP ${res.status}`);
        } catch (e) {
            console.warn("Analytics fetch error:", e);
            this.toggleAnalyticsWarning(true);
            return false;
        }
    },

    toggleAnalyticsWarning(show) {
        const anaWarn = document.getElementById('anaDbWarning');
        if (anaWarn) anaWarn.style.display = show ? 'block' : 'none';
    },

    // ---------------------------------------------------------
    // DB Fetch for Reports (dedicated store — never overwrites analyticsRows)
    // ---------------------------------------------------------
    async loadReportFromDB(range) {
        // Calls /api/analytics — same endpoint as Analytics, dedicated store so they never overwrite each other.
        try {
            const res = await fetch(`/api/analytics?range=${encodeURIComponent(range)}`);
            if (res.ok) {
                const data = await res.json();
                window.EventStore.reportAggregate = data;
                console.debug(
                    `[Report] range=${data.range} | events=${data.total_events}` +
                    ` | warnings=${data.total_warnings} | window=${data.range_start} → ${data.range_end}`
                );
                this.toggleReportWarning(false);
                return true;
            }
            throw new Error(`HTTP ${res.status}`);
        } catch (e) {
            console.warn('[DB-REPORT] Fetch error:', e);
            this.toggleReportWarning(true);
            return false;
        }
    },

    toggleReportWarning(show) {
        const el = document.getElementById('repDbWarning');
        if (el) {
            el.style.display = show ? 'block' : 'none';
            if (show) {
                el.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> DB unavailable — no data available.';
            }
        }
    },

    setupLogEvents() {
        const filters = this.state.logsFilter;

        // Search
        const searchInput = document.getElementById('logsSearch');
        if (searchInput) {
            let debounceTimer;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    filters.searchText = e.target.value;
                    filters.currentPage = 1;
                    this.loadLogsFromDB();
                }, 250);
            });
        }

        // Date Presets
        document.querySelectorAll('.btn-preset').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // Update UI classes
                document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                // Update State
                filters.range = e.target.getAttribute('data-range');
                filters.currentPage = 1;
                this.loadLogsFromDB();
            });
        });

        // Toggles
        document.getElementById('filterWarningOn')?.addEventListener('change', (e) => {
            filters.warningOnly = e.target.checked;
            filters.currentPage = 1;
        });

        document.getElementById('filterInRoi')?.addEventListener('change', (e) => {
            filters.inRoiOnly = e.target.checked;
        });

        document.getElementById('filterScenario')?.addEventListener('change', (e) => {
            filters.scenario = e.target.value;
        });

        // Slider
        const slider = document.getElementById('filterMinConf');
        const label = document.getElementById('filterMinConfLabel');
        if (slider && label) {
            slider.addEventListener('input', (e) => {
                label.textContent = parseFloat(e.target.value).toFixed(2);
                filters.minConf = parseFloat(e.target.value);
            });
            slider.addEventListener('change', () => {
                this.loadLogsFromDB();
            });
        }

        // Buttons
        document.getElementById('btnApplyLogsFilters')?.addEventListener('click', () => {
            filters.currentPage = 1;
            this.loadLogsFromDB();
        });

        document.getElementById('btnResetLogsFilters')?.addEventListener('click', () => {
            // Reset State
            filters.range = 'today';
            filters.searchText = '';
            filters.warningOnly = false;
            filters.inRoiOnly = false;
            filters.minConf = 0.00;
            filters.scenario = 'All';
            filters.currentPage = 1;

            // Reset UI Controls
            document.querySelectorAll('.btn-preset').forEach(b => b.classList.toggle('active', b.getAttribute('data-range') === 'today'));
            if (searchInput) searchInput.value = '';
            const chkWarn = document.getElementById('filterWarningOn'); if (chkWarn) chkWarn.checked = false;
            const chkRoi = document.getElementById('filterInRoi'); if (chkRoi) chkRoi.checked = false;
            const rangeMin = document.getElementById('filterMinConf'); if (rangeMin) rangeMin.value = 0;
            const labelMin = document.getElementById('filterMinConfLabel'); if (labelMin) labelMin.textContent = "0.00";
            const selScen = document.getElementById('filterScenario'); if (selScen) selScen.value = 'All';

            this.loadLogsFromDB();
        });

        // Pagination
        document.getElementById('pageSizeSelect')?.addEventListener('change', (e) => {
            filters.pageSize = parseInt(e.target.value);
            filters.currentPage = 1;
            this.loadLogsFromDB();
        });

        document.getElementById('pagePrev')?.addEventListener('click', () => {
            if (filters.currentPage > 1) {
                filters.currentPage--;
                this.loadLogsFromDB();
            }
        });

        document.getElementById('pageNext')?.addEventListener('click', () => {
            if (filters.currentPage < filters.totalPages) {
                filters.currentPage++;
                this.loadLogsFromDB();
            }
        });

        // Exports
        document.getElementById('btnExportCSV')?.addEventListener('click', () => this.exportCSV());
        document.getElementById('btnExportJSON')?.addEventListener('click', () => this.exportJSON());
    },

    getFilteredLogs() {
        const filters = this.state.logsFilter;
        const now = Date.now();

        // 1. Time Range
        let startTime = 0;
        if (filters.range === '15m') startTime = now - (15 * 60 * 1000);
        else if (filters.range === '1h') startTime = now - (60 * 60 * 1000);
        else if (filters.range === 'today') {
            const t = new Date(); t.setHours(0, 0, 0, 0);
            startTime = t.getTime();
        }
        else if (filters.range === 'all') startTime = 0;

        return window.EventStore.events.filter(log => {
            // Date Check
            // Note: log.rawTimestamp is needed. If existing logs don't have it, we use mock default.
            // But we just added rawTimestamp to logEvent. For old logs in session they might miss it.
            // Fallback: assume old logs match if no rawTimestamp (or clear them).
            const ts = log.rawTimestamp || log.id;
            if (ts < startTime) return false;

            // Flags
            if (filters.warningOnly && !log.warning_on) return false;
            if (filters.inRoiOnly && !log.child_in_roi) return false;
            if (log.confidence < filters.minConf) return false;

            // Scenario
            if (filters.scenario !== 'All' && log.scenario !== filters.scenario) return false;

            // Search
            if (filters.searchText) {
                const lower = filters.searchText.toLowerCase();
                const matchConf = (log.confidence || 0).toFixed(2).includes(lower);
                const matchMsg = (log.message || '').toLowerCase().includes(lower);
                const matchScen = (log.scenario || '').toLowerCase().includes(lower);
                const matchTs = (log.timestamp || '').toLowerCase().includes(lower);

                if (!matchMsg && !matchScen && !matchTs && !matchConf) return false;
            }

            return true;
        }); // logs are already sorted new->old
    },

    renderLogsTable(isAutoRefresh = false) {
        const tbody = document.getElementById('logsTableBody');
        const warningEl = document.getElementById('logsDbWarning');
        if (!tbody) return;

        // Always use DB source
        const displayLogs = window.EventStore.logsRows || [];
        const total = window.EventStore.dbTotal || 0;
        const f = this.state.logsFilter;

        // Show warning banner only on DB error
        if (warningEl) warningEl.style.display = this.state.logsDbError ? 'block' : 'none';

        // Recalc pagination from DB total
        f.totalPages = Math.ceil(total / f.pageSize) || 1;
        if (f.currentPage > f.totalPages) f.currentPage = f.totalPages;
        if (f.currentPage < 1) f.currentPage = 1;

        // Render Rows
        if (displayLogs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px; color:#888;">No logs found.</td></tr>';
        } else {
            tbody.innerHTML = displayLogs.map(log => {
                // Always parse timestamp from ISO (DB source)
                let timeStr;
                const d = this.state.parseTimestamp(log.timestamp_iso);
                if (d) timeStr = d.toLocaleTimeString();
                else timeStr = log.timestamp_iso || log.timestamp || 'Unknown';

                return `
                <tr>
                    <td>${timeStr}</td>
                    <td><span class="badge ${log.child_in_roi ? 'badge-warning' : 'badge-neutral'}">${log.child_in_roi ? 'YES' : 'NO'}</span></td>
                    <td><span style="font-size:0.85em; color:${log.roi_status === 'INSIDE' ? '#d32f2f' : '#999'}">${log.roi_status}</span></td>
                    <td><span class="badge ${this.isOn(log.warning_device_on ?? log.warning_on) ? 'badge-warning' : 'badge-success'}">${this.isOn(log.warning_device_on ?? log.warning_on) ? 'ON' : 'OFF'}</span></td>
                    <td>${(log.confidence || 0).toFixed(2)}</td>
                    <td>${log.latency_ms}ms</td>
                    <td>${log.scenario}</td>
                    <td>${log.false_warning ? '<span style="color:red">YES</span>' : 'NO'}</td>
                </tr>
            `}).join('');
        }

        // Pagination info
        const startIdx = (f.currentPage - 1) * f.pageSize;
        const currentCount = displayLogs.length;
        let rangeText = '';
        if (total === 0) {
            rangeText = 'Showing 0 of 0 events';
        } else {
            rangeText = `Showing ${startIdx + 1}–${startIdx + currentCount} of ${total} persistent events`;
        }

        document.getElementById('resultCount').textContent = rangeText;
        document.getElementById('pageIndicator').textContent = `Page ${f.currentPage} of ${f.totalPages}`;
        document.getElementById('pagePrev').disabled = (f.currentPage <= 1);
        document.getElementById('pageNext').disabled = (f.currentPage >= f.totalPages);
    },

    exportCSV() {
        // Export from DB dataset (logsRows)
        const data = window.EventStore.logsRows || [];
        const headers = ["Timestamp,Message,In ROI,Warning,Confidence,Latency,Scenario,False Warning\n"];
        const rows = data.map(log => {
            const d = this.state.parseTimestamp(log.timestamp_iso);
            const ts = d ? d.toLocaleString() : (log.timestamp_iso || log.timestamp || '');
            const msg = log.child_in_roi ? 'Child-class Detected' : 'No Detection';
            return `${ts},${msg},${log.child_in_roi},${log.warning_on},${(log.confidence || 0).toFixed(2)},${log.latency_ms},${log.scenario},${log.false_warning}`;
        });
        this.downloadFile(headers.concat(rows).join("\n"), 'csv');
    },

    exportJSON() {
        // Export from DB dataset (logsRows)
        const data = window.EventStore.logsRows || [];
        const jsonStr = JSON.stringify(data, null, 2);
        this.downloadFile(jsonStr, 'json');
    },

    downloadFile(content, type) {
        const f = this.state.logsFilter;
        // Filename with date and range
        const dateStr = new Date().toISOString().slice(0, 10);
        const filename = `logs_${dateStr}_${f.range}.${type}`;

        const blob = new Blob([content], { type: type === 'csv' ? 'text/csv;charset=utf-8;' : 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    },


    // ---------------------------------------------------------
    // 7. Navigation & Setup
    // ---------------------------------------------------------
    initSidebar() {
        this.sidebarBtn = document.getElementById('btnHamburger');
        this.sidebar = document.querySelector('.sidebar');
        this.backdrop = document.getElementById('sidebarBackdrop');
        this.body = document.body;

        if (!this.sidebarBtn || !this.sidebar) return;

        // Load Desktop State
        const savedCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
        if (savedCollapsed) {
            this.body.classList.add('sidebar-collapsed');
        }

        // Listeners
        this.sidebarBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleSidebar();
        });

        if (this.backdrop) {
            this.backdrop.addEventListener('click', () => this.closeMobileSidebar());
        }

        // Close on Nav Item (Mobile)
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                if (window.innerWidth < 992) this.closeMobileSidebar();
            });
        });

        // Close on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.closeMobileSidebar();
        });

        // Resize Handling
        window.addEventListener('resize', () => {
            if (window.innerWidth >= 992) {
                this.body.classList.remove('sidebar-open');
            }
        });
    },

    toggleSidebar() {
        const isMobile = window.innerWidth < 992;

        if (isMobile) {
            const isOpen = this.body.classList.contains('sidebar-open');
            if (isOpen) this.closeMobileSidebar();
            else {
                this.body.classList.add('sidebar-open');
                this.sidebarBtn.setAttribute('aria-expanded', 'true');
            }
        } else {
            const isCollapsed = this.body.classList.contains('sidebar-collapsed');
            if (isCollapsed) {
                this.body.classList.remove('sidebar-collapsed');
                localStorage.setItem('sidebarCollapsed', 'false');
                this.sidebarBtn.setAttribute('aria-expanded', 'true');
            } else {
                this.body.classList.add('sidebar-collapsed');
                localStorage.setItem('sidebarCollapsed', 'true');
                this.sidebarBtn.setAttribute('aria-expanded', 'false');
            }
        }
    },

    closeMobileSidebar() {
        this.body.classList.remove('sidebar-open');
        this.sidebarBtn.setAttribute('aria-expanded', 'false');
    },

    setupNavigation() {
        const handleHashChange = () => {
            const hash = window.location.hash.slice(1) || 'live';
            this.state.currentSection = hash;
            document.querySelectorAll('.nav-item').forEach(el => {
                el.classList.toggle('active', el.getAttribute('href') === `#${hash}`);
            });
            document.querySelectorAll('.page-section').forEach(el => {
                el.classList.toggle('active', el.id === `${hash}-section`);
            });

            // Logs Polling Logic — always fetch from DB
            if (hash === 'logs') {
                this.loadLogsFromDB();
                // Start Polling (10s)
                if (this.state.logsPollingTimer) clearInterval(this.state.logsPollingTimer);
                this.state.logsPollingTimer = setInterval(() => this.loadLogsFromDB(), 10000);
            } else {
                // Leaving Logs
                if (this.state.logsPollingTimer) {
                    clearInterval(this.state.logsPollingTimer);
                    this.state.logsPollingTimer = null;
                }
            }

            if (hash === 'analytics') {
                if (this.state.charts.warnings) this.state.charts.warnings.resize();

                // Clear any old poll
                if (this.state.analyticsPollingTimer) {
                    clearInterval(this.state.analyticsPollingTimer);
                    this.state.analyticsPollingTimer = null;
                }

                // Always fetch from DB, then update UI
                this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());

                // Start Polling (30s)
                this.state.analyticsPollingTimer = setInterval(() => {
                    this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());
                }, 30000);
            } else {
                // Leaving Analytics
                if (this.state.analyticsPollingTimer) {
                    clearInterval(this.state.analyticsPollingTimer);
                    this.state.analyticsPollingTimer = null;
                }
            }

            // Camera Persistence Logic
            if (hash === 'live') {
                // Return to Live View: Verify & Re-attach
                const cam = window.CameraController;
                // Check if we have an active stream logic
                if (cam.isOn && cam.stream) {
                    // Double check stream effectively
                    if (cam.stream.active || (cam.stream.getTracks().length > 0 && cam.stream.getTracks()[0].readyState === 'live')) {
                        console.log("Restoring active camera stream...");
                        this.attachStreamToVideo(cam.stream);
                    } else {
                        console.warn("Stream inactive on return. stopping.");
                        this.stopCamera();
                    }
                }
            } else {
                // Navigate away: Camera stays ON (tracks active).
                // UI is hidden by CSS. We do nothing here to stop it.
            }
        };
        window.addEventListener('hashchange', handleHashChange);
        handleHashChange();
    },

    setupAnalytics() {
        // 1. Chart Init
        // Common Chart Options
        // 1. Chart Init
        const isDark = this.state.theme === 'dark';
        const gridColor = isDark ? '#333333' : '#f0f0f0';
        const textColor = isDark ? '#a0a0a0' : '#666';

        // Common Chart Options
        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 800 },
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: textColor }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: gridColor },
                    ticks: { color: textColor }
                }
            }
        };

        // A) Warnings (Line/Bar)
        const ctxW = document.getElementById('chartWarnings')?.getContext('2d');
        if (ctxW) {
            this.state.charts.warnings = new Chart(ctxW, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Warnings',
                        data: [],
                        backgroundColor: '#FF2400',
                        borderRadius: 4
                    }]
                },
                options: commonOptions
            });
        }

        // B) Detections (Line)
        const ctxD = document.getElementById('chartDetections')?.getContext('2d');
        if (ctxD) {
            this.state.charts.detections = new Chart(ctxD, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Detections',
                        data: [],
                        borderColor: '#FF9280',
                        backgroundColor: 'rgba(255, 146, 128, 0.2)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 2
                    }]
                },
                options: commonOptions
            });
        }

        // C) Confidence (Histogram Bar)
        const ctxC = document.getElementById('chartConfidence')?.getContext('2d');
        if (ctxC) {
            this.state.charts.confidence = new Chart(ctxC, {
                type: 'bar',
                data: {
                    labels: ['0.0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0'],
                    datasets: [{
                        label: 'Count',
                        data: [0, 0, 0, 0, 0],
                        backgroundColor: '#45315D',
                        borderRadius: 4
                    }]
                },
                options: commonOptions
            });
        }

        // D) Scenario (Bar)
        const ctxS = document.getElementById('chartScenario')?.getContext('2d');
        if (ctxS) {
            this.state.charts.scenario = new Chart(ctxS, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Events',
                        data: [],
                        backgroundColor: ['#FF9280', '#45315D', '#6c757d', '#2196f3'],
                        borderRadius: 4
                    }]
                },
                options: {
                    ...commonOptions,
                    indexAxis: 'y' // Horizontal bar for scenarios
                }
            });
        }

        // 2. Event Listeners for Presets
        document.querySelectorAll('.btn-preset[data-ana-range]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // UI Toggle
                document.querySelectorAll('.btn-preset[data-ana-range]').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                // State Update
                const newRange = e.target.getAttribute('data-ana-range');
                this.state.analytics.range = newRange;

                // Load Data — always fetch from DB
                this.loadAnalyticsFromDB(newRange).then(() => this.updateAnalyticsUI());
            });
        });

        // Initial update
        this.updateAnalyticsUI();
    },

    // ---------------------------------------------------------
    // Helper: Boolean Normalizer
    // ---------------------------------------------------------
    isOn(val) {
        if (typeof val === 'string') {
            const low = val.toLowerCase();
            return low === '1' || low === 'true' || low === 'on';
        }
        return val === 1 || val === true;
    },

    normalizeEvent(e) {
        // Shallow copy to avoid mutating original store
        const n = { ...e };

        // Canonical warning_device_on
        if (n.warning_device_on === undefined) {
            n.warning_device_on = n.warning_on;
        }

        // Ensure we rely on isOn() checks later, but here we can't easily force it back to boolean 
        // without mutating if source was string. 
        // We just ensure the KEY exists. The comsumer uses isOn(n.warning_device_on).

        return n;
    },

    updateAnalyticsUI() {
        const agg = window.EventStore.analyticsAggregate;

        // Empty State Check
        const chartGrid = document.querySelector('#analytics-section .charts-grid');
        if (chartGrid) {
            if (!agg || agg.total_events === 0) {
                chartGrid.style.display = 'none';
                let emptyMsg = document.getElementById('ana-empty-msg');
                if (!emptyMsg) {
                    emptyMsg = document.createElement('div');
                    emptyMsg.id = 'ana-empty-msg';
                    emptyMsg.style.textAlign = 'center';
                    emptyMsg.style.padding = '40px';
                    emptyMsg.style.color = '#666';
                    emptyMsg.innerHTML = '<i class="fa-solid fa-chart-simple" style="font-size:3rem; margin-bottom:10px; opacity:0.3;"></i><p>No analytics data for this period.</p>';
                    chartGrid.parentNode.insertBefore(emptyMsg, chartGrid);
                } else {
                    emptyMsg.style.display = 'block';
                }
                return;
            } else {
                chartGrid.style.display = 'grid';
                const emptyMsg = document.getElementById('ana-empty-msg');
                if (emptyMsg) emptyMsg.style.display = 'none';
            }
        }

        if (!agg) return;
        this.renderKPIs(agg);
        this.updateCharts(agg);
    },

    // getAnalyticsEvents() retained for any legacy callers but no longer used by Analytics/Reports.
    // Backend aggregate is the single source of truth — no client-side range re-filtering.
    getAnalyticsEvents() {
        return (window.EventStore.analyticsRows || []).slice();
    },

    renderKPIs(agg) {
        document.getElementById('ana-kpi-warnings').textContent = agg.total_warnings;
        document.getElementById('ana-kpi-detections').textContent = agg.total_detections;
        document.getElementById('ana-kpi-false').textContent = agg.false_warnings;
        document.getElementById('ana-kpi-latency').textContent = (agg.avg_latency || 0) + 'ms';
        document.getElementById('ana-kpi-peak').textContent = agg.peak_hour || '--';
        console.debug(
            `[Analytics KPIs] warnings=${agg.total_warnings}, detections=${agg.total_detections},` +
            ` false=${agg.false_warnings}, avg_lat=${agg.avg_latency}ms, peak=${agg.peak_hour}`
        );
    },

    // computeKPIs retained for backward compat but superseded by renderKPIs(agg).
    computeKPIs(events) {
        console.warn('[Analytics] computeKPIs() called with row data — use renderKPIs(agg) instead.');
    },

    // updateCharts now receives the full aggregate object from /api/analytics.
    // All binning is done server-side — client only renders the pre-computed arrays.
    updateCharts(agg) {
        const timeSeries = agg.time_series || [];
        const labels = timeSeries.map(b => b.label);
        const dataWarnings = timeSeries.map(b => b.warnings);
        const dataDetections = timeSeries.map(b => b.detections);

        // A) Warnings over time
        if (this.state.charts.warnings) {
            const chart = this.state.charts.warnings;
            chart.data.labels = labels;
            chart.data.datasets[0].data = dataWarnings;
            chart.update('none');
        }

        // B) Detections over time
        if (this.state.charts.detections) {
            const chart = this.state.charts.detections;
            chart.data.labels = labels;
            chart.data.datasets[0].data = dataDetections;
            chart.update('none');
        }

        // C) Confidence histogram (server-computed per-bucket counts)
        if (this.state.charts.confidence) {
            const chart = this.state.charts.confidence;
            chart.data.datasets[0].data = agg.confidence_bins || [0, 0, 0, 0, 0];
            chart.update('none');
        }

        // D) Scenario distribution (server-computed)
        if (this.state.charts.scenario) {
            const dist = agg.scenario_distribution || [];
            const chart = this.state.charts.scenario;
            chart.data.labels = dist.map(d => d.scenario);
            chart.data.datasets[0].data = dist.map(d => d.count);
            chart.update('none');
        }
    },

    // ---------------------------------------------------------
    // 8. Reports Logic
    // ---------------------------------------------------------
    setupReports() {
        // Init State
        if (!this.state.reports) {
            this.state.reports = {
                range: 'today',
                lastSummary: null
            };
        }

        // 1. Presets — always fetch dedicated report data for the selected range
        document.querySelectorAll('.btn-preset[data-rep-range]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // UI
                document.querySelectorAll('.btn-preset[data-rep-range]').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                // State
                this.state.reports.range = e.target.getAttribute('data-rep-range');

                // Always fetch from DB then generate
                this.loadReportFromDB(this.state.reports.range).then(() => this.generateReport());
            });
        });

        // 2. Actions
        document.getElementById('btnGenerateReport')?.addEventListener('click', () => {
            // Always fetch fresh data for the selected report range
            this.loadReportFromDB(this.state.reports.range).then(() => this.generateReport());
        });

        document.getElementById('btnPrintReport')?.addEventListener('click', () => {
            if (!this.state.reports.lastSummary) this.generateReport();
            window.print();
        });

        document.getElementById('btnDownloadReportJSON')?.addEventListener('click', () => {
            if (!this.state.reports.lastSummary) this.generateReport();
            this.downloadReport('json');
        });

        document.getElementById('btnDownloadReportCSV')?.addEventListener('click', () => {
            if (!this.state.reports.lastSummary) this.generateReport();
            this.downloadReport('csv');
        });

        // Initial Generation — always fetch from DB on load
        setTimeout(() => {
            this.loadReportFromDB(this.state.reports.range).then(() => this.generateReport());
        }, 500);
    },

    // Returns the event dataset for the current report range (always from DB reportRows).
    getReportEvents() {
        return (window.EventStore.reportRows || []).slice();
    },

    async generateReport() {
        // Ensure aggregate is loaded. If not, fetch now.
        if (!window.EventStore.reportAggregate) {
            const ok = await this.loadReportFromDB(this.state.reports.range);
            if (!ok) return; // DB unavailable — banner shown by loadReportFromDB
        }

        const agg = window.EventStore.reportAggregate;
        const range = this.state.reports.range;

        // All metrics come from server-side aggregate — accurate for ALL rows, not a limited subset.
        const totalWarnings = agg.total_warnings;
        const totalDetections = agg.total_detections;
        const falseWarnings = agg.false_warnings;
        const avgLatency = Math.round(agg.avg_latency || 0);
        const peakHour = agg.peak_hour || '--';
        const topScenario = agg.top_scenario || '--';

        console.debug(
            `[Report] range=${range} | events=${agg.total_events} | warnings=${totalWarnings}` +
            ` | detections=${totalDetections} | false=${falseWarnings}` +
            ` | avg_lat=${avgLatency}ms | peak=${peakHour} | window=${agg.range_start} → ${agg.range_end}`
        );

        // Insights
        const insights = [];
        if (agg.total_events === 0) {
            insights.push('No events recorded during this period.');
        } else {
            if (totalWarnings > 0) insights.push(`Total of ${totalWarnings} warnings triggered.`);
            if (peakHour !== '--') insights.push(`Peak warning period: ${peakHour}`);
            if (topScenario !== '--') insights.push(`Most common scenario: ${topScenario}`);
            if (avgLatency < 100) insights.push(`System performance optimal (Avg latency < 100ms).`);
            else insights.push(`Average latency is ${avgLatency}ms.`);
        }

        const summary = {
            rangeLabel: document.querySelector(`.btn-preset[data-rep-range="${range}"]`)?.textContent?.trim() || range,
            generatedAt: new Date().toLocaleString(),
            totalWarnings,
            totalDetections,
            falseWarnings,
            avgLatency,
            peakHour,
            metrics: { mostCommonScenario: topScenario },
            insights
        };

        this.state.reports.lastSummary = summary;
        this.renderReport(summary);
    },

    renderReport(summary) {
        // Update DOM elements directly
        document.getElementById('rep-range-label').textContent = summary.rangeLabel;
        document.getElementById('rep-generated-at').textContent = summary.generatedAt;

        document.getElementById('rep-total-warnings').textContent = summary.totalWarnings;
        document.getElementById('rep-total-detections').textContent = summary.totalDetections;
        document.getElementById('rep-false-warnings').textContent = summary.falseWarnings;
        document.getElementById('rep-avg-latency').textContent = summary.avgLatency + 'ms';
        document.getElementById('rep-peak-hour').textContent = summary.peakHour;

        const list = document.getElementById('rep-insights-list');
        if (list) {
            list.innerHTML = summary.insights.map(i => `<li>${i}</li>`).join('');
        }
    },

    downloadReport(type) {
        const s = this.state.reports.lastSummary;
        if (!s) return;

        const dateStr = new Date().toISOString().slice(0, 10);
        const filename = `report_summary_${dateStr}_${this.state.reports.range}.${type}`;

        let content = '';
        if (type === 'json') {
            // Export summary without internal _rows field
            const { _rows, ...exportable } = s;
            content = JSON.stringify(exportable, null, 2);
        } else {
            // CSV — summary row
            const header = 'Generated At,Range,Total Warnings,Total Detections,False Warnings,Avg Latency,Peak Hour,Most Common Scenario,Location,Client,Title\n';
            const row = `${s.generatedAt},${s.rangeLabel},${s.totalWarnings},${s.totalDetections},${s.falseWarnings},${s.avgLatency}ms,${s.peakHour},${s.metrics.mostCommonScenario},"Casisang Central School","TMC","IoT-Based Smart School-Zone Crosswalk Alert System"`;
            content = header + row;
        }

        const blob = new Blob([content], { type: type === 'csv' ? 'text/csv;charset=utf-8;' : 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    },

    setupROI() {
        // 1. References
        const canvas = document.getElementById('roiCanvas');
        const fileInput = document.getElementById('roiImageInput');
        const overlay = document.getElementById('roiOverlayText');

        if (!canvas) return;

        // 2. State Init
        this.ctx = canvas.getContext('2d');
        this.roiState = {
            isDrawing: false,
            startX: 0,
            startY: 0,
            img: null // Image object
        };

        // 3. Load from LocalStorage (image data only)
        const savedImgData = localStorage.getItem('roiImageData');

        if (savedImgData) {
            this.loadImageToCanvas(savedImgData);
        } else {
            // No image? Show overlay
            overlay.style.display = 'block';
            canvas.style.display = 'none';
        }

        // 3b. Sync ROI rect from server (authoritative source)
        fetch('/api/roi').then(r => r.json()).then(j => {
            if (j.ok && j.roi) {
                const sr = j.roi;
                // Convert server x1,y1,x2,y2 to canvas x,y,w,h
                this.state.roi = {
                    x: sr.x1,
                    y: sr.y1,
                    w: sr.x2 - sr.x1,
                    h: sr.y2 - sr.y1
                };
                // Also store the image dims for reference
                localStorage.setItem('roiImageMeta', JSON.stringify({
                    width: sr.image_w,
                    height: sr.image_h
                }));
                localStorage.setItem('roiRect', JSON.stringify(this.state.roi));
                this.roiDirty = false; // Server-synced = active
                this.drawRoi();
                this.updateRoiCoords(this.state.roi);
                console.log('[ROI] Synced from server:', sr);
            }
        }).catch(() => {
            // Server unavailable — fall back to localStorage
            const savedRect = localStorage.getItem('roiRect');
            if (savedRect) {
                this.state.roi = JSON.parse(savedRect);
                this.drawRoi();
                this.updateRoiCoords(this.state.roi);
            }
        });

        // 4. Event Listeners

        // A) File Input
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files[0]) {
                const reader = new FileReader();
                reader.onload = (evt) => {
                    // Reset ROI on new image
                    this.state.roi = null;
                    this.loadImageToCanvas(evt.target.result);
                    // Mark dirty (new image = unsaved)
                    this.roiDirty = true;
                    const ub = document.getElementById('roiUnsavedBadge');
                    if (ub) ub.style.display = 'inline-flex';
                    // Clear inputs just in case
                    e.target.value = '';
                };
                reader.readAsDataURL(e.target.files[0]);
            }
        });

        // B) Canvas Drawing
        canvas.addEventListener('mousedown', (e) => {
            if (!this.roiState.img) return;
            const pos = this.getCanvasCoordinates(e, canvas);
            this.roiState.isDrawing = true;
            this.roiState.startX = pos.x;
            this.roiState.startY = pos.y;

            // Start a new rect
            this.state.roi = { x: pos.x, y: pos.y, w: 0, h: 0 };
            this.drawRoi();
        });

        canvas.addEventListener('mousemove', (e) => {
            if (!this.roiState.isDrawing || !this.roiState.img) return;
            const pos = this.getCanvasCoordinates(e, canvas);

            // Calculate width/height
            // Allow drawing in any direction
            let w = pos.x - this.roiState.startX;
            let h = pos.y - this.roiState.startY;

            // Normalize (x,y always top-left)
            // But we'll just store raw w/h for now, or normalize?
            // Standard approach: x,y is top-left.

            // Let's keep it simple: x/y is start, w/h can be negative during draw
            // but for final save we normalize.
            this.state.roi.w = w;
            this.state.roi.h = h;

            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
        });

        canvas.addEventListener('mouseup', (e) => {
            if (this.roiState.isDrawing) {
                this.roiState.isDrawing = false;
                // Normalize rect (w/h should be positive)
                this.normalizeRoi();
                this.drawRoi();
                this.updateRoiCoords(this.state.roi);
                // Mark dirty
                this.roiDirty = true;
                const ub = document.getElementById('roiUnsavedBadge');
                if (ub) ub.style.display = 'inline-flex';
            }
        });

        canvas.addEventListener('mouseout', () => {
            if (this.roiState.isDrawing) {
                this.roiState.isDrawing = false;
                this.normalizeRoi();
                this.drawRoi();
                this.updateRoiCoords(this.state.roi);
            }
        });

        // C) Buttons
        document.getElementById('btnSaveRoi')?.addEventListener('click', () => this.saveRoi());
        document.getElementById('btnResetRoi')?.addEventListener('click', () => this.resetRoi());

        // D) Capture Frame
        document.getElementById('btnCaptureFrame')?.addEventListener('click', () => {
            const liveImg = document.getElementById('liveCam');
            if (liveImg && liveImg.src && window.CameraController.isOn) {
                const c = document.createElement('canvas');
                c.width = liveImg.naturalWidth || 1280;
                c.height = liveImg.naturalHeight || 720;
                const ctx = c.getContext('2d');
                try {
                    ctx.drawImage(liveImg, 0, 0, c.width, c.height);
                    const dataUrl = c.toDataURL('image/jpeg', 0.8);
                    this.state.roi = null;
                    this.loadImageToCanvas(dataUrl);
                    // Mark dirty (new capture = unsaved)
                    this.roiDirty = true;
                    const ub = document.getElementById('roiUnsavedBadge');
                    if (ub) ub.style.display = 'inline-flex';
                } catch (e) {
                    alert("Stream error capturing frame. Please upload an image instead.");
                }
            } else {
                alert("Camera is not running in Live View. Please Start Camera first.");
            }
        });
    },

    loadImageToCanvas(dataUrl) {
        const img = new Image();
        img.onload = () => {
            this.roiState.img = img;
            const canvas = document.getElementById('roiCanvas');
            const overlay = document.getElementById('roiOverlayText');

            // Set Resolution
            // Limit max resolution to avoid huge storage/perf issues? 
            // Prompt says: "keep it small... warn if huge".
            // We'll use natural size but maybe cap max width for display helpfulness?
            // Actually, for "saving image" we are saving the DataURL which is already loaded. 
            // If it's huge, localStorage will crash (5MB limit).
            // For now, we use what we have.

            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;

            // UI
            canvas.style.display = 'block';
            overlay.style.display = 'none';

            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
        };
        img.src = dataUrl;
    },

    getCanvasCoordinates(e, canvas) {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;

        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY
        };
    },

    normalizeRoi() {
        if (!this.state.roi) return;
        let { x, y, w, h } = this.state.roi;

        if (w < 0) { x += w; w = Math.abs(w); }
        if (h < 0) { y += h; h = Math.abs(h); }

        // Constraints
        const img = this.roiState.img;
        if (img) {
            x = Math.max(0, x);
            y = Math.max(0, y);
            w = Math.min(w, img.naturalWidth - x);
            h = Math.min(h, img.naturalHeight - y);
        }

        this.state.roi = { x, y, w, h };
    },

    drawRoi() {
        const ctx = this.ctx;
        const canvas = document.getElementById('roiCanvas');
        const img = this.roiState.img;
        const roi = this.state.roi;

        if (!ctx || !canvas) return;

        // Clear
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw Image
        if (img) {
            ctx.drawImage(img, 0, 0);
        }

        // Draw Rect — Green = Active (saved), Red = Draft (unsaved)
        if (roi && (roi.w !== 0 || roi.h !== 0)) {
            const isDraft = !!this.roiDirty;
            const fillColor = isDraft ? 'rgba(239, 68, 68, 0.25)' : 'rgba(34, 197, 94, 0.25)';
            const strokeColor = isDraft ? '#ef4444' : '#22c55e';

            // Fill
            ctx.fillStyle = fillColor;
            ctx.fillRect(roi.x, roi.y, roi.w, roi.h);

            // Stroke
            ctx.strokeStyle = strokeColor;
            ctx.lineWidth = 3;
            ctx.strokeRect(roi.x, roi.y, roi.w, roi.h);

            // Label
            const label = isDraft ? 'DRAFT' : 'ACTIVE';
            ctx.font = 'bold 14px Manrope, sans-serif';
            ctx.fillStyle = strokeColor;
            const labelX = roi.x + 6;
            const labelY = roi.y > 22 ? roi.y - 8 : roi.y + 18;
            ctx.fillText(label, labelX, labelY);
        }
    },

    updateRoiCoords(roi) {
        if (!roi) roi = { x: 0, y: 0, w: 0, h: 0 };

        // Update DOM
        ['x', 'y', 'w', 'h'].forEach(k => {
            const el = document.getElementById(`roi${k.toUpperCase()}`);
            if (el) el.textContent = Math.round(roi[k]);
        });

        // Img Dims
        if (this.roiState.img) {
            document.getElementById('roiImgW').textContent = this.roiState.img.naturalWidth;
            document.getElementById('roiImgH').textContent = this.roiState.img.naturalHeight;
        }
    },

    async saveRoiToServer(roiRect, roiImageMeta) {
        // Convert canvas {x,y,w,h} to server {x1,y1,x2,y2}
        const hasXY = roiRect.x !== undefined && roiRect.y !== undefined;
        const x1 = Math.round(hasXY ? roiRect.x : (roiRect.x1 ?? 0));
        const y1 = Math.round(hasXY ? roiRect.y : (roiRect.y1 ?? 0));
        const x2 = Math.round(hasXY ? roiRect.x + roiRect.w : (roiRect.x2 ?? 0));
        const y2 = Math.round(hasXY ? roiRect.y + roiRect.h : (roiRect.y2 ?? 0));
        const image_w = Math.round(roiImageMeta?.width ?? roiImageMeta?.image_w ?? 0);
        const image_h = Math.round(roiImageMeta?.height ?? roiImageMeta?.image_h ?? 0);

        const payload = { x1, y1, x2, y2, image_w, image_h };
        console.log('[ROI] Saving to server:', payload);

        // 10-second timeout so the button never gets stuck at "Saving..." forever
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        try {
            const res = await fetch("/api/roi", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });
            clearTimeout(timeoutId);

            const j = await res.json().catch(() => ({}));
            if (!res.ok || !j.ok) {
                throw new Error(j.error || `HTTP ${res.status}`);
            }
        } catch (e) {
            clearTimeout(timeoutId);
            if (e.name === 'AbortError') {
                throw new Error('Server did not respond in time (10s). Is the camera stream blocking the server?');
            }
            throw e;
        }
    },

    async saveRoi() {
        if (!this.state.roi) {
            alert("No ROI defined.");
            return;
        }

        const btn = document.getElementById('btnSaveRoi');
        const oldHTML = btn ? btn.innerHTML : '';

        try {
            // 1. ROI Rect
            localStorage.setItem('roiRect', JSON.stringify(this.state.roi));

            // 2. Image Data (only if new image loaded, or keep existing)
            if (this.roiState.img && this.roiState.img.src.startsWith('data:')) {
                localStorage.setItem('roiImageData', this.roiState.img.src);
            }

            // 3. Meta
            let meta = null;
            if (this.roiState.img) {
                meta = { width: this.roiState.img.naturalWidth, height: this.roiState.img.naturalHeight };
                localStorage.setItem('roiImageMeta', JSON.stringify(meta));
            } else {
                meta = JSON.parse(localStorage.getItem('roiImageMeta') || "{}");
            }

            // 4. Visual: Saving state
            if (btn) {
                btn.classList.remove('btn-saved', 'btn-error');
                btn.classList.add('btn-saving');
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
            }

            // 5. Send to Backend
            await this.saveRoiToServer(this.state.roi, meta);

            // 6. Success feedback
            if (btn) {
                btn.classList.remove('btn-saving');
                btn.classList.add('btn-saved');
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Saved \u2713';
                setTimeout(() => {
                    btn.classList.remove('btn-saved');
                    btn.innerHTML = oldHTML;
                }, 1200);
            }

            // 7. Clear dirty flag & redraw ROI in "active" green
            this.roiDirty = false;
            this.drawRoi();
            const ub = document.getElementById('roiUnsavedBadge');
            if (ub) ub.style.display = 'none';

            // Note: Live View badge + camera stream restart is now handled
            // by the 'roi_updated' socket event emitted by the backend.
            // Fallback for cases where socket is not connected:
            if (!this.socket || !this.socket.connected) {
                this.updateLiveRoiBadge();
                if (window.CameraController.isOn) {
                    const img = document.getElementById('liveCam');
                    if (img && img.src && img.src.includes('/video_feed')) {
                        const currentSrc = img.src;
                        img.src = '';
                        setTimeout(() => { img.src = currentSrc; }, 100);
                    }
                }
            }

        } catch (e) {
            console.error("[ROI] Save error:", e);

            if (btn) {
                btn.classList.remove('btn-saving');
                btn.classList.add('btn-error');
                btn.innerHTML = '<i class="fa-solid fa-xmark"></i> Save failed';
                setTimeout(() => {
                    btn.classList.remove('btn-error');
                    btn.innerHTML = oldHTML;
                }, 1800);
            }

            if (e.name === 'QuotaExceededError') {
                alert("Error: Image is too large to save in browser storage. Please use a smaller image/resolution.");
            }
        }
    },

    resetRoi() {
        if (!confirm("Are you sure you want to clear the ROI and Image?")) return;

        // Clear State
        this.state.roi = null;
        this.roiState.img = null;

        // Clear Storage
        localStorage.removeItem('roiRect');
        localStorage.removeItem('roiImageData');
        localStorage.removeItem('roiImageMeta');

        // Update UI
        this.drawRoi(); // Clears canvas since img is null
        document.getElementById('roiCanvas').style.display = 'none';
        document.getElementById('roiOverlayText').style.display = 'block';
        this.updateRoiCoords(null);
        document.getElementById('roiImgW').textContent = '0';
        document.getElementById('roiImgH').textContent = '0';
    },

    // ---------------------------------------------------------
    // Legacy / Shared
    // ---------------------------------------------------------

    // Camera Logic
    initCamera() {
        // Button Listeners
        document.getElementById('btnStartCam')?.addEventListener('click', () => this.startCamera());
        document.getElementById('btnStopCam')?.addEventListener('click', () => this.stopCamera());
        document.getElementById('debugOverlayToggle')?.addEventListener('change', (e) => {
            if (window.CameraController.isOn) {
                const img = document.getElementById('liveCam');
                if (img) img.src = '/video_feed?overlay=' + (e.target.checked ? "1" : "0");
            }
        });
        // Default overlay to ON
        const overlayToggle = document.getElementById('debugOverlayToggle');
        if (overlayToggle) overlayToggle.checked = true;

        const select = document.getElementById('camDeviceSelect');
        const typeSelect = document.getElementById('camSourceType');
        const ipGroup = document.getElementById('ipCamInputGroup');
        const locGroup = document.getElementById('localCamInputGroup');
        const ipInput = document.getElementById('ipCamUrl');

        if (typeSelect) {
            // Load saved state
            const savedType = localStorage.getItem('camSourceType') || 'ip';
            typeSelect.value = savedType;
            if (savedType === 'ip') {
                if (ipGroup) ipGroup.style.display = 'block';
                if (locGroup) locGroup.style.display = 'none';
            } else {
                if (ipGroup) ipGroup.style.display = 'none';
                if (locGroup) locGroup.style.display = 'block';
            }

            const savedUrl = localStorage.getItem('ipCamUrl');
            if (savedUrl && ipInput) ipInput.value = savedUrl;

            typeSelect.addEventListener('change', (e) => {
                const newType = e.target.value;
                localStorage.setItem('camSourceType', newType);

                if (newType === 'ip') {
                    if (ipGroup) ipGroup.style.display = 'block';
                    if (locGroup) locGroup.style.display = 'none';
                } else {
                    if (ipGroup) ipGroup.style.display = 'none';
                    if (locGroup) locGroup.style.display = 'block';
                }

                // If camera is already ON, restart with new type
                if (window.CameraController.isOn) {
                    this.stopCamera();
                    setTimeout(() => this.startCamera(), 300);
                }
            });
        }

        if (ipInput) {
            ipInput.addEventListener('change', (e) => {
                localStorage.setItem('ipCamUrl', e.target.value.trim());
                if (window.CameraController.isOn && typeSelect && typeSelect.value === 'ip') {
                    this.stopCamera();
                    setTimeout(() => this.startCamera(), 300);
                }
            });
        }

        if (select) {
            select.addEventListener('change', (e) => {
                const newId = e.target.value;
                if (window.CameraController.selectedDeviceId === newId) return; // No change

                window.CameraController.selectedDeviceId = newId;
                localStorage.setItem('camDeviceId', newId);

                // If camera is already ON, restart with new device
                if (window.CameraController.isOn && typeSelect && typeSelect.value === 'local') {
                    this.stopCamera(); // Stop current
                    setTimeout(() => this.startCamera(), 300); // Restart
                }
            });
        }

        // Enumerate Devices
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
            navigator.mediaDevices.enumerateDevices().then(devices => {
                const videoDevices = devices.filter(device => device.kind === 'videoinput');

                if (select) {
                    if (videoDevices.length > 0) {
                        select.innerHTML = videoDevices.map(device =>
                            `<option value="${device.deviceId}">${device.label || `Camera ${select.length + 1}`}</option>`
                        ).join('');

                        if (videoDevices.length > 1) selectGroup.style.display = 'block';

                        // Restore selection or default
                        const savedId = window.CameraController.selectedDeviceId;
                        if (savedId && videoDevices.some(d => d.deviceId === savedId)) {
                            select.value = savedId;
                        } else {
                            // Default to first
                            window.CameraController.selectedDeviceId = videoDevices[0].deviceId;
                        }
                    } else {
                        // No devices
                        select.innerHTML = '<option disabled>No cameras found</option>';
                    }
                }
            }).catch(e => console.warn("Camera enum error:", e));
        }

        // On Load Persistence Check
        // If the implementation supports hot-reloading or we want to be safe:
        if (window.CameraController.isOn && window.CameraController.stream) {
            this.attachStreamToVideo(window.CameraController.stream);
        }
    },

    startCamera() {
        const img = document.getElementById('liveCam');
        if (!img) return;

        // Use backend video feed
        const useOverlay = document.getElementById('debugOverlayToggle')?.checked ? "1" : "0";

        let sourceParam = "";
        const typeSelect = document.getElementById('camSourceType');

        if (typeSelect && typeSelect.value === 'ip') {
            const ipUrl = document.getElementById('ipCamUrl')?.value.trim();
            if (ipUrl) {
                sourceParam = encodeURIComponent(ipUrl);
            }
        } else {
            // Local webcam index
            const selectTarget = document.getElementById('camDeviceSelect');
            if (selectTarget && selectTarget.selectedIndex >= 0) {
                sourceParam = selectTarget.selectedIndex.toString();
            } else {
                sourceParam = "0"; // Default
            }
        }

        img.src = '/video_feed?overlay=' + useOverlay + '&source=' + sourceParam;
        img.style.display = 'block';
        window.CameraController.isOn = true;
        this.updateLiveRoiBadge();

        // UI
        const ph = document.getElementById('camPlaceholder');
        if (ph) ph.style.display = 'none';

        const chip = document.getElementById('camStatusChip');
        if (chip) {
            chip.className = 'status-chip connected';
            chip.innerHTML = '<div class="status-indicator"></div> ON';
            chip.style.backgroundColor = 'rgba(76, 175, 80, 0.1)';
            chip.style.color = '#2e7d32';
        }

        const sourceChip = document.getElementById('camSourceChip');
        if (sourceChip) {
            sourceChip.style.display = 'flex';
            sourceChip.innerHTML = '<div class="status-indicator"></div> IP Webcam + YOLO';
        }
    },

    stopCamera() {
        window.CameraController.isOn = false;

        // UI Reset
        const img = document.getElementById('liveCam');
        if (img) {
            img.src = '';
            img.style.display = 'none';
        }

        const ph = document.getElementById('camPlaceholder');
        if (ph) {
            ph.style.display = 'flex';
            ph.innerHTML = `
                <div style="font-size: 2rem; margin-bottom: 10px; color: #ccc;">
                    <i class="fa-solid fa-camera"></i>
                </div>
                <p><strong>Camera is OFF.</strong><br>Click Start Camera to preview.</p>
                <p style="font-size: 0.8rem; margin-top: 10px; color: #888;">Powered by OpenCV backend.</p>
            `;
        }

        const chip = document.getElementById('camStatusChip');
        if (chip) {
            chip.className = 'status-chip mock';
            chip.innerHTML = '<div class="status-indicator"></div> OFF';
            chip.style.backgroundColor = '#eee';
            chip.style.color = '#666';
        }
        const sourceChip = document.getElementById('camSourceChip');
        if (sourceChip) sourceChip.style.display = 'none';

        // Reset live status cards to idle state
        const status = window.EventStore.systemStatus;
        status.child_in_roi = false;
        status.warning_on = false;
        status.confidence = 0.0;
        status.roi_status = 'OUTSIDE';
        status.latency_ms = 0;
        status.connection_status = 'Camera OFF';
        this.updateUI();
    },

    // ---------------------------------------------------------
    // 8. Theme Management
    // ---------------------------------------------------------
    initTheme() {
        // Initial Apply
        this.setTheme(this.state.theme, false);

        // Listener
        document.getElementById('theme-toggle')?.addEventListener('click', () => {
            const newTheme = this.state.theme === 'light' ? 'dark' : 'light';
            this.setTheme(newTheme, true);
        });
    },

    setTheme(theme, updateCharts = true) {
        this.state.theme = theme;
        localStorage.setItem('theme', theme);

        // Body Class
        if (theme === 'dark') document.body.classList.add('dark-mode');
        else document.body.classList.remove('dark-mode');

        // Button Icon/Title
        const btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.innerHTML = theme === 'dark' ?
                '<i class="fa-solid fa-sun"></i>' :
                '<i class="fa-solid fa-moon"></i>';
            btn.title = theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode";

            // Adjust button class for visibility if needed, but outline/primary works in CSS
        }

        // Update Charts
        if (updateCharts) this.updateChartsTheme();
    },

    updateChartsTheme() {
        const isDark = this.state.theme === 'dark';
        const gridColor = isDark ? '#333333' : '#f0f0f0';
        const textColor = isDark ? '#a0a0a0' : '#666';

        Object.values(this.state.charts).forEach(chart => {
            if (!chart) return;

            if (chart.options.scales.x) {
                chart.options.scales.x.ticks.color = textColor;
            }
            if (chart.options.scales.y) {
                chart.options.scales.y.grid.color = gridColor;
                chart.options.scales.y.ticks.color = textColor;
            }
            chart.update();
        });
    },

    async updateLiveRoiBadge() {
        try {
            const res = await fetch("/api/roi");
            if (res.ok) {
                const j = await res.json();
                if (j.ok && j.roi) {
                    const b = document.getElementById('liveRoiBadge');
                    if (b) {
                        b.style.display = 'block';
                        b.innerHTML = `<i class="fa-solid fa-crosshairs"></i> ROI Active: (${Math.round(j.roi.x1)}, ${Math.round(j.roi.y1)}) to (${Math.round(j.roi.x2)}, ${Math.round(j.roi.y2)})`;
                    }
                }
            }
        } catch (e) { }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
