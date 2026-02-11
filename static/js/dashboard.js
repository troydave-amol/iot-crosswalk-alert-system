// Dashboard Application Logic

const App = {
    state: {
        mockMode: true,
        isConnected: false,
        lastUpdate: null,
        logs: [],
        currentSection: 'live',
        charts: {},
        roi: JSON.parse(localStorage.getItem('roi_settings')) || { x: 50, y: 50, w: 100, h: 100 },
        systemState: {
            child_in_roi: false,
            warning_on: false,
            confidence: 0.0,
            roi_status: 'OUTSIDE'
        }
    },

    init() {
        this.setupNavigation();
        this.setupSocket();
        this.setupMockGenerator();
        this.setupCharts();
        this.renderLogs();
        this.setupROI();
        this.updateTime();
        
        // Mobile sidebar toggle
        document.getElementById('sidebar-toggle').addEventListener('click', () => {
             document.querySelector('.sidebar').classList.toggle('collapsed');
             document.querySelector('.main-content').classList.toggle('expanded');
        });

        // Mock mode toggle
        document.getElementById('mock-toggle').addEventListener('click', (e) => {
            this.state.mockMode = !this.state.mockMode;
            e.target.textContent = this.state.mockMode ? 'Mock Mode: ON' : 'Mock Mode: OFF';
            e.target.classList.toggle('btn-primary');
            e.target.classList.toggle('btn-outline');
        });
    },

    setupNavigation() {
        const handleHashChange = () => {
            const hash = window.location.hash.slice(1) || 'live';
            this.state.currentSection = hash;
            
            // Update active nav item
            document.querySelectorAll('.nav-item').forEach(el => {
                el.classList.toggle('active', el.getAttribute('href') === `#${hash}`);
            });

            // Show active section
            document.querySelectorAll('.page-section').forEach(el => {
                el.classList.toggle('active', el.id === `${hash}-section`);
            });

            // Resize charts if analytics
            if (hash === 'analytics' && this.state.charts.warnings) {
                this.state.charts.warnings.resize();
            }
        };

        window.addEventListener('hashchange', handleHashChange);
        handleHashChange(); // Initial load
    },

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
                if (!this.state.mockMode) {
                    this.processUpdate(data);
                }
            });
        } catch (e) {
            console.log('Socket.IO not available, running in mock mode only.');
        }
    },

    setupMockGenerator() {
        setInterval(() => {
            if (this.state.mockMode) {
                const isChild = Math.random() > 0.7;
                const mockData = {
                    child_in_roi: isChild,
                    warning_on: isChild,
                    confidence: isChild ? 0.75 + Math.random() * 0.2 : 0.1 + Math.random() * 0.1,
                    timestamp: new Date().toISOString()
                };
                this.processUpdate(mockData);
            }
        }, 1000);

        setInterval(() => {
            this.updateTime();
        }, 1000);
    },

    processUpdate(data) {
        this.state.lastUpdate = new Date();
        this.state.systemState = { ...this.state.systemState, ...data };
        this.state.systemState.roi_status = data.child_in_roi ? 'INSIDE' : 'OUTSIDE';

        // Update Live View
        this.updateLiveView();

        // Add to logs
        const logEntry = {
            id: Date.now(),
            timestamp: new Date().toLocaleTimeString(),
            child_detected: data.child_in_roi,
            in_roi: data.child_in_roi,
            warning: data.warning_on,
            confidence: data.confidence,
            latency: Math.floor(Math.random() * 50) + 10, // Mock latency
            scenario: this.getMockScenario()
        };
        this.state.logs.unshift(logEntry);
        if (this.state.logs.length > 100) this.state.logs.pop(); // Keep last 100

        this.renderLogs();
        this.updateAnalytics();
    },

    getMockScenario() {
        const scenarios = ['Standard', 'Crowded', 'Shadows', 'Rain'];
        return scenarios[Math.floor(Math.random() * scenarios.length)];
    },

    updateLiveView() {
        document.getElementById('live-child').textContent = this.state.systemState.child_in_roi ? 'YES' : 'NO';
        document.getElementById('live-child').className = `card-value ${this.state.systemState.child_in_roi ? 'critical' : ''}`;
        
        document.getElementById('live-warning').textContent = this.state.systemState.warning_on ? 'ON' : 'OFF';
        document.getElementById('live-warning').className = `card-value ${this.state.systemState.warning_on ? 'critical' : ''}`;
        
        document.getElementById('live-conf').textContent = (this.state.systemState.confidence || 0).toFixed(2);
        
        document.getElementById('live-roi').textContent = this.state.systemState.roi_status;
        
        // Mock latency display
        document.getElementById('live-latency').textContent = `${Math.floor(Math.random() * 30) + 20}ms`;

        // Update feed
        const feedContainer = document.getElementById('event-feed');
        const entry = document.createElement('div');
        entry.className = 'feed-item';
        entry.style.padding = '8px 0';
        entry.style.borderBottom = '1px solid #eee';
        entry.innerHTML = `<small>${new Date().toLocaleTimeString()}</small> - ${this.state.systemState.child_in_roi ? '<span style="color:red"><b>Child Detected</b></span>' : 'No Detection'}`;
        feedContainer.prepend(entry);
        if (feedContainer.children.length > 20) feedContainer.lastChild.remove();
    },

    updateConnectionStatus() {
        const chip = document.getElementById('connection-chip');
        if (this.state.isConnected) {
            chip.className = 'status-chip connected';
            chip.innerHTML = '<div class="status-indicator"></div> Connected';
        } else {
            chip.className = 'status-chip mock';
            chip.innerHTML = '<div class="status-indicator"></div> Offline (Mock)';
        }
    },

    updateTime() {
        const now = new Date();
        document.getElementById('last-update').textContent = `Last Update: ${now.toLocaleTimeString()}`;
    },

    renderLogs() {
        const tbody = document.getElementById('logs-body');
        if (!tbody) return;

        // Apply filters (mock)
        const filterWarning = document.getElementById('filter-warning')?.checked;
        const filterRoi = document.getElementById('filter-roi')?.checked;

        const filtered = this.state.logs.filter(log => {
            if (filterWarning && !log.warning) return false;
            if (filterRoi && !log.in_roi) return false;
            return true;
        });

        tbody.innerHTML = filtered.slice(0, 15).map(log => `
            <tr>
                <td>${log.timestamp}</td>
                <td><span class="badge ${log.child_detected ? 'badge-warning' : 'badge-neutral'}">${log.child_detected ? 'YES' : 'NO'}</span></td>
                <td>${log.in_roi ? 'YES' : 'NO'}</td>
                <td><span class="badge ${log.warning ? 'badge-warning' : 'badge-success'}">${log.warning ? 'ON' : 'OFF'}</span></td>
                <td>${(log.confidence || 0).toFixed(2)}</td>
                <td>${log.latency}ms</td>
                <td>${log.scenario}</td>
            </tr>
        `).join('');
    },

    setupCharts() {
        const ctxP = document.getElementById('warningsChart')?.getContext('2d');
        if (ctxP) {
            this.state.charts.warnings = new Chart(ctxP, {
                type: 'line',
                data: {
                    labels: Array(10).fill(''),
                    datasets: [{
                        label: 'Warnings',
                        data: Array(10).fill(0),
                        borderColor: '#FF2400',
                        tension: 0.4
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
    },

    updateAnalytics() {
        // Update Chart
        if (this.state.charts.warnings) {
            const chart = this.state.charts.warnings;
            chart.data.labels.push(new Date().toLocaleTimeString());
            chart.data.labels.shift();
            chart.data.datasets[0].data.push(this.state.systemState.warning_on ? 1 : 0);
            chart.data.datasets[0].data.shift();
            chart.update('none');
        }

        // Update KPIs
        const totalWarnings = this.state.logs.filter(l => l.warning).length;
        document.getElementById('kpi-warnings').textContent = totalWarnings;
        document.getElementById('kpi-detections').textContent = this.state.logs.filter(l => l.child_detected).length;
        document.getElementById('kpi-avg-latency').textContent = '34ms';
    },

    setupROI() {
        const canvas = document.getElementById('roi-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const img = new Image();
        img.src = '/static/img/sample.jpg'; // Placeholder or upload
        // Draw logic would go here. For prototypte, we just show coords.
        
        img.onload = () => {
             ctx.drawImage(img, 0, 0, 400, 300);
             ctx.strokeStyle = 'red';
             ctx.lineWidth = 2;
             ctx.strokeRect(this.state.roi.x, this.state.roi.y, this.state.roi.w, this.state.roi.h);
        };
        
        // Mock save
        document.getElementById('save-roi').addEventListener('click', () => {
             localStorage.setItem('roi_settings', JSON.stringify(this.state.roi));
             alert('ROI Settings Saved to LocalStorage');
        });
    },

    exportCSV() {
        const headers = ["Timestamp,Child Detected,In ROI,Warning,Confidence,Latency,Scenario\n"];
        const rows = this.state.logs.map(log => 
            `${log.timestamp},${log.child_detected},${log.in_roi},${log.warning},${log.confidence.toFixed(2)},${log.latency},${log.scenario}`
        );
        const csvContent = "data:text/csv;charset=utf-8," + headers.concat(rows).join("\n");
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", "traffic_logs.csv");
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
};

document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
