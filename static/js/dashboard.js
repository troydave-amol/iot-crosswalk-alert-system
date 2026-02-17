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
        connection_status: 'Offline (Mock)',
        // Warning logic helpers
        switch_enabled: true
    },
    latestPayload: null,      // RAW Contract Payload (from Backend/Socket)
    contractValidation: null, // Validation Result
    powerStatus: {    // Power System
        solar_status: 'Charging',
        solar_voltage: 24.1,
        battery_percent: 85,
        led_driver: 'Ready'
    },
    // DB Mode Store
    logsRows: [],     // Paginated DB results
    dbTotal: 0,       // Total matching DB rows
    analyticsRows: [], // Range-based DB results for Analytics/Reports
    analyticsTotal: 0  // Optional total count
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
        mockMode: true,
        isConnected: false,
        dbMode: localStorage.getItem('db_mode_enabled') === 'true', // DB Mode State
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

        // Mock Engine State
        mockEngine: {
            crossingActive: false,
            crossingTimer: 0,
            nextBurstTime: 0,
            powerDrainTimer: 0
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
        this.setupMockEngine(); // Starts the 1s loop
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

        // Mock Mode Toggle
        document.getElementById('mock-toggle').addEventListener('click', (e) => {
            this.setMockMode(!this.state.mockMode);
        });

        // Initial Load for Logs if starting there
        if (window.location.hash === '#logs' && this.state.dbMode) {
            this.loadLogsFromDB();
        }

        // DB Mode Init
        const dbToggle = document.getElementById('toggleDbMode');
        if (dbToggle) {
            // Sync UI to initial state
            this.setDbMode(this.state.dbMode);

            dbToggle.addEventListener('change', (e) => {
                this.setDbMode(e.target.checked);
            });
        }
    },

    // ... (Existing setMockMode, setupMockEngine, updateMockData, setupSocket, handleSocketData methods remain unchanged in this block) ...

    setMockMode(enabled) {
        this.state.mockMode = enabled;
        const btn = document.getElementById('mock-toggle');
        btn.textContent = enabled ? 'Mock Mode: ON' : 'Mock Mode: OFF';
        btn.classList.toggle('btn-primary', enabled);
        btn.classList.toggle('btn-outline', !enabled);

        // If turning OFF, we wait for socket. If no socket data comes in 3s, watchdog will handle it.
        this.updateConnectionStatus();
    },

    // ---------------------------------------------------------
    // DB Mode Logic (Refined UI/UX)
    // ---------------------------------------------------------
    setDbMode(enabled) {
        // 1. Update State & Storage
        this.state.dbMode = enabled;
        localStorage.setItem('db_mode_enabled', enabled);

        // 2. Update Toggle UI
        const toggle = document.getElementById('toggleDbMode');
        const label = document.getElementById('dbModeStateLabel');
        const warning = document.getElementById('dbModeWarning');

        if (toggle) {
            toggle.checked = enabled;
        }

        if (label) label.textContent = enabled ? 'Enabled' : 'Disabled';

        // 3. Status Chip Logic
        const badge = document.getElementById('dbHubStatus');

        if (enabled) {
            // Turning ON
            if (badge) {
                badge.className = 'status-chip mock'; // Grey/Neutral
                badge.textContent = 'Checking...';
                badge.style.display = 'inline-flex';
                badge.style.backgroundColor = '';
                badge.style.color = '';
            }
            if (warning) warning.style.display = 'none';

            this.checkBackendHealth();
        } else {
            // Turning OFF
            if (badge) {
                badge.className = 'status-chip neutral';
                badge.textContent = 'Session';
                badge.style.display = 'inline-flex';
                badge.style.backgroundColor = '';
                badge.style.color = '';
            }
            if (warning) warning.style.display = 'none';
        }

        // 4. Polling & View Logic
        const hash = window.location.hash;

        // Logs Polling
        if (hash === '#logs') {
            if (enabled) {
                this.loadLogsFromDB();
                if (this.state.logsPollingTimer) clearInterval(this.state.logsPollingTimer);
                this.state.logsPollingTimer = setInterval(() => this.loadLogsFromDB(), 10000);
            } else {
                if (this.state.logsPollingTimer) {
                    clearInterval(this.state.logsPollingTimer);
                    this.state.logsPollingTimer = null;
                }
                this.renderLogsTable();
            }
        }

        // Analytics Polling
        if (hash === '#analytics') {
            if (enabled) {
                this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());
                if (this.state.analyticsPollingTimer) clearInterval(this.state.analyticsPollingTimer);
                this.state.analyticsPollingTimer = setInterval(() => {
                    this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());
                }, 30000);
            } else {
                if (this.state.analyticsPollingTimer) {
                    clearInterval(this.state.analyticsPollingTimer);
                    this.state.analyticsPollingTimer = null;
                }
                this.updateAnalyticsUI();
            }
        }
    },

    async checkBackendHealth() {
        const badge = document.getElementById('dbHubStatus');
        const warning = document.getElementById('dbModeWarning');

        try {
            const res = await fetch('/api/health');
            if (res.ok) {
                // Success: Online
                if (badge) {
                    badge.className = 'status-chip connected';
                    badge.textContent = 'Online';
                    badge.style.backgroundColor = ''; // Use CSS class color
                }
            } else {
                throw new Error("Backend Returned Error");
            }
        } catch (e) {
            console.warn("DB Mode Health Check Failed:", e);

            // Failure: Offline -> Auto-Revert
            if (badge) {
                // Briefly show error if you want, or just revert?
                // User wants "Show warning... Auto-switch back to OFF"
                badge.className = 'status-chip neutral'; // Revert to Session style?
                badge.textContent = 'Session';
            }

            // Show Warning
            if (warning) {
                warning.style.display = 'block';
                // Optional: Hide warning after 5s? 
                // "Backend offline — staying in session mode" implies persistent message until user tries again?
                // Or maybe just let it sit there.
            }

            // Auto-Revert Toggle Logic
            this.state.dbMode = false;
            localStorage.setItem('db_mode_enabled', 'false');

            const toggle = document.getElementById('toggleDbMode');
            const label = document.getElementById('dbModeStateLabel');

            if (toggle) toggle.checked = false;
            if (label) label.textContent = 'Disabled';
        }
    },

    // ---------------------------------------------------------
    // 3. Mock Data Engine
    // ---------------------------------------------------------
    setupMockEngine() {
        // Main System Tick (1Hz)
        setInterval(() => {
            const now = Date.now();

            if (this.state.mockMode) {
                this.updateMockData(now);
            } else {
                // Watchdog: If verify we haven't lost connection
                if (now - this.state.lastSocketUpdate > 3000 && this.state.isConnected) {
                    console.warn("Connection lost. Falling back to Mock Mode.");
                    this.state.isConnected = false;
                    this.setMockMode(true); // Auto-fallback
                }
            }

            // Always update UI on tick
            this.updateUI();


            // Auto-refresh Logs if valid
            if (window.location.hash === '#logs') {
                this.renderLogsTable(true); // pass true to indicate auto-refresh if needed
            }

            // Analytics Live Update
            // Prompt: "If DB Mode ON -> refresh every 30s", "If OFF -> existing behavior"
            if (window.location.hash === '#analytics') {
                if (this.state.dbMode) {
                    // DB Mode Polling (30s)
                    // We handle this in setupNavigation/setInterval actually, 
                    // but we could also do it here if we want a single loop. 
                    // However, Prompt said: "Stop polling when leaving Analytics tab".
                    // It's cleaner to use a separate interval in setupNavigation 
                    // OR use this central loop with a checks.

                    // Let's use the setupNavigation approach for the 30s DB poll to be cleaner and explicit.
                    // This block here is for MOCK/Session mode live updates (approx every 2s).
                } else {
                    // Session/Mock Mode: Update every 2s
                    if (now - this.state.analytics.lastUpdate > 2000) {
                        this.updateAnalyticsUI();
                        this.state.analytics.lastUpdate = now;
                    }
                }
            }

        }, 1000);
    },

    updateMockData(now) {
        const engine = this.state.mockEngine;
        const status = window.EventStore.systemStatus;
        const power = window.EventStore.powerStatus;

        // A) Burst Generator Logic
        if (!engine.crossingActive && now > engine.nextBurstTime) {
            if (Math.random() < 0.2) {
                engine.crossingActive = true;
                const duration = 3000 + Math.random() * 5000;
                engine.crossingTimer = now + duration;
            } else {
                engine.nextBurstTime = now + 2000;
            }
        }

        if (engine.crossingActive && now > engine.crossingTimer) {
            engine.crossingActive = false;
            engine.nextBurstTime = now + 5000 + Math.random() * 10000;
        }

        // B) Update Core Status
        let detected = false;
        if (engine.crossingActive) {
            detected = Math.random() > 0.1;
        } else {
            detected = Math.random() > 0.98;
        }

        status.child_in_roi = detected;
        status.roi_status = detected ? 'INSIDE' : 'OUTSIDE';

        // CRITICAL: Warning Logic -> warning_on && switch_enabled
        // (If switch is passed as true in mock usually)
        status.warning_on = status.child_in_roi && status.switch_enabled;

        // C) Confidence & Latency
        if (status.child_in_roi) {
            status.confidence = 0.75 + (Math.random() * 0.23);
            status.latency_ms = 20 + Math.floor(Math.random() * 40);
        } else {
            status.confidence = 0.05 + (Math.random() * 0.20);
            status.latency_ms = 0;
        }

        // D) Power System
        if (now > engine.powerDrainTimer) {
            const change = (Math.random() - 0.5) * 0.5;
            power.battery_percent = Math.max(0, Math.min(100, power.battery_percent + change));
            engine.powerDrainTimer = now + 5000;
            power.solar_voltage = 23.5 + (Math.random() * 1.5);
        }

        // E) Log Generation
        if (status.child_in_roi || Math.random() > 0.7) {
            let scenario = engine.crossingActive ? "Crowded" : "Low activity";
            if (Math.random() > 0.8) scenario = "Rain";
            if (Math.random() > 0.9) scenario = "Night";

            this.logEvent(status, scenario);
        }

        status.last_update_str = new Date().toLocaleTimeString();
        status.connection_status = "Mock Running";
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
        } catch (e) {
            console.log("Socket.IO not initialized (Mock Mode only).");
        }
    },

    handleSocketData(data) {
        // 1. Always process Contract Preview (DEV TOOL) - Updates 'Settings' page even in Mock Mode
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

        if (this.state.mockMode) return;

        this.state.isConnected = true;
        this.state.lastSocketUpdate = Date.now();

        const status = window.EventStore.systemStatus;
        const power = window.EventStore.powerStatus;

        status.child_in_roi = data.child_in_roi;
        // Server might send warning_on, or we derive it? 
        // For now take server value, but ensure it respects switch locally just in case?
        // Actually, if server controls it, we trust server.
        status.warning_on = data.warning_on;
        status.confidence = data.confidence;
        status.roi_status = data.child_in_roi ? 'INSIDE' : 'OUTSIDE';
        status.latency_ms = data.latency || 0;
        status.last_update_str = new Date().toLocaleTimeString();
        status.connection_status = "Connected";

        if (data.battery) power.battery_percent = data.battery;
        // If solar data comes in
        if (data.solar_voltage) power.solar_voltage = data.solar_voltage;

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
        const power = window.EventStore.powerStatus;

        // Topbar
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

        // Power System
        document.getElementById('power-solar-status').textContent = `${power.solar_status} (${power.solar_voltage.toFixed(1)}V)`;
        document.getElementById('power-battery-bar').style.width = `${power.battery_percent}%`;
        document.getElementById('power-battery-text').textContent = `${Math.round(power.battery_percent)}%`;

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
        if (!this.state.dbMode) return;

        const f = this.state.logsFilter;
        // Build Query Params
        const params = new URLSearchParams({
            limit: f.pageSize,
            offset: (f.currentPage - 1) * f.pageSize,
            range: f.range
        });

        if (f.warningOnly) params.append('warning_only', '1');
        if (f.inRoiOnly) params.append('in_roi_only', '1');
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
            this.renderLogsTable(); // Will fallback to session
        }
    },

    async loadAnalyticsFromDB(range) {
        if (!this.state.dbMode) return false;

        // Adviser: explicit mapping (ensure backend receives these exact strings)
        // Frontend uses: 15m, 1h, today, all
        // Backend handles these.

        const params = new URLSearchParams({
            range: range,
            limit: 500, // Fixed limit
            offset: 0
        });

        try {
            const res = await fetch(`/api/events?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();

                // Mismatch Guard
                if (data.total > 0 && (!data.rows || data.rows.length === 0)) {
                    console.error("DATA MISMATCH (Analytics): Total > 0 but rows empty.", data);
                    window.EventStore.analyticsRows = [];
                    window.EventStore.analyticsTotal = 0;
                } else {
                    window.EventStore.analyticsRows = data.rows;
                    window.EventStore.analyticsTotal = data.total;
                }

                // Hide Warning if it was showing
                this.toggleAnalyticsWarning(false);
                return true;
            } else {
                throw new Error("Analytics DB Fetch Failed");
            }
        } catch (e) {
            console.warn("Analytics fetch error:", e);
            this.toggleAnalyticsWarning(true);
            return false;
        }
    },

    toggleAnalyticsWarning(show) {
        // We'll implement a shared warning ID for Analytics & Reports or separate?
        // Plan said: "Add a hidden warning alert div in the Analytics and Reports sections"
        // Let's assume IDs: 'anaDbWarning' and 'repDbWarning'
        const anaWarn = document.getElementById('anaDbWarning');
        const repWarn = document.getElementById('repDbWarning');

        if (anaWarn) anaWarn.style.display = show ? 'block' : 'none';
        if (repWarn) repWarn.style.display = show ? 'block' : 'none';
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
                    if (this.state.dbMode) this.loadLogsFromDB();
                    else this.renderLogsTable();
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
                if (this.state.dbMode) this.loadLogsFromDB();
                else this.renderLogsTable();
            });
        });

        // Toggles
        document.getElementById('filterWarningOn')?.addEventListener('change', (e) => {
            filters.warningOnly = e.target.checked;
            filters.currentPage = 1;
            this.renderLogsTable(); /* don't auto render on every click if we have apply? Prompt said Apply button triggers it, but live updates are nicer. Prompt says: Apply button triggers renderLogsTable(), but also said "Date preset buttons: set active... and render". Let's stick to prompt strictness where possible, but for UX 'Apply' usually implies manual trigger. However, the prompt also says "Slider updates label live and renders on release". Given the 'Apply' button exists, I will make the toggles/dropdowns update state but ONLY render when Apply is clicked, OR just render immediately for better UX. The prompt specifically lists "Apply (id=btnApplyLogsFilters)". So I will bind the render to the Apply button for the form controls. But Date Presets are immediate per prompt. */
        });

        document.getElementById('filterInRoi')?.addEventListener('change', (e) => {
            filters.inRoiOnly = e.target.checked;
            // Waiting for Apply button
        });

        document.getElementById('filterScenario')?.addEventListener('change', (e) => {
            filters.scenario = e.target.value;
            // Waiting for Apply button
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
                // Waiting for Apply button or immediate? Prompt: "renders on release".
                this.renderLogsTable();
            });
        }

        // Buttons
        document.getElementById('btnApplyLogsFilters')?.addEventListener('click', () => {
            // Re-read current DOM state just to be sure or just render based on bound state (bound state is better)
            filters.currentPage = 1;
            if (this.state.dbMode) this.loadLogsFromDB();
            else this.renderLogsTable();
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

            this.renderLogsTable(); // Reset always renders session logs initially properly, but if in DB mode?
            // If DB Mode, we should probably fetch from DB with reset params?
            // "If DB Mode ON -> loadLogsFromDB()"
            if (this.state.dbMode) this.loadLogsFromDB();
            else this.renderLogsTable();
        });

        // Pagination
        document.getElementById('pageSizeSelect')?.addEventListener('change', (e) => {
            filters.pageSize = parseInt(e.target.value);
            filters.pageSize = parseInt(e.target.value);
            filters.currentPage = 1;
            if (this.state.dbMode) this.loadLogsFromDB();
            else this.renderLogsTable();
        });

        document.getElementById('pagePrev')?.addEventListener('click', () => {
            if (filters.currentPage > 1) {
                filters.currentPage--;
                if (this.state.dbMode) this.loadLogsFromDB();
                else this.renderLogsTable();
            }
        });

        document.getElementById('pageNext')?.addEventListener('click', () => {
            if (filters.currentPage < filters.totalPages) {
                filters.currentPage++;
                if (this.state.dbMode) this.loadLogsFromDB();
                else this.renderLogsTable();
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

        // 1. Determine Source
        let displayLogs = [];
        let total = 0;
        let isDbSource = this.state.dbMode && !this.state.logsDbError;

        if (isDbSource) {
            // Use DB Data
            displayLogs = window.EventStore.logsRows || [];
            total = window.EventStore.dbTotal || 0;
            if (warningEl) warningEl.style.display = 'none';
        } else {
            // Use Session Data
            const allFiltered = this.getFilteredLogs();
            total = allFiltered.length;

            // Recalc pages for session data
            const f = this.state.logsFilter;
            f.totalPages = Math.ceil(total / f.pageSize) || 1;
            if (f.currentPage > f.totalPages) f.currentPage = f.totalPages;
            if (f.currentPage < 1) f.currentPage = 1;

            const start = (f.currentPage - 1) * f.pageSize;
            const end = start + f.pageSize;
            displayLogs = allFiltered.slice(start, end);

            // Show warning only if DB mode was intended but failed
            if (warningEl) warningEl.style.display = this.state.dbMode && this.state.logsDbError ? 'block' : 'none';
        }

        const f = this.state.logsFilter;
        // If DB Source, pages are calc based on Total
        if (isDbSource) {
            // Logic: Backend handles slicing, we just need to know total pages
            f.totalPages = Math.ceil(total / f.pageSize) || 1;
        }

        // Render Rows
        if (displayLogs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px; color:#888;">No logs found.</td></tr>';
        } else {
            tbody.innerHTML = displayLogs.map(log => {
                // Time Display Logic
                let timeStr = log.timestamp; // Default to existing if valid
                if (this.state.dbMode) {
                    const d = this.state.parseTimestamp(log.timestamp_iso);
                    if (d) timeStr = d.toLocaleTimeString();
                    else timeStr = log.timestamp_iso || "Invalid Date";
                } else {
                    // Session fallback
                    if (!timeStr && log.rawTimestamp) timeStr = new Date(log.rawTimestamp).toLocaleTimeString();
                }

                return `
                <tr>
                    <td>${timeStr}</td>
                    <td><span class="badge ${log.child_in_roi ? 'badge-warning' : 'badge-neutral'}">${log.child_in_roi ? 'YES' : 'NO'}</span></td>
                    <td><span style="font-size:0.85em; color:${log.roi_status === 'INSIDE' ? '#d32f2f' : '#999'}">${log.roi_status}</span></td>
                    <td><span class="badge ${log.warning_on ? 'badge-warning' : 'badge-success'}">${log.warning_on ? 'ON' : 'OFF'}</span></td>
                    <td>${(log.confidence || 0).toFixed(2)}</td>
                    <td>${log.latency_ms}ms</td>
                    <td>${log.scenario}</td>
                    <td>${log.false_warning ? '<span style="color:red">YES</span>' : 'NO'}</td>
                </tr>
            `}).join('');
        }

        // Calculate range text
        const startIdx = (f.currentPage - 1) * f.pageSize;
        const currentCount = displayLogs.length;

        // Fix: "Showing 0-0 of 0" logic
        let rangeText = "";
        if (total === 0) {
            rangeText = "Showing 0 of 0 events";
        } else {
            const endRange = startIdx + currentCount;
            // Guard against weird math if backend returns weirdness
            rangeText = `Showing ${startIdx + 1}–${endRange} of ${total} ${isDbSource ? 'persistent' : 'filtered'} events`;
        }

        // Update Controls
        document.getElementById('resultCount').textContent = rangeText;
        document.getElementById('pageIndicator').textContent = `Page ${f.currentPage} of ${f.totalPages}`;
        document.getElementById('pagePrev').disabled = (f.currentPage <= 1);
        document.getElementById('pageNext').disabled = (f.currentPage >= f.totalPages);
    },

    exportCSV() {
        const data = this.getFilteredLogs();
        const headers = ["Timestamp,Message,In ROI,Warning,Confidence,Latency,Scenario,False Warning\n"];
        const rows = data.map(log =>
            `${log.timestamp},${log.message},${log.child_in_roi},${log.warning_on},${log.confidence.toFixed(2)},${log.latency_ms},${log.scenario},${log.false_warning}`
        );
        this.downloadFile(headers.concat(rows).join("\n"), 'csv');
    },

    exportJSON() {
        const data = this.getFilteredLogs();
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

            // Logs Polling Logic
            if (hash === 'logs') {
                if (this.state.dbMode) {
                    this.loadLogsFromDB();
                    // Start Polling (10s)
                    if (this.state.logsPollingTimer) clearInterval(this.state.logsPollingTimer);
                    this.state.logsPollingTimer = setInterval(() => this.loadLogsFromDB(), 10000);
                }
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

                if (this.state.dbMode) {
                    // 1. Initial Load
                    this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());

                    // 2. Start Polling (30s)
                    this.state.analyticsPollingTimer = setInterval(() => {
                        this.loadAnalyticsFromDB(this.state.analytics.range).then(() => this.updateAnalyticsUI());
                    }, 30000);
                } else {
                    this.updateAnalyticsUI();
                }
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

                // Load Data
                if (this.state.dbMode) {
                    this.loadAnalyticsFromDB(newRange).then(() => this.updateAnalyticsUI());
                } else {
                    this.updateAnalyticsUI();
                }
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
        const rawEvents = this.getAnalyticsEvents();
        // Normalize for consistent keys
        const events = rawEvents.map(e => this.normalizeEvent(e));

        // Empty State Check
        const chartGrid = document.querySelector('#analytics-section .charts-grid');
        if (chartGrid) {
            if (events.length === 0) {
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
            } else {
                chartGrid.style.display = 'grid';
                const emptyMsg = document.getElementById('ana-empty-msg');
                if (emptyMsg) emptyMsg.style.display = 'none';
            }
        }

        this.computeKPIs(events);
        this.updateCharts(events);
    },

    getAnalyticsEvents() {
        const range = this.state.analytics.range;
        const now = Date.now();
        let startTime = 0;

        if (range === '15m') startTime = now - (15 * 60 * 1000);
        else if (range === '1h') startTime = now - (60 * 60 * 1000);
        else if (range === 'today') {
            const t = new Date(); t.setHours(0, 0, 0, 0);
            startTime = t.getTime();
        }
        // 'all' = 0

        // Filter and Sort (Oldest first for Charts, usually)
        if (this.state.dbMode) {
            // Use DB rows
            return (window.EventStore.analyticsRows || [])
                .sort((a, b) => {
                    const tA = this.state.parseTimestamp(a.timestamp_iso)?.getTime() || 0;
                    const tB = this.state.parseTimestamp(b.timestamp_iso)?.getTime() || 0;
                    return tA - tB;
                });
        } else {
            // Use Session events
            return window.EventStore.events
                .filter(log => (log.rawTimestamp || log.id) >= startTime)
                .sort((a, b) => (a.rawTimestamp || a.id) - (b.rawTimestamp || b.id));
        }
    },

    computeKPIs(events) {
        let totalWarnings = 0;
        let totalDetections = 0;
        let falseWarnings = 0;
        let totalLatency = 0;
        let latencyCount = 0;
        const hoursMap = {};

        events.forEach(e => {
            // Use canonical keys with isOn()
            const isWarn = this.isOn(e.warning_device_on);
            const isDet = this.isOn(e.child_in_roi);

            if (isWarn) totalWarnings++;
            if (isDet) totalDetections++;
            if (e.false_warning) falseWarnings++; // Keep existing or use (isWarn && !isDet)? existing log logic populates this.

            const lat = parseFloat(e.latency_ms);
            if (lat > 0) {
                totalLatency += lat;
                latencyCount++;
            }

            // Peak Hour
            let d = new Date(e.rawTimestamp || e.id);
            if (this.state.dbMode && e.timestamp_iso) {
                const parsed = this.state.parseTimestamp(e.timestamp_iso);
                if (parsed) d = parsed;
            }
            const h = d.getHours();
            hoursMap[h] = (hoursMap[h] || 0) + 1;
        });

        // Debug Log (Adviser req)
        if (this.state.dbMode) {
            console.debug(`[Analytics Fix] Rows: ${events.length}, Warnings: ${totalWarnings}`);
        }

        // Peak Calc
        let peakHour = '--';
        let maxCount = 0;
        for (const [h, count] of Object.entries(hoursMap)) {
            if (count > maxCount) {
                maxCount = count;
                const date = new Date(); date.setHours(h);
                peakHour = date.toLocaleTimeString([], { hour: 'numeric', hour12: true });
            }
        }

        const avgLatency = latencyCount > 0 ? Math.round(totalLatency / latencyCount) : 0;

        // DOM Updates
        document.getElementById('ana-kpi-warnings').textContent = totalWarnings;
        document.getElementById('ana-kpi-detections').textContent = totalDetections;
        document.getElementById('ana-kpi-false').textContent = falseWarnings;
        document.getElementById('ana-kpi-latency').textContent = avgLatency + 'ms';
        document.getElementById('ana-kpi-peak').textContent = peakHour;
    },

    updateCharts(events) {
        // Helper: Binning
        const range = this.state.analytics.range;
        const binSize = (range === '15m' || range === '1h') ? 5 * 60 * 1000 : 60 * 60 * 1000; // 5m or 1h
        const timeFormat = (range === '15m' || range === '1h') ?
            d => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) :
            d => d.toLocaleTimeString([], { hour: 'numeric', hour12: true });

        // 1. Comparison & Distribution Maps
        const bins = {};
        const confBins = [0, 0, 0, 0, 0]; // 0-0.2, 0.2-0.4 ...
        const scenarioMap = {};

        events.forEach(e => {
            // Time Bins
            let ts = e.rawTimestamp || e.id;
            if (this.state.dbMode && e.timestamp_iso) {
                const parsed = this.state.parseTimestamp(e.timestamp_iso);
                if (parsed) ts = parsed.getTime();
            }
            const binKey = Math.floor(ts / binSize) * binSize;
            if (!bins[binKey]) bins[binKey] = { warnings: 0, detections: 0 };

            // Use isOn logic
            if (this.isOn(e.warning_device_on)) bins[binKey].warnings++;
            if (this.isOn(e.child_in_roi)) bins[binKey].detections++;

            // Confidence (only if detection)
            if (this.isOn(e.child_in_roi)) {
                const c = parseFloat(e.confidence) || 0;
                if (c < 0.2) confBins[0]++;
                else if (c < 0.4) confBins[1]++;
                else if (c < 0.6) confBins[2]++;
                else if (c < 0.8) confBins[3]++;
                else confBins[4]++;
            }

            // Scenario
            const s = e.scenario || 'Unknown';
            scenarioMap[s] = (scenarioMap[s] || 0) + 1;
        });

        // Convert Bins to Arrays
        const sortedKeys = Object.keys(bins).sort();
        const labels = sortedKeys.map(k => timeFormat(new Date(parseInt(k))));
        const dataWarnings = sortedKeys.map(k => bins[k].warnings);
        const dataDetections = sortedKeys.map(k => bins[k].detections);

        // Update Charts
        // A) Warnings
        if (this.state.charts.warnings) {
            const chart = this.state.charts.warnings;
            chart.data.labels = labels;
            chart.data.datasets[0].data = dataWarnings;
            chart.update('none'); // 'none' mode for performance
        }

        // B) Detections
        if (this.state.charts.detections) {
            const chart = this.state.charts.detections;
            chart.data.labels = labels;
            chart.data.datasets[0].data = dataDetections;
            chart.update('none');
        }

        // C) Confidence
        if (this.state.charts.confidence) {
            const chart = this.state.charts.confidence;
            chart.data.datasets[0].data = confBins;
            chart.update('none');
        }

        // D) Scenario
        if (this.state.charts.scenario) {
            const chart = this.state.charts.scenario;
            chart.data.labels = Object.keys(scenarioMap);
            chart.data.datasets[0].data = Object.values(scenarioMap);
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

        // 1. Presets
        document.querySelectorAll('.btn-preset[data-rep-range]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // UI
                document.querySelectorAll('.btn-preset[data-rep-range]').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                // State
                this.state.reports.range = e.target.getAttribute('data-rep-range');
                // Auto-regenerate on preset change
                if (this.state.dbMode) {
                    this.loadAnalyticsFromDB(this.state.reports.range).then(() => this.generateReport());
                } else {
                    this.generateReport();
                }
            });
        });

        // 2. Actions
        document.getElementById('btnGenerateReport')?.addEventListener('click', () => {
            if (this.state.dbMode) {
                this.loadAnalyticsFromDB(this.state.reports.range).then(() => this.generateReport());
            } else {
                this.generateReport();
            }
        });

        document.getElementById('btnPrintReport')?.addEventListener('click', () => {
            // Ensure report is fresh
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

        // Initial Generation
        if (!this.state.dbMode) {
            setTimeout(() => this.generateReport(), 500);
        } else {
            // If DB Mode, we likely want to show default report
            setTimeout(() => {
                // Try reuse if Analytics already has data, else fetch
                const anaRange = this.state.analytics.range;
                const repRange = this.state.reports.range;

                // If analytics has 'today' data and we need 'today', reuse it
                if (anaRange === repRange && window.EventStore.analyticsRows.length > 0) {
                    this.generateReport();
                } else {
                    this.loadAnalyticsFromDB(repRange).then(() => this.generateReport());
                }
            }, 500);
        }
    },

    async generateReport() {
        // DB Mode: Ensure we have data for the REPORT range
        if (this.state.dbMode) {
            const range = this.state.reports.range;
            // Check if we already have this data loaded in Analytics (optimization)
            // Only reuse if the analytics range matches report range.
            // Otherwise we MUST fetch new data.
            if (this.state.analytics.range !== range || !window.EventStore.analyticsRows) {
                // Fetch dedicated report dataset (re-using loadAnalyticsFromDB helper for now as it fills same store)
                // NOTE: reusing loadAnalyticsFromDB overwrites analyticsRows. This is okay as they are usually same page 
                // BUT if user switches tabs quickly it might be confusing. 
                // Ideally reports should have own store, but for "Wire Analytics to DB" scope, sharing is acceptable
                // provided we accept the overwrite.
                await this.loadAnalyticsFromDB(range);
            }
        }

        const events = this.getReportEvents();
        const range = this.state.reports.range;

        // ... rest of logic uses 'events' which is now populated from DB store if logic holds

        let totalWarnings = 0;
        let totalDetections = 0;
        let falseWarnings = 0;
        let totalLatency = 0;
        let latencyCount = 0;
        const hoursMap = {};
        const scenarioMap = {};

        events.forEach(e => {
            if (e.warning_on) totalWarnings++;
            if (e.child_in_roi) totalDetections++;
            if (e.false_warning) falseWarnings++;
            if (e.latency_ms > 0) {
                totalLatency += e.latency_ms;
                latencyCount++;
            }

            // Peak Hour
            const d = new Date(e.rawTimestamp || e.id);
            const h = d.getHours();
            hoursMap[h] = (hoursMap[h] || 0) + 1;

            // Scenarios
            if (e.scenario) scenarioMap[e.scenario] = (scenarioMap[e.scenario] || 0) + 1;
        });

        // Peak Hour Calc
        let peakHour = '--';
        let maxCount = 0;
        for (const [h, count] of Object.entries(hoursMap)) {
            if (count > maxCount) {
                maxCount = count;
                const d = new Date(); d.setHours(h);
                peakHour = d.toLocaleTimeString([], { hour: 'numeric', hour12: true }) +
                    ' - ' +
                    new Date(d.getTime() + 3600000).toLocaleTimeString([], { hour: 'numeric', hour12: true });
            }
        }

        const avgLatency = latencyCount > 0 ? Math.round(totalLatency / latencyCount) : 0;

        // Insights Generation
        const insights = [];
        if (events.length === 0) {
            insights.push("No events recorded during this period.");
        } else {
            if (totalWarnings > 0) insights.push(`Total of ${totalWarnings} warnings triggered.`);
            if (peakHour !== '--') insights.push(`Peak warning period: ${peakHour}`);

            // Common Scenario
            let commonScenario = '--';
            let maxScen = 0;
            for (const [s, c] of Object.entries(scenarioMap)) {
                if (c > maxScen) { maxScen = c; commonScenario = s; }
            }
            if (commonScenario !== '--') insights.push(`Most common scenario: ${commonScenario}`);

            if (avgLatency < 100) insights.push(`System performance optimal (Avg latency < 100ms).`);
            else insights.push(`Average latency is ${avgLatency}ms.`);
        }

        const summary = {
            rangeLabel: document.querySelector(`.btn-preset[data-rep-range="${range}"]`)?.textContent || range,
            generatedAt: new Date().toLocaleString(),
            totalWarnings,
            totalDetections,
            falseWarnings,
            avgLatency,
            peakHour,
            metrics: { // For CSV/JSON
                mostCommonScenario: insights.find(i => i.includes('Most common'))?.split(": ")[1] || "N/A"
            },
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

        let content = "";
        if (type === 'json') {
            content = JSON.stringify(s, null, 2);
        } else {
            // CSV
            const header = "Generated At,Range,Total Warnings,Total Detections,False Warnings,Avg Latency,Peak Hour,Most Common Scenario,Location,Client,Title\n";
            const row = `${s.generatedAt},${s.rangeLabel},${s.totalWarnings},${s.totalDetections},${s.falseWarnings},${s.avgLatency},${s.peakHour},${s.metrics.mostCommonScenario},"Casisang Central School","TMC","IoT-Based Smart School-Zone Crosswalk Alert System"`;
            content = header + row;
        }

        const blob = new Blob([content], { type: type === 'csv' ? 'text/csv;charset=utf-8;' : 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", filename);
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

        // 3. Load from LocalStorage
        const savedRect = localStorage.getItem('roiRect');
        const savedImgData = localStorage.getItem('roiImageData');

        if (savedRect) {
            this.state.roi = JSON.parse(savedRect);
        }

        if (savedImgData) {
            this.loadImageToCanvas(savedImgData);
        } else {
            // No image? Show overlay
            overlay.style.display = 'block';
            canvas.style.display = 'none';
        }

        // 4. Event Listeners

        // A) File Input
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files[0]) {
                const reader = new FileReader();
                reader.onload = (evt) => {
                    // Reset ROI on new image? Prompt says: "If user uploads a new image, clear the current ROI selection"
                    this.state.roi = null;
                    this.loadImageToCanvas(evt.target.result);

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

        // Draw Rect
        if (roi && (roi.w !== 0 || roi.h !== 0)) {
            // Fill
            ctx.fillStyle = 'rgba(255, 146, 128, 0.3)'; // Primary accent tint
            ctx.fillRect(roi.x, roi.y, roi.w, roi.h);

            // Stroke
            ctx.strokeStyle = '#FF9280';
            ctx.lineWidth = 3;
            ctx.strokeRect(roi.x, roi.y, roi.w, roi.h);
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

    saveRoi() {
        if (!this.state.roi) {
            alert("No ROI defined.");
            return;
        }

        try {
            // 1. ROI Rect
            localStorage.setItem('roiRect', JSON.stringify(this.state.roi));

            // 2. Image Data (only if new image loaded, or keep existing)
            // If we have an image in memory (img.src is DataURL), save it.
            if (this.roiState.img && this.roiState.img.src.startsWith('data:')) {
                localStorage.setItem('roiImageData', this.roiState.img.src);
            }

            // 3. Meta
            if (this.roiState.img) {
                const meta = { width: this.roiState.img.naturalWidth, height: this.roiState.img.naturalHeight };
                localStorage.setItem('roiImageMeta', JSON.stringify(meta));
            }

            // Feedback
            const btn = document.getElementById('btnSaveRoi');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Saved';
            btn.classList.replace('btn-primary', 'btn-success'); // Assuming bootstrap-like or we add style
            // We need to define .btn-success or just style it
            btn.style.backgroundColor = '#4CAF50';
            btn.style.color = 'white';

            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.style.backgroundColor = '';
                btn.style.color = '';
                btn.classList.replace('btn-success', 'btn-primary');
            }, 2000);

        } catch (e) {
            console.error("Storage Error", e);
            if (e.name === 'QuotaExceededError') {
                alert("Error: Image is too large to save in browser storage. Please use a smaller image/resolution.");
            } else {
                alert("Error saving settings.");
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

        const select = document.getElementById('camDeviceSelect');
        if (select) {
            select.addEventListener('change', (e) => {
                const newId = e.target.value;
                if (window.CameraController.selectedDeviceId === newId) return; // No change

                window.CameraController.selectedDeviceId = newId;
                localStorage.setItem('camDeviceId', newId);

                // If camera is already ON, restart with new device
                if (window.CameraController.isOn) {
                    this.stopCamera(); // Stop current
                    setTimeout(() => this.startCamera(), 300); // Restart
                }
            });
        }

        // Enumerate Devices
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
            navigator.mediaDevices.enumerateDevices().then(devices => {
                const videoDevices = devices.filter(device => device.kind === 'videoinput');
                const selectGroup = document.getElementById('camSelectGroup');

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
        if (window.CameraController.isOn && window.CameraController.stream && window.CameraController.stream.active) {
            // Already running, just ensure attached
            this.attachStreamToVideo(window.CameraController.stream);
            return;
        }

        const constraints = {
            video: window.CameraController.selectedDeviceId ?
                { deviceId: { exact: window.CameraController.selectedDeviceId } } : true,
            audio: false
        };

        navigator.mediaDevices.getUserMedia(constraints).then(stream => {
            // Success
            window.CameraController.stream = stream;
            window.CameraController.isOn = true;
            window.CameraController.lastError = null;

            // Handle stream ended unexpectedly
            if (stream.getTracks().length > 0) {
                const track = stream.getTracks()[0];
                track.onended = () => {
                    console.log("Stream track ended.");
                    // Only stop if we really are done.
                    // This creates a robust check.
                    this.stopCamera();
                };
            }

            this.attachStreamToVideo(stream);

        }).catch(err => {
            console.error("Camera error:", err);
            window.CameraController.isOn = false;
            window.CameraController.lastError = err;
            window.CameraController.stream = null;

            const ph = document.getElementById('camPlaceholder');
            if (ph) {
                ph.innerHTML = `<p style="color:red">Error: ${err.message}</p>`;
                ph.style.display = 'flex';
            }
        });
    },

    attachStreamToVideo(stream) {
        const video = document.getElementById('liveCam');
        if (!video) return;

        try {
            // Don't re-set if already same (avoids flicker)
            if (video.srcObject !== stream) {
                video.srcObject = stream;
            }

            // Allow play
            video.play().catch(e => {
                if (e.name !== 'AbortError') console.warn("Video play interrupted:", e);
            });

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
            if (sourceChip) sourceChip.style.display = 'flex';

        } catch (e) {
            console.error("Attach error:", e);
        }
    },

    stopCamera() {
        // Stop Tracks
        if (window.CameraController.stream) {
            window.CameraController.stream.getTracks().forEach(track => track.stop());
            window.CameraController.stream = null;
        }
        window.CameraController.isOn = false;

        // UI Reset
        const video = document.getElementById('liveCam');
        if (video) {
            video.pause();
            video.srcObject = null;
        }

        const ph = document.getElementById('camPlaceholder');
        if (ph) {
            ph.style.display = 'flex';
            ph.innerHTML = `
                <div style="font-size: 2rem; margin-bottom: 10px; color: #ccc;">
                    <i class="fa-solid fa-camera"></i>
                </div>
                <p><strong>Camera is OFF.</strong><br>Click Start Camera to preview.</p>
                <p style="font-size: 0.8rem; margin-top: 10px; color: #888;">Runs locally in the browser. No audio, no recording, no uploads.</p>
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
    }
};

document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
