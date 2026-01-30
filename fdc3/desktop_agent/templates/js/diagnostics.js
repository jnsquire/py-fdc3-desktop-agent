'use strict';

// Mock diagnostic data (kept in-JS for demo)
const mockDiagnostics = [
  { name: 'WebSocket Server', status: 'pass', message: 'Running on port 8000' },
  { name: 'Database Connection', status: 'pass', message: 'SQLite database accessible' },
  { name: 'App Registry', status: 'pass', message: '1 system app registered' },
  { name: 'Intent Resolution', status: 'pass', message: 'System intents available' },
  { name: 'Access Control', status: 'warn', message: 'No origins configured' },
  { name: 'Channel Manager', status: 'pass', message: 'Default channels available' }
];

function displayDiagnostics(diagnostics) {
  const container = document.getElementById('health-checks');

  container.innerHTML = diagnostics.map(diagnostic => `
    <div class="diagnostic-item">
      <strong>${diagnostic.name}:</strong>
      <span class="status status-${diagnostic.status}">${diagnostic.status.toUpperCase()}</span>
      <p>${diagnostic.message}</p>
    </div>
  `).join('');
}

function runDiagnostics() {
  document.getElementById('run-diagnostics').disabled = true;
  document.getElementById('run-diagnostics').textContent = 'Running...';

  setTimeout(() => {
    displayDiagnostics(mockDiagnostics);
    document.getElementById('run-diagnostics').disabled = false;
    document.getElementById('run-diagnostics').textContent = 'Run Full Diagnostics';
    loadMetrics();
  }, 2000);
}

function setMetricText(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
}

function setServerStatus(status) {
  const el = document.getElementById('metric-server-status');
  if (!el) return;
  const normalized = (status || 'unknown').toLowerCase();
  el.textContent = normalized === 'running' ? 'Running' : normalized;
  el.classList.remove('status-pass', 'status-warn', 'status-fail');
  if (normalized === 'running') {
    el.classList.add('status-pass');
  } else {
    el.classList.add('status-warn');
  }
}

async function loadMetrics() {
  try {
    const response = await fetch('/api/diagnostics/metrics');
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const metrics = await response.json();
    setServerStatus(metrics.serverStatus);
    setMetricText('metric-active-connections', metrics.activeConnections ?? '-');
    setMetricText('metric-registered-apps', metrics.registeredApps ?? '-');
    setMetricText('metric-memory-usage', metrics.memoryUsageHuman ?? '-');
  } catch (error) {
    showStatus('Error loading system metrics: ' + error.message, 'error');
    setServerStatus('unknown');
    setMetricText('metric-active-connections', '-');
    setMetricText('metric-registered-apps', '-');
    setMetricText('metric-memory-usage', '-');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  displayDiagnostics(mockDiagnostics);
  document.getElementById('run-diagnostics').addEventListener('click', runDiagnostics);
  loadMetrics();
  setInterval(loadMetrics, 5000);
});
