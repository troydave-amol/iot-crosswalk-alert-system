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
    powerStatus: {    // Power System
        solar_status: 'Charging',
        solar_voltage: 24.1,
        battery_percent: 85,
        led_driver: 'Ready'
    }
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
        lastSocketUpdate: 0,

        // System Configuration
        roi: JSON.parse(localStorage.getItem('roi_settings')) || { x: 50, y: 50, w: 100, h: 100 },

        // Logs Page Filter State
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

            // Analytics Live Update (Throttle to every 2s)
            if (window.location.hash === '#analytics') {
                if (now - this.state.analytics.lastUpdate > 2000) {
                    this.updateAnalyticsUI();
                    this.state.analytics.lastUpdate = now;
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
        try {
            const socket = io();
            socket.on('connect', () => {
                this.state.isConnected = true;
                this.updateConnectionStatus();
            });
            socket.on('disconnect', () => {
                this.state.isConnected = false;
                this.updateConnectionStatus();
            });
            socket.on('status_update', (data) => {
                this.handleSocketData(data);
            });
        } catch (e) {
            console.log("Socket.IO not initialized (Mock Mode only).");
        }
    },

    handleSocketData(data) {
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
            <div class="feed-item" style="border-bottom:1px solid #eee; padding:8px 0; font-size:0.9rem;">
                <span class="text-muted" style="font-size:0.8rem;">${e.timestamp}</span>
                <strong>${e.message}</strong>
                <div style="font-size:0.8rem; color:#666;">Conf: ${e.confidence.toFixed(2)} | Latency: ${e.latency_ms}ms</div>
            </div>
        `).join('');
    },

    // ---------------------------------------------------------
    // 6. Logs Logic: Sorting, Filtering, Pagination
    // ---------------------------------------------------------
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
                    this.renderLogsTable();
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
                this.renderLogsTable();
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
            this.renderLogsTable();
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

            this.renderLogsTable();
        });

        // Pagination
        document.getElementById('pageSizeSelect')?.addEventListener('change', (e) => {
            filters.pageSize = parseInt(e.target.value);
            filters.currentPage = 1;
            this.renderLogsTable();
        });

        document.getElementById('pagePrev')?.addEventListener('click', () => {
            if (filters.currentPage > 1) {
                filters.currentPage--;
                this.renderLogsTable();
            }
        });

        document.getElementById('pageNext')?.addEventListener('click', () => {
            if (filters.currentPage < filters.totalPages) {
                filters.currentPage++;
                this.renderLogsTable();
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
        if (!tbody) return;

        // Don't refresh if user is interacting with filters? 
        // Logic says "preserve current filters". We do that.
        // "preserve current page". We do that.

        const allFiltered = this.getFilteredLogs();
        const total = allFiltered.length;
        const f = this.state.logsFilter;

        // Calc Pagination
        f.totalPages = Math.ceil(total / f.pageSize) || 1;

        // Fix page if out of bounds
        if (f.currentPage > f.totalPages) f.currentPage = f.totalPages;
        if (f.currentPage < 1) f.currentPage = 1;

        // Slice
        const start = (f.currentPage - 1) * f.pageSize;
        const end = start + f.pageSize;
        const pageItems = allFiltered.slice(start, end);

        // Render Rows
        tbody.innerHTML = pageItems.map(log => `
            <tr>
                <td>${log.timestamp}</td>
                <td><span class="badge ${log.child_in_roi ? 'badge-warning' : 'badge-neutral'}">${log.child_in_roi ? 'YES' : 'NO'}</span></td>
                <td><span style="font-size:0.85em; color:${log.roi_status === 'INSIDE' ? '#d32f2f' : '#999'}">${log.roi_status}</span></td>
                <td><span class="badge ${log.warning_on ? 'badge-warning' : 'badge-success'}">${log.warning_on ? 'ON' : 'OFF'}</span></td>
                <td>${(log.confidence || 0).toFixed(2)}</td>
                <td>${log.latency_ms}ms</td>
                <td>${log.scenario}</td>
                <td>${log.false_warning ? '<span style="color:red">YES</span>' : 'NO'}</td>
            </tr>
        `).join('');

        // Update Controls
        document.getElementById('resultCount').textContent = `Showing ${Math.min(end, total) - start > 0 ? start + 1 : 0}-${Math.min(end, total)} of ${total} filtered events`;
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

            if (hash === 'analytics') {
                if (this.state.charts.warnings) this.state.charts.warnings.resize();
                this.updateAnalyticsUI();
            }
            if (hash !== 'live') this.stopCamera();
        };
        window.addEventListener('hashchange', handleHashChange);
        handleHashChange();
    },

    setupAnalytics() {
        // 1. Chart Init
        // Common Chart Options
        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 800 },
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true, grid: { color: '#f0f0f0' } }
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
                this.state.analytics.range = e.target.getAttribute('data-ana-range');
                this.updateAnalyticsUI();
            });
        });

        // Initial update
        this.updateAnalyticsUI();
    },

    updateAnalyticsUI() {
        const events = this.getAnalyticsEvents();

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
        return window.EventStore.events
            .filter(log => (log.rawTimestamp || log.id) >= startTime)
            .sort((a, b) => (a.rawTimestamp || a.id) - (b.rawTimestamp || b.id));
    },

    computeKPIs(events) {
        let totalWarnings = 0;
        let totalDetections = 0;
        let falseWarnings = 0;
        let totalLatency = 0;
        let latencyCount = 0;
        const hoursMap = {};

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
        });

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
            const ts = e.rawTimestamp || e.id;
            const binKey = Math.floor(ts / binSize) * binSize;
            if (!bins[binKey]) bins[binKey] = { warnings: 0, detections: 0 };
            if (e.warning_on) bins[binKey].warnings++;
            if (e.child_in_roi) bins[binKey].detections++;

            // Confidence (only if detection)
            if (e.child_in_roi) {
                const c = e.confidence;
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
                // Auto-regenerate on preset change for better UX
                this.generateReport();
            });
        });

        // 2. Actions
        document.getElementById('btnGenerateReport')?.addEventListener('click', () => {
            this.generateReport();
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
        // Delay slightly to ensure logs are populated
        setTimeout(() => this.generateReport(), 500);
    },

    getReportEvents() {
        const range = this.state.reports.range;
        const now = Date.now();
        let startTime = 0;

        if (range === '15m') startTime = now - (15 * 60 * 1000);
        else if (range === '1h') startTime = now - (60 * 60 * 1000);
        else if (range === 'today') {
            const t = new Date(); t.setHours(0, 0, 0, 0);
            startTime = t.getTime();
        }
        // 'all' = 0

        return window.EventStore.events.filter(log => (log.rawTimestamp || log.id) >= startTime);
    },

    generateReport() {
        const events = this.getReportEvents();
        const range = this.state.reports.range;

        // Compute metrics
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
        document.getElementById('btnStartCam')?.addEventListener('click', () => this.startCamera());
        document.getElementById('btnStopCam')?.addEventListener('click', () => this.stopCamera());

        const select = document.getElementById('camDeviceSelect');
        if (select) {
            select.addEventListener('change', (e) => {
                this.state.camera.selectedId = e.target.value;
                if (this.state.camera.stream) {
                    this.stopCamera();
                    this.startCamera();
                }
            });
        }

        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
            navigator.mediaDevices.enumerateDevices().then(devices => {
                const videoDevices = devices.filter(device => device.kind === 'videoinput');
                const selectGroup = document.getElementById('camSelectGroup');
                if (videoDevices.length > 0) {
                    select.innerHTML = videoDevices.map(device =>
                        `<option value="${device.deviceId}">${device.label || `Camera ${select.length + 1}`}</option>`
                    ).join('');
                    if (videoDevices.length > 1) selectGroup.style.display = 'block';
                    this.state.camera.selectedId = videoDevices[0].deviceId;
                }
            }).catch(e => console.warn(e));
        }
    },

    startCamera() {
        if (this.state.camera.stream) return;
        const constraints = {
            video: this.state.camera.selectedId ? { deviceId: { exact: this.state.camera.selectedId } } : true,
            audio: false
        };
        navigator.mediaDevices.getUserMedia(constraints).then(stream => {
            this.state.camera.stream = stream;
            const video = document.getElementById('liveCam');
            video.srcObject = stream;
            document.getElementById('camPlaceholder').style.display = 'none';

            const chip = document.getElementById('camStatusChip');
            chip.className = 'status-chip connected';
            chip.innerHTML = '<div class="status-indicator"></div> ON';
            chip.style.backgroundColor = 'rgba(76, 175, 80, 0.1)';
            chip.style.color = '#2e7d32';

            const sourceChip = document.getElementById('camSourceChip');
            sourceChip.style.display = 'flex';
        }).catch(err => {
            console.error("Camera error:", err);
            const ph = document.getElementById('camPlaceholder');
            ph.innerHTML = `<p style="color:red">Error: ${err.message}</p>`;
            ph.style.display = 'flex';
        });
    },

    stopCamera() {
        if (this.state.camera.stream) {
            this.state.camera.stream.getTracks().forEach(track => track.stop());
            this.state.camera.stream = null;
        }
        const video = document.getElementById('liveCam');
        if (video) video.srcObject = null;

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
        document.getElementById('camSourceChip').style.display = 'none';
    }
};

document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
