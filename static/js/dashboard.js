// Dashboard Application Logic

// ---------------------------------------------------------
// GLOBAL AUTH INTERCEPTOR — redirects to login on 401
// ---------------------------------------------------------
(function() {
    const _origFetch = window.fetch;
    window.fetch = async function(...args) {
        const response = await _origFetch.apply(this, args);
        if (response.status === 401) {
            // Session expired or not authenticated — redirect to login
            window.location.href = '/';
            return response;
        }
        return response;
    };
})();

// ---------------------------------------------------------
// GLOBAL STORE (Single Source of Truth)
// ---------------------------------------------------------
window.EventStore = {
    events: [],       // All events (Logs/Analytics)
    systemStatus: {   // Detection & Telemetry Status
        child_in_roi: false,
        warning_on: false,
        confidence: 0.0,
        roi_status: 'OUTSIDE',
        latency_ms: 0,
        stream_latency_ms: 0,
        fps: 0.0,
        capture_fps: 0.0,
        infer_fps: 0.0,
        frame_drop_rate: 0.0,
        edge_compute: { cpu_percent: 0.0, ram_percent: 0.0 },
        relay_status: { connected: false, label: 'Disconnected', port: 'COM5', heartbeat_ok: false, heartbeat_label: 'Not Responding' },
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
// CAMERA STATE (Hikvision — single source, auto-connect)
// ---------------------------------------------------------
window.CameraState = {
    isConnected: false,
    isReconnecting: false,
    reconnectTimer: null,
    statusPollTimer: null,
    lastStatus: null,
};

// ---------------------------------------------------------
// APP MODE STATE (Live Camera vs Video Test)
// ---------------------------------------------------------
window.AppMode = {
    current: 'live',           // 'live' | 'video_test'
    testVideoFile: null,       // currently playing filename
    availableVideos: [],       // from /api/test_videos
    switching: false,          // prevent double-clicks during mode switch
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
            startDate: null,
            endDate: null,
            searchText: '',
            warningOnly: true,
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
        this.setupTick(); // 1s tick for UI refresh and polling (live data only)
        this.setupAnalytics();

        // Init Logs Controls
        this.setupLogEvents();
        this.renderLogsTable(); // Initial render

        // Init Reports
        this.setupReports();

        this.setupROI();
        this.initCamera();
        this.initVideoTestMode();
        this.updateUI(); // Initial render

        // Sidebar Init
        this.initSidebar();

        // Change Password Modal Init (Shared)
        this.setupPasswordModal();

        // Initial Load for Logs if starting there
        if (window.location.hash === '#logs') {
            this.loadLogsFromDB();
        }

        // Warning Device Watchdog — auto-hide if no status_update in 2s
        this._lastStatusTs = Date.now();
        setInterval(() => {
            if (Date.now() - this._lastStatusTs > 2000) {
                this.setWarningUI(false, {});
            }
        }, 500);
    },

    setupTick() {
        // Main system tick (1Hz) for UI refresh and auto-polling.
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
                    badge.className = "status-chip disconnected";
                }
            });
            this.socket.on('status_update', (data) => {
                this.handleSocketData(data);
            });
            this.socket.on('roi_updated', (msg) => {
                this.handleRoiUpdated(msg);
            });
            this.socket.on('mode_update', (data) => {
                this.handleModeUpdate(data);
            });
        } catch (e) {
            console.log("Socket.IO not initialized.");
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

    // ---------------------------------------------------------
    // Visual Warning Device UI
    // ---------------------------------------------------------
    setWarningUI(isOn, payload) {
        const banner = document.getElementById('warningBanner');
        const overlay = document.getElementById('warningOverlay');
        const bannerMeta = document.getElementById('warningBannerMeta');
        const overlayMeta = document.getElementById('warningOverlayMeta');

        if (!banner || !overlay) return;

        if (isOn) {
            banner.classList.remove('hidden');
            overlay.classList.remove('hidden');

            const conf = payload?.confidence != null
                ? Number(payload.confidence).toFixed(3)
                : '—';
            const lat = payload?.latency_ms ?? payload?.latency ?? '—';
            const roi = payload?.roi_status ?? '';
            bannerMeta.textContent = `Conf: ${conf}  |  Latency: ${lat} ms  |  ROI: ${roi}`;
            overlayMeta.textContent = `Conf: ${conf}  •  Latency: ${lat} ms  •  ROI: ${roi}`;
        } else {
            banner.classList.add('hidden');
            overlay.classList.add('hidden');
            if (bannerMeta) bannerMeta.textContent = '';
            if (overlayMeta) overlayMeta.textContent = '';
        }
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

        // 2. Always update live status from socket data
        this.state.isConnected = true;
        this.state.lastSocketUpdate = Date.now();

        const status = window.EventStore.systemStatus;

        status.child_in_roi = data.child_in_roi;
        status.warning_on = data.warning_device_on ?? data.warning_on;
        status.confidence = data.confidence;
        status.roi_status = data.child_in_roi ? 'INSIDE' : 'OUTSIDE';
        status.latency_ms = data.latency_ms || data.latency || 0;
        status.stream_latency_ms = data.stream_latency_ms || 0;
        status.fps = (typeof data.fps === 'number') ? data.fps : (data.capture_fps || 0.0);
        status.capture_fps = data.capture_fps || 0.0;
        status.infer_fps = data.infer_fps || 0.0;
        status.frame_drop_rate = (typeof data.frame_drop_rate === 'number') ? data.frame_drop_rate : 0.0;
        if (data.edge_compute) status.edge_compute = data.edge_compute;
        if (data.relay_status) status.relay_status = data.relay_status;
        status.last_update_str = new Date().toLocaleTimeString();

        if (data.source === "yolo") {
            status.connection_status = "Live (YOLO)";
        } else if (data.source === "idle") {
            const camStatus = data.camera_status || "OFFLINE";
            status.connection_status = camStatus === "OFFLINE" ? "Camera Offline" : "Connected";
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

        // 3. Visual Warning Device — toggle banner/overlay
        this._lastStatusTs = Date.now();
        const warningOn = Boolean(data?.warning_device_on ?? data?.warning_on);
        this.setWarningUI(warningOn, data);
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
            validBadge.className = "status-chip disconnected";
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
            // Determine chip class — override to disconnected if camera says "Offline"
            let chipClass = this.state.isConnected ? 'connected' : 'disconnected';
            if (status.connection_status.toLowerCase().includes('offline')) {
                chipClass = 'disconnected';
            }
            connChip.innerHTML = `<div class="status-indicator"></div><span class="status-text">${status.connection_status}</span>`;
            connChip.className = `status-chip ${chipClass}`;
        }
        const lastUpdateEl = document.getElementById('last-update');
        if (lastUpdateEl) lastUpdateEl.textContent = status.last_update_str;

        // Live View Cards (IT Specialist Dashboard exclusive)
        const liveChild = document.getElementById('live-child');
        if (liveChild) {
            liveChild.textContent = status.child_in_roi ? 'YES' : 'NO';
            liveChild.style.color = status.child_in_roi ? '#d32f2f' : 'inherit';
        }

        const liveWarn = document.getElementById('live-warning');
        if (liveWarn) {
            liveWarn.textContent = status.warning_on ? 'ON' : 'OFF';
            liveWarn.style.color = status.warning_on ? '#d32f2f' : '#2e7d32';
        }

        // Sync the System Status "Warning Output" pill instantly with the metric card
        const warnChip = document.getElementById('sysStatusWarning');
        if (warnChip) {
            if (status.warning_on) {
                warnChip.innerHTML = '<div class="status-indicator"></div> Active';
                warnChip.className = 'status-chip';
                warnChip.style.backgroundColor = 'rgba(211, 47, 47, 0.12)';
                warnChip.style.color = '#b71c1c';
            } else {
                warnChip.innerHTML = '<div class="status-indicator"></div> Standby';
                warnChip.className = 'status-chip connected';
                warnChip.style.backgroundColor = '';
                warnChip.style.color = '';
            }
        }

        const liveConf = document.getElementById('live-conf');
        if (liveConf) {
            liveConf.textContent = (typeof status.confidence === 'number') ? status.confidence.toFixed(2) : '0.00';
        }

        const liveRoi = document.getElementById('live-roi');
        if (liveRoi) {
            liveRoi.textContent = status.roi_status;
            liveRoi.className = `card-value ${status.roi_status === 'INSIDE' ? 'text-danger' : ''}`;
        }

        const liveLat = document.getElementById('live-latency');
        if (liveLat) {
            liveLat.textContent = (status.latency_ms || 0) + 'ms';
        }

        const liveStreamLat = document.getElementById('live-stream-latency');
        if (liveStreamLat) {
            liveStreamLat.textContent = (status.stream_latency_ms || 0) + 'ms';
        }

        const liveFps = document.getElementById('live-fps');
        if (liveFps) {
            const fpsVal = (status.fps || status.capture_fps || 0);
            liveFps.textContent = fpsVal > 0 ? fpsVal.toFixed(1) : '--';
        }

        const liveDrop = document.getElementById('live-drop-rate');
        if (liveDrop) {
            const dropRate = (status.frame_drop_rate || 0);
            liveDrop.textContent = dropRate.toFixed(1) + '%';
            if (dropRate > 5.0) {
                liveDrop.classList.add('critical');
            } else {
                liveDrop.classList.remove('critical');
            }
        }

        // Relay Controller Status Chip
        const relayChip = document.getElementById('sysStatusRelay');
        const relayText = document.getElementById('sysStatusRelayText');
        const relayPort = document.getElementById('sysRelayPort');
        if (relayChip && status.relay_status) {
            const isRelayConn = Boolean(status.relay_status.connected);
            relayChip.className = `status-chip ${isRelayConn ? 'connected' : 'disconnected'}`;
            if (relayText) relayText.textContent = status.relay_status.label || (isRelayConn ? 'Connected' : 'Disconnected');
            if (relayPort) relayPort.textContent = `(${status.relay_status.port || 'COM5'})`;
        }

        // Hardware Pulse (Heartbeat) Status Chip
        const hbChip = document.getElementById('sysStatusHeartbeat');
        const hbText = document.getElementById('sysStatusHeartbeatText');
        if (hbChip && status.relay_status) {
            const isHbOk = Boolean(status.relay_status.heartbeat_ok);
            hbChip.className = `status-chip ${isHbOk ? 'connected' : 'disconnected'}`;
            if (hbText) hbText.textContent = status.relay_status.heartbeat_label || (isHbOk ? 'Responding' : 'Not Responding');
        }

        // Edge Compute Load
        const cpuBar = document.getElementById('cpu-load-bar');
        const cpuVal = document.getElementById('cpu-load-val');
        const ramBar = document.getElementById('ram-load-bar');
        const ramVal = document.getElementById('ram-load-val');
        if (status.edge_compute) {
            const cpuPct = Math.min(100, Math.max(0, status.edge_compute.cpu_percent || 0));
            const ramPct = Math.min(100, Math.max(0, status.edge_compute.ram_percent || 0));
            if (cpuBar) cpuBar.style.width = cpuPct + '%';
            if (cpuVal) cpuVal.textContent = cpuPct.toFixed(0) + '%';
            if (ramBar) ramBar.style.width = ramPct + '%';
            if (ramVal) ramVal.textContent = ramPct.toFixed(0) + '%';
        }

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

        if (f.startDate) params.append('start_date', f.startDate);
        if (f.endDate) params.append('end_date', f.endDate);
        if (f.warningOnly) params.append('warning_only', 'true');
        if (f.inRoiOnly) params.append('in_roi_only', 'true');
        if (f.minConf > 0) params.append('min_conf', f.minConf);
        if (f.scenario !== 'All') params.append('scenario', f.scenario);
        if (f.searchText) params.append('search', f.searchText);

        // UI Loading State (optional but good)
        const tbody = document.getElementById('logsTableBody');
        if (tbody && f.currentPage === 1 && !this.state.logsPollingTimer) {
            const colCount = document.querySelector('#logsTable.tmc-logs-table') ? 3 : (document.querySelector('#logsTable.it-logs-table') ? 6 : 8);
            // Only show explicit loading on first load or manual filter change, not every poll
            tbody.innerHTML = `<tr><td colspan="${colCount}" style="text-align:center; padding:20px; color:#888;"><i class="fa-solid fa-spinner fa-spin"></i> Loading DB logs...</td></tr>`;
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

                // Clear Custom Dates
                filters.startDate = null;
                filters.endDate = null;
                const startEl = document.getElementById('logsStartDate');
                const endEl = document.getElementById('logsEndDate');
                const clearBtn = document.getElementById('btnClearCustomRange');
                if (startEl) startEl.value = '';
                if (endEl) endEl.value = '';
                if (clearBtn) clearBtn.style.display = 'none';

                // Update State
                filters.range = e.target.getAttribute('data-range');
                filters.currentPage = 1;
                this.loadLogsFromDB();
            });
        });

        // Custom Date Range Inputs
        const startInput = document.getElementById('logsStartDate');
        const endInput = document.getElementById('logsEndDate');
        const clearCustomBtn = document.getElementById('btnClearCustomRange');

        const onCustomDateChange = () => {
            const startVal = startInput ? startInput.value : '';
            const endVal = endInput ? endInput.value : '';

            if (startVal || endVal) {
                // Deactivate preset buttons
                document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
                if (clearCustomBtn) clearCustomBtn.style.display = 'inline-flex';
                filters.startDate = startVal || null;
                filters.endDate = endVal || null;
            } else {
                if (clearCustomBtn) clearCustomBtn.style.display = 'none';
                filters.startDate = null;
                filters.endDate = null;
            }
        };

        if (startInput) {
            startInput.addEventListener('change', () => {
                onCustomDateChange();
                filters.currentPage = 1;
                this.loadLogsFromDB();
            });
        }

        if (endInput) {
            endInput.addEventListener('change', () => {
                onCustomDateChange();
                filters.currentPage = 1;
                this.loadLogsFromDB();
            });
        }

        if (clearCustomBtn) {
            clearCustomBtn.addEventListener('click', () => {
                if (startInput) startInput.value = '';
                if (endInput) endInput.value = '';
                clearCustomBtn.style.display = 'none';
                filters.startDate = null;
                filters.endDate = null;
                filters.range = 'today';
                document.querySelectorAll('.btn-preset').forEach(b => {
                    b.classList.toggle('active', b.getAttribute('data-range') === 'today');
                });
                filters.currentPage = 1;
                this.loadLogsFromDB();
            });
        }

        // Toggles
        document.getElementById('filterWarningOn')?.addEventListener('change', (e) => {
            filters.warningOnly = e.target.checked;
            filters.currentPage = 1;
            this.loadLogsFromDB();
        });

        document.getElementById('filterInRoi')?.addEventListener('change', (e) => {
            filters.inRoiOnly = e.target.checked;
            filters.currentPage = 1;
            this.loadLogsFromDB();
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
            filters.startDate = null;
            filters.endDate = null;
            filters.searchText = '';
            filters.warningOnly = true;
            filters.inRoiOnly = false;
            filters.minConf = 0.00;
            filters.scenario = 'All';
            filters.currentPage = 1;

            // Reset UI Controls
            document.querySelectorAll('.btn-preset').forEach(b => b.classList.toggle('active', b.getAttribute('data-range') === 'today'));
            if (startInput) startInput.value = '';
            if (endInput) endInput.value = '';
            if (clearCustomBtn) clearCustomBtn.style.display = 'none';
            if (searchInput) searchInput.value = '';
            const chkWarn = document.getElementById('filterWarningOn'); if (chkWarn) chkWarn.checked = true;
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
            // Note: log.rawTimestamp is needed. If missing, use a safe fallback value.
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

        const isTmcSimplified = document.querySelector('#logsTable.tmc-logs-table') !== null;
        const isItAudit = document.querySelector('#logsTable.it-logs-table') !== null;

        // Render Rows
        if (displayLogs.length === 0) {
            const colCount = isTmcSimplified ? 3 : (isItAudit ? 6 : 8);
            tbody.innerHTML = `<tr><td colspan="${colCount}" style="text-align:center; padding:20px; color:#888;">No logs found.</td></tr>`;
        } else {
            tbody.innerHTML = displayLogs.map(log => {
                // Always parse timestamp from ISO (DB source)
                let timeStr;
                const d = this.state.parseTimestamp(log.timestamp_iso);
                if (d) timeStr = d.toLocaleTimeString();
                else timeStr = log.timestamp_iso || log.timestamp || 'Unknown';

                if (isTmcSimplified) {
                    // Consolidated status: warning triggered if child_in_roi OR warning device on
                    const isWarning = log.child_in_roi || this.isOn(log.warning_device_on ?? log.warning_on);
                    const rowClass = isWarning ? 'tmc-row-warning' : 'tmc-row-clear';

                    // Status pill
                    const pillClass = isWarning ? 'warning' : 'clear';
                    const pillIcon = isWarning
                        ? '<i class="fa-solid fa-triangle-exclamation"></i>'
                        : '<i class="fa-solid fa-check"></i>';
                    const pillLabel = isWarning ? 'Warning Triggered' : 'Clear';

                    // Contextual description
                    const statusDesc = isWarning
                        ? 'Child detected in crosswalk ROI'
                        : 'Crosswalk clear · Standby';

                    // Warning device badge
                    const deviceOn = this.isOn(log.warning_device_on ?? log.warning_on);
                    const deviceClass = deviceOn ? 'active' : 'standby';
                    const deviceLabel = deviceOn ? 'ACTIVE' : 'STANDBY';

                    return `
                    <tr class="${rowClass}">
                        <td><span class="tmc-log-time">${timeStr}</span></td>
                        <td>
                            <div class="tmc-status-cell">
                                <span class="tmc-status-pill ${pillClass}">${pillIcon} ${pillLabel}</span>
                                <span class="tmc-status-desc">${statusDesc}</span>
                            </div>
                        </td>
                        <td class="tmc-device-cell">
                            <span class="tmc-device-badge ${deviceClass}">
                                <span class="tmc-device-dot"></span>
                                ${deviceLabel}
                            </span>
                        </td>
                    </tr>`;
                }

                if (isItAudit) {
                    // Consolidated status from 3 redundant columns
                    const isWarning = log.child_in_roi || this.isOn(log.warning_device_on ?? log.warning_on);
                    const isFalse = log.false_warning;

                    // Row class: false warning takes priority for amber accent
                    let rowClass = 'it-row-clear';
                    if (isFalse) rowClass = 'it-row-false-warning';
                    else if (isWarning) rowClass = 'it-row-warning';

                    // Status pill (same visual language as TMC)
                    const pillClass = isWarning ? 'warning' : 'clear';
                    const pillIcon = isWarning
                        ? '<i class="fa-solid fa-triangle-exclamation"></i>'
                        : '<i class="fa-solid fa-check"></i>';
                    const pillLabel = isWarning ? 'Warning Triggered' : 'Clear';

                    // Confidence styling — highlight if >= threshold
                    const conf = (log.confidence || 0).toFixed(2);
                    const confClass = log.confidence >= 0.65 ? 'it-mono-val it-conf-high' : 'it-mono-val';

                    // False warning badge
                    const falseHtml = isFalse
                        ? '<span class="it-false-badge yes"><i class="fa-solid fa-flag"></i> YES</span>'
                        : '<span class="it-false-badge no">NO</span>';

                    return `
                    <tr class="${rowClass}">
                        <td><span class="it-log-time">${timeStr}</span></td>
                        <td>
                            <div class="tmc-status-cell">
                                <span class="tmc-status-pill ${pillClass}">${pillIcon} ${pillLabel}</span>
                            </div>
                        </td>
                        <td style="text-align: right;"><span class="${confClass}">${conf}</span></td>
                        <td style="text-align: right;"><span class="it-mono-val">${log.latency_ms}ms</span></td>
                        <td><span class="it-scenario-tag">${log.scenario}</span></td>
                        <td style="text-align: center;">${falseHtml}</td>
                    </tr>`;
                }

                // Fallback: generic 8-column (should not normally be reached)
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
                </tr>`;
            }).join('');
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
        this.exportRawData('csv');
    },

    exportJSON() {
        this.exportRawData('json');
    },

    exportRawData(format) {
        const f = this.state.logsFilter;
        const params = new URLSearchParams({
            format: format,
            range: f.range || 'all',
            warning_only: f.warningOnly ? 'true' : 'false',
            in_roi_only: f.inRoiOnly ? 'true' : 'false',
            min_conf: f.minConf || 0,
            scenario: f.scenario || 'All'
        });

        if (f.startDate) params.set('start_date', f.startDate);
        if (f.endDate) params.set('end_date', f.endDate);
        if (f.searchText) params.set('search', f.searchText);

        const exportUrl = `/api/events/export?${params.toString()}`;
        console.debug(`[Export] Requesting full server-side streaming export: ${exportUrl}`);

        const link = document.createElement('a');
        link.href = exportUrl;
        link.style.display = 'none';
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

                // Start Polling (5s — near real-time)
                this.state.analyticsPollingTimer = setInterval(() => {
                    this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());
                }, 5000);
            } else {
                // Leaving Analytics
                if (this.state.analyticsPollingTimer) {
                    clearInterval(this.state.analyticsPollingTimer);
                    this.state.analyticsPollingTimer = null;
                }
            }

            // Hikvision: MJPEG is always-on, just ensure img src is set on return
            if (hash === 'live') {
                this.ensureLiveStream();
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

        // D) Scenario (Horizontal Bar — axes must be explicitly set
        //    because indexAxis:'y' swaps which axis is category vs value)
        const ctxS = document.getElementById('chartScenario')?.getContext('2d');
        if (ctxS) {
            this.state.charts.scenario = new Chart(ctxS, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Total Recorded Events',
                        data: [],
                        backgroundColor: ['#FF9280', '#45315D', '#6c757d', '#2196f3', '#4caf50', '#ff5722'],
                        borderRadius: 4
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 800 },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: ctx => `${ctx.parsed.x.toLocaleString()} events`
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            grid: { color: gridColor },
                            ticks: {
                                color: textColor,
                                precision: 0
                            }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { color: textColor }
                        }
                    }
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
                // Reset KPI cards to zero so stale values from the previous range don't persist
                this.renderKPIs({ total_warnings: 0, total_detections: 0, false_warnings: 0, avg_latency: 0, peak_hour: '--' });
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
        const warnEl = document.getElementById('ana-kpi-warnings');
        if (warnEl) warnEl.textContent = agg.total_warnings;

        const detEl = document.getElementById('ana-kpi-detections');
        if (detEl) detEl.textContent = agg.total_detections;

        const falseEl = document.getElementById('ana-kpi-false');
        if (falseEl) falseEl.textContent = agg.false_warnings;

        const latEl = document.getElementById('ana-kpi-latency');
        if (latEl) latEl.textContent = (agg.avg_latency || 0) + 'ms';

        const peakEl = document.getElementById('ana-kpi-peak');
        if (peakEl) peakEl.textContent = agg.peak_hour || '--';

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

        // 1. Presets — ONLY update range state and reset the sheet to "pending"
        document.querySelectorAll('.btn-preset[data-rep-range]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // UI — toggle active class
                document.querySelectorAll('.btn-preset[data-rep-range]').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                // State — store selected range
                this.state.reports.range = e.target.getAttribute('data-rep-range');

                // Clear the report sheet to indicate generation is needed
                this.resetReportSheet(e.target.textContent.trim());
            });
        });

        // 2. Actions
        document.getElementById('btnGenerateReport')?.addEventListener('click', () => {
            const btn = document.getElementById('btnGenerateReport');
            if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-rotate-right fa-spin"></i> Generating…'; }
            this.loadReportFromDB(this.state.reports.range).then(() => {
                this.generateReport();
            }).finally(() => {
                setTimeout(() => {
                    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Generate'; }
                }, 700);
            });
        });

        document.getElementById('btnPrintReport')?.addEventListener('click', () => {
            if (!this.state.reports.lastSummary) {
                alert('Please click "Generate" first to build the report.');
                return;
            }
            window.print();
        });

        document.getElementById('btnDownloadReportJSON')?.addEventListener('click', () => {
            if (!this.state.reports.lastSummary) {
                alert('Please click "Generate" first to build the report.');
                return;
            }
            this.downloadReport('json');
        });

        document.getElementById('btnDownloadReportCSV')?.addEventListener('click', () => {
            if (!this.state.reports.lastSummary) {
                alert('Please click "Generate" first to build the report.');
                return;
            }
            this.downloadReport('csv');
        });

        // No auto-generation on load — report starts in a clean pending state
    },

    // Resets the report sheet to a "pending generation" state
    resetReportSheet(rangeLabel) {
        this.state.reports.lastSummary = null;
        window.EventStore.reportAggregate = null;

        const rangeEl = document.getElementById('rep-range-label');
        if (rangeEl) rangeEl.textContent = rangeLabel || 'Today';

        const genEl = document.getElementById('rep-generated-at');
        if (genEl) genEl.textContent = '\u2014';

        const warnEl = document.getElementById('rep-total-warnings');
        if (warnEl) warnEl.textContent = '\u2014';

        const detEl = document.getElementById('rep-total-detections');
        if (detEl) detEl.textContent = '\u2014';

        const falseEl = document.getElementById('rep-false-warnings');
        if (falseEl) falseEl.textContent = '\u2014';

        const latEl = document.getElementById('rep-avg-latency');
        if (latEl) latEl.textContent = '\u2014';

        const peakEl = document.getElementById('rep-peak-hour');
        if (peakEl) peakEl.textContent = '\u2014';

        const list = document.getElementById('rep-insights-list');
        if (list) {
            list.innerHTML = '<li>Select a time range and click <strong>Generate</strong> to build the report.</li>';
        }
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

        // Professional qualitative insights
        const insights = [];
        if (agg.total_events === 0) {
            insights.push('No events were recorded during this period. The system was operational but no pedestrian activity was detected in the monitored crosswalk zone.');
        } else {
            // Safety impact
            if (totalWarnings > 0) {
                insights.push(`The system successfully facilitated <strong>${totalWarnings}</strong> active safety intervention${totalWarnings > 1 ? 's' : ''}, triggering visual alerts for child pedestrians detected in the crosswalk zone.`);
            } else {
                insights.push('No warning activations were recorded during this period, indicating no child pedestrian entries were detected within the active ROI zone.');
            }

            // Accuracy / false warning rate
            if (totalWarnings > 0) {
                const falseRate = ((falseWarnings / totalWarnings) * 100).toFixed(1);
                if (parseFloat(falseRate) <= 10) {
                    insights.push(`System classification reliability is <strong>high</strong> — false warning rate stands at ${falseRate}%, well within acceptable prototype operating parameters.`);
                } else {
                    insights.push(`A false warning rate of <strong>${falseRate}%</strong> was recorded. This is within standard prototype operating variance; continued dataset refinement is recommended for production deployment.`);
                }
            }

            // Peak risk interval
            if (peakHour !== '--') {
                insights.push(`A <strong>Critical Risk Interval</strong> was identified at <strong>${peakHour}</strong> — representing the period of highest crosswalk utilization requiring the greatest driver and pedestrian vigilance.`);
            }
        }

        const summary = {
            rangeLabel: document.querySelector(`.btn-preset[data-rep-range="${range}"]`)?.textContent?.trim() || range,
            generatedAt: new Date().toLocaleString(undefined, { 
                year: 'numeric', month: 'numeric', day: 'numeric', 
                hour: 'numeric', minute: 'numeric', second: 'numeric' 
            }),
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
        // Update DOM elements directly with null-safe checks
        const rangeEl = document.getElementById('rep-range-label');
        if (rangeEl) rangeEl.textContent = summary.rangeLabel;

        const genEl = document.getElementById('rep-generated-at');
        if (genEl) genEl.textContent = summary.generatedAt;

        const warnEl = document.getElementById('rep-total-warnings');
        if (warnEl) warnEl.textContent = summary.totalWarnings;

        const detEl = document.getElementById('rep-total-detections');
        if (detEl) detEl.textContent = summary.totalDetections;

        const falseEl = document.getElementById('rep-false-warnings');
        if (falseEl) falseEl.textContent = summary.falseWarnings;

        const latEl = document.getElementById('rep-avg-latency');
        if (latEl) latEl.textContent = summary.avgLatency + 'ms';

        const peakEl = document.getElementById('rep-peak-hour');
        if (peakEl) peakEl.textContent = summary.peakHour;

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
            const row = `${s.generatedAt},${s.rangeLabel},${s.totalWarnings},${s.totalDetections},${s.falseWarnings},${s.avgLatency}ms,${s.peakHour},${s.metrics.mostCommonScenario},"Casisang Central School","TMC","IoT-Based Smart Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection"`;
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
        const canvas = document.getElementById('roiCanvas');
        const fileInput = document.getElementById('roiImageInput');
        const overlay = document.getElementById('roiOverlayText');
        const wrapper = document.getElementById('roiWrapper');

        if (!canvas) return;

        this.ctx = canvas.getContext('2d');
        this.roiState = {
            img: null,
            // Interaction mode: 'none' | 'drawing' | 'moving' | 'resizing'
            mode: 'none',
            // For drawing
            startX: 0, startY: 0,
            // For moving
            moveOffsetX: 0, moveOffsetY: 0,
            // For resizing — which handle is being dragged
            resizeHandle: null, // 'nw','n','ne','e','se','s','sw','w'
            resizeStartRoi: null, // snapshot of ROI at drag-start
            resizeStartMouse: null, // mouse position at drag-start
        };

        // Undo/Redo history stack (max 30 entries)
        this.roiHistory = [];
        this.roiHistoryIndex = -1;
        this.ROI_HISTORY_MAX = 30;


        // Handle size in canvas pixels (scaled visually later)
        this.HANDLE_SIZE = 8;
        this.HANDLE_HIT = 14; // Hit area slightly larger than visual

        // Load saved image
        const savedImgData = localStorage.getItem('roiImageData');
        if (savedImgData) {
            this.loadImageToCanvas(savedImgData);
        } else {
            overlay.style.display = 'block';
            canvas.style.display = 'none';
        }

        // Sync ROI from server
        fetch('/api/roi').then(r => r.json()).then(j => {
            if (j.ok && j.roi) {
                const sr = j.roi;
                if (sr.polygon) {
                    // New polygon format
                    this.state.roi = sr.polygon.map(p => ({x: p.x, y: p.y}));
                } else {
                    // Legacy rect → convert to 4-point polygon
                    this.state.roi = [
                        {x: sr.x1, y: sr.y1}, {x: sr.x2, y: sr.y1},
                        {x: sr.x2, y: sr.y2}, {x: sr.x1, y: sr.y2}
                    ];
                }
                localStorage.setItem('roiImageMeta', JSON.stringify({ width: sr.image_w, height: sr.image_h }));
                localStorage.setItem('roiRect', JSON.stringify(this.state.roi));
                this.roiDirty = false;
                this.drawRoi();
                this.updateRoiCoords(this.state.roi);
                this.updateRoiSteps();
            }
        }).catch(() => {
            const savedRect = localStorage.getItem('roiRect');
            if (savedRect) {
                this.state.roi = JSON.parse(savedRect);
                this.drawRoi();
                this.updateRoiCoords(this.state.roi);
                this.updateRoiSteps();
            }
        });

        // --- File Input ---
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files[0]) {
                const reader = new FileReader();
                reader.onload = (evt) => {
                    this.state.roi = null;
                    this.roiHistory = [];
                    this.roiHistoryIndex = -1;
                    this.updateUndoRedoButtons();
                    this.loadImageToCanvas(evt.target.result);
                    this.roiDirty = true;
                    this.updateRoiSteps();
                    e.target.value = '';
                };
                reader.readAsDataURL(e.target.files[0]);
            }
        });

        // --- Canvas Mouse Events ---
        canvas.addEventListener('mousedown', (e) => this._roiMouseDown(e, canvas));
        canvas.addEventListener('mousemove', (e) => this._roiMouseMove(e, canvas));
        canvas.addEventListener('mouseup', (e) => this._roiMouseUp(e, canvas));
        canvas.addEventListener('mouseleave', (e) => this._roiMouseUp(e, canvas));

        // --- Touch Events (mobile support) ---
        canvas.addEventListener('touchstart', (e) => {
            e.preventDefault();
            this._roiMouseDown(this._touchToMouse(e), canvas);
        }, { passive: false });
        canvas.addEventListener('touchmove', (e) => {
            e.preventDefault();
            this._roiMouseMove(this._touchToMouse(e), canvas);
        }, { passive: false });
        canvas.addEventListener('touchend', (e) => {
            e.preventDefault();
            this._roiMouseUp(this._touchToMouse(e), canvas);
        }, { passive: false });

        // --- Buttons ---
        document.getElementById('btnSaveRoi')?.addEventListener('click', () => this.saveRoi());
        document.getElementById('btnResetRoi')?.addEventListener('click', () => this.resetRoi());

        // --- Undo/Redo Toolbar Buttons ---
        document.getElementById('btnRoiUndo')?.addEventListener('click', () => this.roiUndo());
        document.getElementById('btnRoiRedo')?.addEventListener('click', () => this.roiRedo());


        // --- Keyboard Shortcuts ---
        document.addEventListener('keydown', (e) => {
            // Only listen when the ROI config page is visible
            const roiSection = document.getElementById('roiWrapper');
            if (!roiSection || roiSection.offsetParent === null) return;

            if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
                e.preventDefault();
                this.roiUndo();
            } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
                e.preventDefault();
                this.roiRedo();
            }
        });

        // --- Capture Frame ---
        document.getElementById('btnCaptureFrame')?.addEventListener('click', async () => {
            const btn = document.getElementById('btnCaptureFrame');
            if (btn) btn.disabled = true;

            if (!window.CameraState.isConnected) {
                alert("Camera is not connected. Please wait for the stream to connect.");
                if (btn) btn.disabled = false;
                return;
            }

            try {
                const res = await fetch('/api/camera/snapshot?t=' + Date.now());
                if (!res.ok) throw new Error(`Snapshot failed: ${res.status}`);
                const blob = await res.blob();
                const dataUrl = await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
                this.state.roi = null;
                this.roiHistory = [];
                this.roiHistoryIndex = -1;
                this.updateUndoRedoButtons();
                this.loadImageToCanvas(dataUrl);
                this.roiDirty = true;
                this.updateRoiSteps();
            } catch (e) {
                console.error('[ROI] Capture failed:', e);
                alert("Failed to capture frame. Make sure the camera is online.");
            }
            if (btn) btn.disabled = false;
        });

        this.updateRoiSteps();
    },

    _touchToMouse(e) {
        const touch = e.touches[0] || e.changedTouches[0];
        return { clientX: touch.clientX, clientY: touch.clientY };
    },

    // --- Detect which handle (if any) the mouse is over ---
    _hitTestHandle(pos, roi) {
        if (!roi || !Array.isArray(roi) || roi.length < 3) return -1;
        const hs = this.HANDLE_HIT;
        for (let i = 0; i < roi.length; i++) {
            if (Math.abs(pos.x - roi[i].x) <= hs && Math.abs(pos.y - roi[i].y) <= hs) {
                return i;
            }
        }
        return -1;
    },

    _isInsideRoi(pos, roi) {
        if (!roi || !Array.isArray(roi) || roi.length < 3) return false;
        // Ray-casting point-in-polygon test
        let inside = false;
        for (let i = 0, j = roi.length - 1; i < roi.length; j = i++) {
            const xi = roi[i].x, yi = roi[i].y;
            const xj = roi[j].x, yj = roi[j].y;
            if ((yi > pos.y) !== (yj > pos.y) &&
                pos.x < (xj - xi) * (pos.y - yi) / (yj - yi) + xi) {
                inside = !inside;
            }
        }
        return inside;
    },

    _getCursorForHandle(handle) {
        return handle >= 0 ? 'move' : 'default';
    },

    _roiMouseDown(e, canvas) {
        if (!this.roiState.img) return;
        const pos = this.getCanvasCoordinates(e, canvas);

        // Capture the "before" state on the very first interaction
        // so that the first edit can be undone back to the original.
        if (this.roiHistory.length === 0 && this.state.roi) {
            this.roiHistory.push(JSON.parse(JSON.stringify(this.state.roi)));
            this.roiHistoryIndex = 0;
            this.updateUndoRedoButtons();
        }

        // Priority: handle > inside > draw new
        const handleIdx = this._hitTestHandle(pos, this.state.roi);
        if (handleIdx >= 0) {
            this.roiState.mode = 'dragging_corner';
            this.roiState.dragCornerIdx = handleIdx;
            canvas.style.cursor = 'move';
            return;
        }

        if (this._isInsideRoi(pos, this.state.roi)) {
            this.roiState.mode = 'moving';
            this.roiState.moveStart = { x: pos.x, y: pos.y };
            this.roiState.moveStartRoi = this.state.roi.map(p => ({...p}));
            canvas.style.cursor = 'grabbing';
            return;
        }

        // Draw new 4-point polygon (start as a small rectangle from click)
        // Snapshot "no ROI" as the before-state if history is empty
        if (this.roiHistory.length === 0) {
            this.roiHistory.push(null);
            this.roiHistoryIndex = 0;
        }
        this.roiState.mode = 'drawing';
        this.roiState.startX = pos.x;
        this.roiState.startY = pos.y;
        this.state.roi = [
            {x: pos.x, y: pos.y}, {x: pos.x, y: pos.y},
            {x: pos.x, y: pos.y}, {x: pos.x, y: pos.y}
        ];
        this.drawRoi();
    },

    _roiMouseMove(e, canvas) {
        if (!this.roiState.img) return;
        const pos = this.getCanvasCoordinates(e, canvas);

        if (this.roiState.mode === 'drawing') {
            // Expand rectangle from start point
            const sx = this.roiState.startX;
            const sy = this.roiState.startY;
            this.state.roi = [
                {x: sx, y: sy}, {x: pos.x, y: sy},
                {x: pos.x, y: pos.y}, {x: sx, y: pos.y}
            ];
            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
            return;
        }

        if (this.roiState.mode === 'dragging_corner') {
            const idx = this.roiState.dragCornerIdx;
            this.state.roi[idx] = { x: pos.x, y: pos.y };
            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
            return;
        }

        if (this.roiState.mode === 'moving') {
            const dx = pos.x - this.roiState.moveStart.x;
            const dy = pos.y - this.roiState.moveStart.y;
            this.state.roi = this.roiState.moveStartRoi.map(p => ({
                x: p.x + dx, y: p.y + dy
            }));
            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
            return;
        }

        // Hover cursor
        const handleIdx = this._hitTestHandle(pos, this.state.roi);
        if (handleIdx >= 0) {
            canvas.style.cursor = this._getCursorForHandle(handleIdx);
        } else if (this._isInsideRoi(pos, this.state.roi)) {
            canvas.style.cursor = 'grab';
        } else {
            canvas.style.cursor = 'crosshair';
        }
    },

    _roiMouseUp(e, canvas) {
        const wasInteracting = this.roiState.mode !== 'none';
        if (wasInteracting) {
            this.roiState.mode = 'none';
            this.normalizeRoi();
            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
            // Push state to history for undo/redo
            this.pushRoiHistory();
            // Mark dirty
            this.roiDirty = true;
            const ub = document.getElementById('roiUnsavedBadge');
            if (ub) ub.style.display = 'inline-flex';
            this.updateRoiSteps();
            canvas.style.cursor = 'crosshair';
        }
    },

    loadImageToCanvas(dataUrl) {
        const img = new Image();
        img.onload = () => {
            this.roiState.img = img;
            const canvas = document.getElementById('roiCanvas');
            const overlay = document.getElementById('roiOverlayText');
            const wrapper = document.getElementById('roiWrapper');

            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            // Clear any stale CSS transform/width from previous zoom session
            canvas.style.transform = '';
            canvas.style.width = '';
            canvas.style.height = '';
            canvas.style.display = 'block';
            overlay.style.display = 'none';
            if (wrapper) {
                wrapper.classList.add('has-image');
                wrapper.classList.remove('zoomed', 'hand-tool', 'panning');
            }

            this.drawRoi();
            this.updateRoiCoords(this.state.roi);
            this.updateRoiSteps();
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

    // ---------------------------------------------------------------
    // Undo / Redo
    // ---------------------------------------------------------------
    pushRoiHistory() {
        if (!this.state.roi) return;
        const snapshot = JSON.parse(JSON.stringify(this.state.roi));
        // Truncate any redo branch ahead of current index
        if (this.roiHistoryIndex < this.roiHistory.length - 1) {
            this.roiHistory = this.roiHistory.slice(0, this.roiHistoryIndex + 1);
        }
        this.roiHistory.push(snapshot);
        // Cap at max size
        if (this.roiHistory.length > this.ROI_HISTORY_MAX) {
            this.roiHistory.shift();
        }
        this.roiHistoryIndex = this.roiHistory.length - 1;
        this.updateUndoRedoButtons();
    },

    roiUndo() {
        if (this.roiHistoryIndex <= 0) return;
        this.roiHistoryIndex--;
        const snapshot = this.roiHistory[this.roiHistoryIndex];
        this.state.roi = snapshot ? JSON.parse(JSON.stringify(snapshot)) : null;
        this.roiDirty = true;
        this.drawRoi();
        this.updateRoiCoords(this.state.roi);
        this.updateRoiSteps();
        this.updateUndoRedoButtons();
        const ub = document.getElementById('roiUnsavedBadge');
        if (ub) ub.style.display = 'inline-flex';
    },

    roiRedo() {
        if (this.roiHistoryIndex >= this.roiHistory.length - 1) return;
        this.roiHistoryIndex++;
        this.state.roi = JSON.parse(JSON.stringify(this.roiHistory[this.roiHistoryIndex]));
        this.roiDirty = true;
        this.drawRoi();
        this.updateRoiCoords(this.state.roi);
        this.updateRoiSteps();
        this.updateUndoRedoButtons();
        const ub = document.getElementById('roiUnsavedBadge');
        if (ub) ub.style.display = 'inline-flex';
    },

    updateUndoRedoButtons() {
        const undoBtn = document.getElementById('btnRoiUndo');
        const redoBtn = document.getElementById('btnRoiRedo');
        if (undoBtn) undoBtn.disabled = this.roiHistoryIndex <= 0;
        if (redoBtn) redoBtn.disabled = this.roiHistoryIndex >= this.roiHistory.length - 1;
    },

    normalizeRoi() {
        if (!this.state.roi || !Array.isArray(this.state.roi)) return;
        const img = this.roiState.img;
        if (img) {
            this.state.roi = this.state.roi.map(p => ({
                x: Math.max(0, Math.min(p.x, img.naturalWidth)),
                y: Math.max(0, Math.min(p.y, img.naturalHeight))
            }));
        }
    },

    drawRoi() {
        const ctx = this.ctx;
        const canvas = document.getElementById('roiCanvas');
        const img = this.roiState.img;
        const roi = this.state.roi;
        if (!ctx || !canvas) return;

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (img) ctx.drawImage(img, 0, 0);

        if (roi && Array.isArray(roi) && roi.length >= 3) {
            const isDraft = !!this.roiDirty;
            const fillColor = isDraft ? 'rgba(239, 68, 68, 0.18)' : 'rgba(34, 197, 94, 0.18)';
            const strokeColor = isDraft ? '#ef4444' : '#22c55e';
            const handleColor = isDraft ? '#dc2626' : '#16a34a';

            // Dim outside region, cut out polygon
            ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            // Cut out polygon area
            ctx.save();
            ctx.beginPath();
            ctx.moveTo(roi[0].x, roi[0].y);
            for (let i = 1; i < roi.length; i++) ctx.lineTo(roi[i].x, roi[i].y);
            ctx.closePath();
            ctx.globalCompositeOperation = 'destination-out';
            ctx.fill();
            ctx.restore();
            // Redraw image inside polygon
            if (img) {
                ctx.save();
                ctx.beginPath();
                ctx.moveTo(roi[0].x, roi[0].y);
                for (let i = 1; i < roi.length; i++) ctx.lineTo(roi[i].x, roi[i].y);
                ctx.closePath();
                ctx.clip();
                ctx.drawImage(img, 0, 0);
                ctx.restore();
            }

            // Polygon fill
            ctx.beginPath();
            ctx.moveTo(roi[0].x, roi[0].y);
            for (let i = 1; i < roi.length; i++) ctx.lineTo(roi[i].x, roi[i].y);
            ctx.closePath();
            ctx.fillStyle = fillColor;
            ctx.fill();

            // Polygon border
            ctx.beginPath();
            ctx.moveTo(roi[0].x, roi[0].y);
            for (let i = 1; i < roi.length; i++) ctx.lineTo(roi[i].x, roi[i].y);
            ctx.closePath();
            ctx.strokeStyle = strokeColor;
            ctx.lineWidth = 3;
            ctx.setLineDash([]);
            ctx.stroke();

            // Label
            const minX = Math.min(...roi.map(p => p.x));
            const minY = Math.min(...roi.map(p => p.y));
            const label = isDraft ? 'DRAFT ROI (drag corners)' : 'ACTIVE ROI';
            ctx.font = 'bold 14px Manrope, sans-serif';
            const labelX = minX + 8;
            const labelY = minY > 24 ? minY - 8 : minY + 20;
            const tm = ctx.measureText(label);
            ctx.fillStyle = 'rgba(0,0,0,0.6)';
            ctx.fillRect(labelX - 3, labelY - 13, tm.width + 6, 17);
            ctx.fillStyle = strokeColor;
            ctx.fillText(label, labelX, labelY);

            // Draw 4 corner handles (circles)
            const hs = this.HANDLE_SIZE;
            roi.forEach((p, i) => {
                ctx.beginPath();
                ctx.arc(p.x, p.y, hs + 2, 0, Math.PI * 2);
                ctx.fillStyle = '#fff';
                ctx.fill();
                ctx.strokeStyle = handleColor;
                ctx.lineWidth = 2.5;
                ctx.stroke();
                // Corner number
                ctx.fillStyle = handleColor;
                ctx.font = 'bold 10px Manrope, sans-serif';
                ctx.fillText(String(i + 1), p.x - 3, p.y + 3);
            });
        }

        // Update status badge
        this.updateRoiStatusBadge();
    },

    updateRoiStatusBadge() {
        const badge = document.getElementById('roiStatusBadge');
        if (!badge) return;
        const roi = this.state.roi;
        if (!roi || !Array.isArray(roi) || roi.length < 3) {
            badge.className = 'roi-status-badge roi-status-none';
            badge.innerHTML = '<i class="fa-solid fa-circle-xmark"></i> No ROI Defined';
        } else if (this.roiDirty) {
            badge.className = 'roi-status-badge roi-status-draft';
            badge.innerHTML = '<i class="fa-solid fa-pen"></i> Draft (Unsaved)';
        } else {
            badge.className = 'roi-status-badge roi-status-active';
            badge.innerHTML = '<i class="fa-solid fa-circle-check"></i> Active (Saved)';
        }
    },

    updateRoiSteps() {
        const s1 = document.getElementById('roiStep1');
        const s2 = document.getElementById('roiStep2');
        const s3 = document.getElementById('roiStep3');
        if (!s1 || !s2 || !s3) return;

        const hasImage = !!this.roiState.img;
        const hasRoi = !!(this.state.roi && Array.isArray(this.state.roi) && this.state.roi.length >= 3);
        const isSaved = hasRoi && !this.roiDirty;

        // Step 1
        s1.className = hasImage ? 'roi-step done' : 'roi-step active';
        // Step 2
        s2.className = hasImage ? (hasRoi ? 'roi-step done' : 'roi-step active') : 'roi-step';
        // Step 3
        s3.className = isSaved ? 'roi-step done' : (hasRoi ? 'roi-step active' : 'roi-step');
    },

    updateRoiCoords(roi) {
        // Display polygon corner coordinates
        const coordsEl = document.getElementById('roiX');
        if (coordsEl) {
            if (roi && Array.isArray(roi) && roi.length >= 3) {
                const txt = roi.map((p, i) => `P${i+1}(${Math.round(p.x)},${Math.round(p.y)})`).join('  ');
                coordsEl.textContent = txt;
            } else {
                coordsEl.textContent = 'No ROI';
            }
        }
        // Hide legacy fields that may not exist
        ['Y', 'W', 'H'].forEach(k => {
            const el = document.getElementById('roi' + k);
            if (el) el.textContent = '';
        });
        if (this.roiState.img) {
            const elW = document.getElementById('roiImgW');
            const elH = document.getElementById('roiImgH');
            if (elW) elW.textContent = this.roiState.img.naturalWidth;
            if (elH) elH.textContent = this.roiState.img.naturalHeight;
        }
    },

    async saveRoiToServer(roiPoly, roiImageMeta) {
        const image_w = Math.round(roiImageMeta?.width ?? roiImageMeta?.image_w ?? 0);
        const image_h = Math.round(roiImageMeta?.height ?? roiImageMeta?.image_h ?? 0);

        // Send polygon format
        const polygon = roiPoly.map(p => ({x: Math.round(p.x), y: Math.round(p.y)}));
        const payload = { polygon, image_w, image_h };
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
            if (!res.ok || !j.ok) throw new Error(j.error || `HTTP ${res.status}`);
        } catch (e) {
            clearTimeout(timeoutId);
            if (e.name === 'AbortError') throw new Error('Server did not respond in time (10s).');
            throw e;
        }
    },

    async saveRoi() {
        if (!this.state.roi) {
            alert("No ROI defined. Draw a region first.");
            return;
        }

        const btn = document.getElementById('btnSaveRoi');
        const oldHTML = btn ? btn.innerHTML : '';

        try {
            localStorage.setItem('roiRect', JSON.stringify(this.state.roi));
            if (this.roiState.img && this.roiState.img.src.startsWith('data:')) {
                localStorage.setItem('roiImageData', this.roiState.img.src);
            }

            let meta = null;
            if (this.roiState.img) {
                meta = { width: this.roiState.img.naturalWidth, height: this.roiState.img.naturalHeight };
                localStorage.setItem('roiImageMeta', JSON.stringify(meta));
            } else {
                meta = JSON.parse(localStorage.getItem('roiImageMeta') || "{}");
            }

            if (btn) {
                btn.classList.remove('btn-saved', 'btn-error');
                btn.classList.add('btn-saving');
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
            }

            await this.saveRoiToServer(this.state.roi, meta);

            if (btn) {
                btn.classList.remove('btn-saving');
                btn.classList.add('btn-saved');
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Saved \u2713';
                setTimeout(() => { btn.classList.remove('btn-saved'); btn.innerHTML = oldHTML; }, 1200);
            }

            this.roiDirty = false;
            this.drawRoi();
            const ub = document.getElementById('roiUnsavedBadge');
            if (ub) ub.style.display = 'none';
            this.updateRoiSteps();

            if (!this.socket || !this.socket.connected) {
                this.updateLiveRoiBadge();
            }

        } catch (e) {
            console.error("[ROI] Save error:", e);
            if (btn) {
                btn.classList.remove('btn-saving');
                btn.classList.add('btn-error');
                btn.innerHTML = '<i class="fa-solid fa-xmark"></i> Save failed';
                setTimeout(() => { btn.classList.remove('btn-error'); btn.innerHTML = oldHTML; }, 1800);
            }
            if (e.name === 'QuotaExceededError') {
                alert("Error: Image is too large. Please use a smaller image.");
            }
        }
    },

    resetRoi() {
        if (!confirm("Clear the ROI and image? This cannot be undone.")) return;
        this.state.roi = null;
        this.roiState.img = null;

        localStorage.removeItem('roiRect');
        localStorage.removeItem('roiImageData');
        localStorage.removeItem('roiImageMeta');

        this.drawRoi();
        const canvas = document.getElementById('roiCanvas');
        const overlay = document.getElementById('roiOverlayText');
        const wrapper = document.getElementById('roiWrapper');
        if (canvas) canvas.style.display = 'none';
        if (overlay) overlay.style.display = 'block';
        if (wrapper) wrapper.classList.remove('has-image');
        this.updateRoiCoords(null);
        document.getElementById('roiImgW').textContent = '0';
        document.getElementById('roiImgH').textContent = '0';
        this.updateRoiSteps();
    },


    // ---------------------------------------------------------
    // Legacy / Shared
    // ---------------------------------------------------------

    // ---------------------------------------------------------
    // VIDEO TEST MODE — Mode switching, upload, video library
    // ---------------------------------------------------------

    initVideoTestMode() {
        // Mode toggle buttons
        document.getElementById('btnModeLive')?.addEventListener('click', () => {
            this.switchMode('live');
        });
        document.getElementById('btnModeTest')?.addEventListener('click', () => {
            // If already in test mode, just show panel
            if (window.AppMode.current === 'video_test') return;
            // Show the video test panel so user can select a video
            const panel = document.getElementById('videoTestPanel');
            if (panel) panel.style.display = 'block';
            this.loadTestVideos();
            // Update toggle buttons visually (but don't switch mode yet — user picks a video)
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('btnModeTest')?.classList.add('active');
        });


        // Collapse/expand toggle for video test content
        document.getElementById('videoTestHeader')?.addEventListener('click', () => {
            const content = document.getElementById('videoTestContent');
            const icon = document.getElementById('videoTestCollapseIcon');
            if (content && icon) {
                content.classList.toggle('collapsed');
                icon.classList.toggle('collapsed');
            }
        });

        // Upload dropzone
        const dropzone = document.getElementById('uploadDropzone');
        const fileInput = document.getElementById('videoFileInput');

        if (dropzone && fileInput) {
            dropzone.addEventListener('click', () => fileInput.click());

            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropzone.classList.add('drag-over');
            });

            dropzone.addEventListener('dragleave', () => {
                dropzone.classList.remove('drag-over');
            });

            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('drag-over');
                const files = e.dataTransfer?.files;
                if (files && files.length > 0) {
                    this.uploadTestVideo(files[0]);
                }
            });

            fileInput.addEventListener('change', (e) => {
                if (e.target.files && e.target.files.length > 0) {
                    this.uploadTestVideo(e.target.files[0]);
                    e.target.value = ''; // reset for re-upload of same file
                }
            });
        }

        // Refresh button
        document.getElementById('btnRefreshVideos')?.addEventListener('click', () => {
            this.loadTestVideos();
        });

        // Fetch initial mode from server
        fetch('/api/mode')
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    this.handleModeUpdate(data);
                }
            })
            .catch(() => {});
    },

    handleModeUpdate(data) {
        const mode = data?.mode || 'live';
        const prevMode = window.AppMode.current;
        const prevVideo = window.AppMode.testVideoFile;
        window.AppMode.current = mode;
        window.AppMode.testVideoFile = data?.video_filename || null;
        window.AppMode.switching = false;
        this.updateModeUI();

        // If mode or test video changed, re-bind the MJPEG stream
        if (prevMode !== mode || prevVideo !== window.AppMode.testVideoFile) {
            setTimeout(() => this.connectLiveStream(), 300);
        }
    },

    async switchMode(targetMode, filename) {
        if (window.AppMode.switching) return;
        if (targetMode === window.AppMode.current && targetMode === 'live') return;

        window.AppMode.switching = true;

        // Show switching state
        const badge = document.getElementById('modeBadge');
        if (badge) {
            badge.className = 'mode-badge';
            badge.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Switching...';
        }

        try {
            let res;
            if (targetMode === 'live') {
                res = await fetch('/api/mode/live', { method: 'POST' });
            } else {
                res = await fetch('/api/mode/video_test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename }),
                });
            }

            const data = await res.json();
            if (data.ok) {
                window.AppMode.current = data.mode;
                window.AppMode.testVideoFile = data.video_filename || null;

                // Reconnect the MJPEG stream to pick up new source
                setTimeout(() => this.connectLiveStream(), 500);
            } else {
                console.error('[Mode] Switch failed:', data.error);
                alert(`Mode switch failed: ${data.error}`);
            }
        } catch (e) {
            console.error('[Mode] Switch error:', e);
        }

        window.AppMode.switching = false;
        this.updateModeUI();
    },

    async loadTestVideos() {
        try {
            const res = await fetch('/api/test_videos');
            const data = await res.json();
            if (data.ok) {
                window.AppMode.availableVideos = data.videos || [];
                this.renderVideoGrid();
            }
        } catch (e) {
            console.warn('[VideoTest] Failed to load videos:', e);
        }
    },

    renderVideoGrid() {
        const grid = document.getElementById('videoGrid');
        if (!grid) return;

        const videos = window.AppMode.availableVideos;
        if (videos.length === 0) {
            grid.innerHTML = `
                <div class="video-empty-state">
                    <i class="fa-solid fa-video-slash"></i>
                    <p>No test videos yet. Upload an .mp4 file above.</p>
                </div>
            `;
            return;
        }

        grid.innerHTML = videos.map(v => {
            const isActive = window.AppMode.current === 'video_test' && window.AppMode.testVideoFile === v.filename;
            const dur = v.duration_sec ? `${Math.floor(v.duration_sec / 60)}m ${Math.floor(v.duration_sec % 60)}s` : '—';

            return `
                <div class="video-card ${isActive ? 'active' : ''}" data-filename="${v.filename}">
                    <div class="video-card-name">
                        <i class="fa-solid fa-file-video"></i>
                        ${v.filename}
                    </div>
                    <div class="video-card-meta">
                        <span><i class="fa-solid fa-clock"></i> ${dur}</span>
                        <span><i class="fa-solid fa-weight-hanging"></i> ${v.size_mb} MB</span>
                        ${v.resolution ? `<span><i class="fa-solid fa-expand"></i> ${v.resolution}</span>` : ''}
                        ${v.fps ? `<span><i class="fa-solid fa-gauge-high"></i> ${v.fps} fps</span>` : ''}
                    </div>
                    <button class="btn-play" onclick="App.switchMode('video_test', '${v.filename}')">
                        ${isActive ? '<i class="fa-solid fa-circle-play"></i> Playing' : '<i class="fa-solid fa-play"></i> Play'}
                    </button>
                </div>
            `;
        }).join('');
    },

    async uploadTestVideo(file) {
        if (!file) return;

        if (!file.name.toLowerCase().endsWith('.mp4')) {
            alert('Only .mp4 files are accepted.');
            return;
        }

        const dropContent = document.querySelector('.dropzone-content');
        const progress = document.getElementById('uploadProgress');
        const progressText = document.getElementById('uploadProgressText');

        // Show progress
        if (dropContent) dropContent.style.display = 'none';
        if (progress) progress.style.display = 'flex';
        if (progressText) progressText.textContent = `Uploading ${file.name}...`;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/test_videos/upload', {
                method: 'POST',
                body: formData,
            });
            const data = await res.json();

            if (data.ok) {
                console.log(`[Upload] Success: ${data.filename} (${data.size_mb} MB)`);
                if (progressText) progressText.textContent = `✓ Uploaded ${data.filename}`;
                setTimeout(() => {
                    if (dropContent) dropContent.style.display = 'block';
                    if (progress) progress.style.display = 'none';
                }, 2000);
                // Refresh library
                this.loadTestVideos();
            } else {
                throw new Error(data.error || 'Upload failed');
            }
        } catch (e) {
            console.error('[Upload] Error:', e);
            if (progressText) progressText.textContent = `✗ Failed: ${e.message}`;
            setTimeout(() => {
                if (dropContent) dropContent.style.display = 'block';
                if (progress) progress.style.display = 'none';
            }, 3000);
        }
    },

    updateModeUI() {
        const mode = window.AppMode.current;
        const isTest = mode === 'video_test';

        // Toggle buttons
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // Mode badge
        const badge = document.getElementById('modeBadge');
        if (badge) {
            if (isTest) {
                badge.className = 'mode-badge mode-test';
                const name = window.AppMode.testVideoFile || 'No video';
                badge.innerHTML = `<i class="fa-solid fa-film"></i> Test: ${name}`;
            } else {
                badge.className = 'mode-badge mode-live';
                badge.innerHTML = '<i class="fa-solid fa-circle"></i> Live';
            }
        }


        // Video test panel visibility
        const panel = document.getElementById('videoTestPanel');
        if (panel) {
            panel.style.display = isTest ? 'block' : 'none';
            if (isTest) this.loadTestVideos();
        }

        // Camera card title
        const camTitle = document.getElementById('cameraCardTitle');
        if (camTitle) {
            if (isTest && window.AppMode.testVideoFile) {
                camTitle.textContent = `Video Test Simulation — ${window.AppMode.testVideoFile}`;
            } else {
                camTitle.textContent = 'Live Camera View';
            }
        }

        // Update video grid active states
        this.renderVideoGrid();
    },

    // ---------------------------------------------------------
    // Hikvision Camera — Auto-connect (no manual controls)
    // ---------------------------------------------------------

    buildVideoFeedUrl(useOverlay) {
        const params = new URLSearchParams();
        params.set('overlay', useOverlay ? '1' : '0');
        return '/video_feed?' + params.toString();
    },

    initCamera() {
        // AI Overlay toggle
        document.getElementById('debugOverlayToggle')?.addEventListener('change', (e) => {
            if (window.CameraState.isConnected) {
                const img = document.getElementById('liveCam');
                if (img) img.src = this.buildVideoFeedUrl(e.target.checked) + '&t=' + Date.now();
            }
        });
        const overlayToggle = document.getElementById('debugOverlayToggle');
        if (overlayToggle) overlayToggle.checked = true;

        // Reconnect button — smart behavior based on current state
        document.getElementById('btnReconnect')?.addEventListener('click', async () => {
            const btn = document.getElementById('btnReconnect');
            if (btn) btn.disabled = true;

            try {
                if (window.CameraState.isConnected) {
                    // Camera is already online — seamless refresh (no spinner)
                    console.log('[Camera] Soft refresh (camera already online)');
                    const img = document.getElementById('liveCam');
                    if (img) {
                        const useOverlay = !!document.getElementById('debugOverlayToggle')?.checked;
                        img.src = this.buildVideoFeedUrl(useOverlay) + '&t=' + Date.now();
                    }
                } else {
                    // Camera is offline — ask backend to force reconnect
                    console.log('[Camera] Requesting backend reconnect...');
                    await fetch('/api/camera/reconnect', { method: 'POST' });
                    // Wait for backend to re-establish RTSP, then reconnect MJPEG
                    setTimeout(() => this.connectLiveStream(), 2000);
                }
            } catch (e) {
                console.warn('[Camera] Reconnect failed:', e);
                this.connectLiveStream();
            }

            // Re-enable button after 3s to prevent spam
            setTimeout(() => { if (btn) btn.disabled = false; }, 3000);
        });

        // SocketIO camera_status listener
        if (this.socket) {
            this.socket.on('camera_status', (data) => {
                window.CameraState.lastStatus = data;
                this.updateSystemStatusPanel(data);
            });
        }

        // Auto-connect on init
        this.connectLiveStream();

        // Poll camera status every 2s
        window.CameraState.statusPollTimer = setInterval(() => this.pollCameraStatus(), 2000);
    },

    connectLiveStream() {
        const img = document.getElementById('liveCam');
        const ph = document.getElementById('camPlaceholder');
        if (!img) return;

        // Cancel any pending reconnect timer
        clearTimeout(window.CameraState.reconnectTimer);
        window.CameraState.reconnectTimer = null;

        // Cancel any pending load timeout
        clearTimeout(window.CameraState._loadTimeout);
        window.CameraState._loadTimeout = null;

        // Clean up old handlers to prevent ghost callbacks
        img.onload = null;
        img.onerror = null;
        img.src = '';

        // Show connecting state
        if (ph) {
            ph.style.display = 'flex';
            ph.innerHTML = `
                <div style="font-size: 2rem; margin-bottom: 10px; color: #ccc;">
                    <i class="fa-solid fa-spinner fa-spin"></i>
                </div>
                <p><strong>Connecting to CCTV...</strong><br>Waiting for Hikvision stream.</p>
            `;
        }
        img.style.display = 'none';
        window.CameraState.isConnected = false;

        const useOverlay = !!document.getElementById('debugOverlayToggle')?.checked;
        const connectToken = Date.now();
        window.CameraState._connectToken = connectToken;

        // SUCCESS: first MJPEG frame arrived
        img.onload = () => {
            if (window.CameraState._connectToken !== connectToken) return;
            clearTimeout(window.CameraState._loadTimeout);
            window.CameraState.isConnected = true;
            window.CameraState.isReconnecting = false;
            img.style.display = 'block';
            if (ph) ph.style.display = 'none';
            this.updateLiveRoiBadge();
            console.log('[Camera] Hikvision stream connected');
        };

        // ERROR: HTTP connection failed (server down, 503, etc.)
        img.onerror = () => {
            if (window.CameraState._connectToken !== connectToken) return;
            clearTimeout(window.CameraState._loadTimeout);
            this._handleStreamError();
        };

        // TIMEOUT: HTTP connection open but no frame data (the core bug fix)
        window.CameraState._loadTimeout = setTimeout(() => {
            if (window.CameraState._connectToken !== connectToken) return;
            if (window.CameraState.isConnected) return; // Already loaded, ignore
            console.warn('[Camera] Load timeout (8s) — no frame received, retrying');
            img.onload = null;
            img.onerror = null;
            img.src = '';  // Kill the hung MJPEG connection
            this._handleStreamError();
        }, 8000);

        // Start the MJPEG stream
        img.src = this.buildVideoFeedUrl(useOverlay) + '&t=' + connectToken;
    },

    _handleStreamError() {
        const img = document.getElementById('liveCam');
        const ph = document.getElementById('camPlaceholder');

        window.CameraState.isConnected = false;
        if (img) img.style.display = 'none';

        // Show reconnecting UI (only update once to avoid flicker)
        if (!window.CameraState.isReconnecting) {
            window.CameraState.isReconnecting = true;
            if (ph) {
                ph.style.display = 'flex';
                ph.innerHTML = `
                    <div style="font-size: 2rem; margin-bottom: 10px; color: #e65100;">
                        <i class="fa-solid fa-rotate-right fa-spin"></i>
                    </div>
                    <p><strong>Stream disconnected</strong><br>Reconnecting automatically...</p>
                `;
            }
        }

        // Schedule retry (single timer, no duplicates)
        clearTimeout(window.CameraState.reconnectTimer);
        window.CameraState.reconnectTimer = setTimeout(() => {
            console.log('[Camera] Auto-retry...');
            this.connectLiveStream();
        }, 3000);
    },

    ensureLiveStream() {
        const img = document.getElementById('liveCam');
        if (!img) return;
        // If MJPEG src is already set and working, do nothing
        if (img.src && img.src.includes('/video_feed') && window.CameraState.isConnected) return;
        // Otherwise reconnect
        this.connectLiveStream();
    },

    async pollCameraStatus() {
        try {
            const res = await fetch('/api/camera/status');
            if (res.ok) {
                const data = await res.json();
                window.CameraState.lastStatus = data;
                this.updateSystemStatusPanel(data);
            }
        } catch (e) {
            // Server offline — show disconnected
            this.updateSystemStatusPanel({
                camera_online: false,
                stream_connected: false,
                ai_running: false,
                ai_error: 'Server unreachable',
                reconnect_attempts: 0,
                last_frame_time: 0,
            });
        }
    },

    updateSystemStatusPanel(data) {
        if (!data) return;

        const setChip = (id, isGood, textOn, textOff) => {
            const chip = document.getElementById(id);
            if (!chip) return;
            chip.className = `status-chip ${isGood ? 'connected' : 'disconnected'}`;
            chip.innerHTML = `<div class="status-indicator"></div> ${isGood ? textOn : textOff}`;
        };

        setChip('sysStatusCamera', data.camera_online, 'Online', 'Offline');
        setChip('sysStatusStream', data.stream_connected, 'Connected', 'Disconnected');
        setChip('sysStatusAI', data.ai_running, 'Running', data.ai_error ? 'Not Loaded' : 'Stopped');

        // Relay Controller & Heartbeat
        if (data.relay_status) {
            const relayChip = document.getElementById('sysStatusRelay');
            const relayText = document.getElementById('sysStatusRelayText');
            const relayPort = document.getElementById('sysRelayPort');
            if (relayChip) {
                const isRelayConn = Boolean(data.relay_status.connected);
                relayChip.className = `status-chip ${isRelayConn ? 'connected' : 'disconnected'}`;
                if (relayText) relayText.textContent = data.relay_status.label || (isRelayConn ? 'Connected' : 'Disconnected');
                if (relayPort) relayPort.textContent = `(${data.relay_status.port || 'COM5'})`;
            }

            const hbChip = document.getElementById('sysStatusHeartbeat');
            const hbText = document.getElementById('sysStatusHeartbeatText');
            if (hbChip) {
                const isHbOk = Boolean(data.relay_status.heartbeat_ok);
                hbChip.className = `status-chip ${isHbOk ? 'connected' : 'disconnected'}`;
                if (hbText) hbText.textContent = data.relay_status.heartbeat_label || (isHbOk ? 'Responding' : 'Not Responding');
            }
        }

        // FPS & Latencies
        if (data.fps !== undefined || data.capture_fps !== undefined) {
            const liveFps = document.getElementById('live-fps');
            if (liveFps) {
                const fpsVal = ((data.fps !== undefined ? data.fps : data.capture_fps) || 0);
                liveFps.textContent = fpsVal > 0 ? fpsVal.toFixed(1) : '--';
            }
        }
        if (data.stream_latency_ms !== undefined) {
            const liveStreamLat = document.getElementById('live-stream-latency');
            if (liveStreamLat) liveStreamLat.textContent = data.stream_latency_ms + 'ms';
        }
        if (data.frame_drop_rate !== undefined) {
            const liveDrop = document.getElementById('live-drop-rate');
            if (liveDrop) {
                liveDrop.textContent = data.frame_drop_rate.toFixed(1) + '%';
                if (data.frame_drop_rate > 5.0) {
                    liveDrop.classList.add('critical');
                } else {
                    liveDrop.classList.remove('critical');
                }
            }
        }

        // Edge Compute Load
        if (data.edge_compute) {
            const cpuBar = document.getElementById('cpu-load-bar');
            const cpuVal = document.getElementById('cpu-load-val');
            const ramBar = document.getElementById('ram-load-bar');
            const ramVal = document.getElementById('ram-load-val');
            const cpuPct = Math.min(100, Math.max(0, data.edge_compute.cpu_percent || 0));
            const ramPct = Math.min(100, Math.max(0, data.edge_compute.ram_percent || 0));
            if (cpuBar) cpuBar.style.width = cpuPct + '%';
            if (cpuVal) cpuVal.textContent = cpuPct.toFixed(0) + '%';
            if (ramBar) ramBar.style.width = ramPct + '%';
            if (ramVal) ramVal.textContent = ramPct.toFixed(0) + '%';
        }

        // Last frame time
        const lastFrame = document.getElementById('sysLastFrame');
        if (lastFrame) {
            if (data.last_frame_time && data.last_frame_time > 0) {
                const d = new Date(data.last_frame_time * 1000);
                lastFrame.textContent = d.toLocaleTimeString();
            } else {
                lastFrame.textContent = '---';
            }
        }
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

    // ---------------------------------------------------------
    // Change Password Modal Handler (Shared across roles)
    // ---------------------------------------------------------
    setupPasswordModal() {
        const modal = document.getElementById('passwordModal');
        const form = document.getElementById('changePasswordForm');
        const msgDiv = document.getElementById('pwdMsg');
        const triggerBtn = document.getElementById('btn-change-password');

        if (!modal || !form) return;

        // Open modal
        if (triggerBtn) {
            triggerBtn.addEventListener('click', (e) => {
                e.preventDefault();
                form.reset();
                if (msgDiv) {
                    msgDiv.style.display = 'none';
                    msgDiv.className = 'modal-msg';
                }
                modal.style.display = 'flex';
                const firstInput = document.getElementById('pwdCurrent');
                if (firstInput) firstInput.focus();
            });
        }

        // Close on backdrop click (click outside modal-card)
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
                if (msgDiv) msgDiv.style.display = 'none';
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.style.display === 'flex') {
                modal.style.display = 'none';
                if (msgDiv) msgDiv.style.display = 'none';
            }
        });

        // Form submit
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!msgDiv) return;
            msgDiv.style.display = 'none';
            msgDiv.className = 'modal-msg';

            const current = document.getElementById('pwdCurrent')?.value.trim();
            const newPwd = document.getElementById('pwdNew')?.value.trim();
            const confirm = document.getElementById('pwdConfirm')?.value.trim();

            if (newPwd !== confirm) {
                msgDiv.textContent = 'New passwords do not match.';
                msgDiv.classList.add('error');
                return;
            }

            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;"></i>Updating...';
            }

            try {
                const res = await fetch('/api/user/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_password: current, new_password: newPwd })
                });
                const data = await res.json();
                if (data.ok) {
                    msgDiv.textContent = 'Password updated successfully!';
                    msgDiv.classList.add('success');
                    form.reset();
                    setTimeout(() => {
                        modal.style.display = 'none';
                        msgDiv.style.display = 'none';
                    }, 1800);
                } else {
                    msgDiv.textContent = data.error || 'Failed to update password.';
                    msgDiv.classList.add('error');
                }
            } catch (err) {
                msgDiv.textContent = 'Server error. Please try again.';
                msgDiv.classList.add('error');
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="fa-solid fa-check" style="margin-right:6px;"></i>Update Password';
                }
            }
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
                        if (j.roi.polygon) {
                        b.innerHTML = '<i class="fa-solid fa-crosshairs"></i> ROI Active: ' + j.roi.polygon.length + '-point polygon';
                    } else {
                        b.innerHTML = `<i class="fa-solid fa-crosshairs"></i> ROI Active: (${Math.round(j.roi.x1)}, ${Math.round(j.roi.y1)}) to (${Math.round(j.roi.x2)}, ${Math.round(j.roi.y2)})`;
                    }
                    }
                }
            }
        } catch (e) { }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
