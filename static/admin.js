// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab + '-panel').classList.add('active');
        if (tab.dataset.tab === 'config') loadSMTPConfig();
    });
});

// API helpers
const API = {
    async get(path) {
        const res = await fetch('/api' + path);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },
    async post(path, data) {
        const res = await fetch('/api' + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },
    async put(path, data) {
        const res = await fetch('/api' + path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },
    async delete(path) {
        const res = await fetch('/api' + path, { method: 'DELETE' });
        if (!res.ok) throw new Error(await res.text());
        return true;
    }
};

function showMessage(msg, isError = false) {
    const el = document.getElementById('message');
    el.textContent = msg;
    el.style.display = 'block';
    el.style.background = isError ? '#da3633' : '#238636';
    setTimeout(() => el.style.display = 'none', 3000);
}

// ============ STATUS CONFIG ============
const STATUS_CLASS_MAP = {
    'operational': 'status-operational',
    'degraded': 'status-degraded',
    'down': 'status-outage',
    'maintenance': 'status-maintenance'
};

const STATUS_BANNER_CLASS_MAP = {
    'all_operational': 'operational',
    'degraded': 'degraded',
    'partial_outage': 'degraded',
    'major_outage': 'down',
    'maintenance': 'maintenance'
};

function getStatusBadge(status) {
    const cssClass = STATUS_CLASS_MAP[status] || 'status-operational';
    return `<span class="status-badge ${cssClass}">${status || 'unknown'}</span>`;
}

// ============ ENDPOINTS ============
let endpoints = [];

async function loadEndpoints() {
    try {
        endpoints = await API.get('/endpoints');
        renderEndpoints();
    } catch (e) {
        showMessage('Failed to load endpoints: ' + e.message, true);
    }
}

function renderEndpoints() {
    const tbody = document.getElementById('endpoints-tbody');
    if (endpoints.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="no-data">No endpoints configured</td></tr>';
        return;
    }
    tbody.innerHTML = endpoints.map(e => `
        <tr>
            <td>${escapeHtml(e.name)}</td>
            <td>${e.check_type.toUpperCase()}</td>
            <td>${escapeHtml(e.url || e.host + (e.port ? ':' + e.port : ''))}</td>
            <td>${e.check_interval}s</td>
            <td>${getStatusBadge(e.current_status)}</td>
            <td class="actions">
                <button class="btn btn-secondary" onclick="editEndpoint(${e.id})">Edit</button>
                <button class="btn btn-danger" onclick="deleteEndpoint(${e.id})">Delete</button>
            </td>
        </tr>
    `).join('');
}

function toggleEndpointFields() {
    const type = document.getElementById('endpoint-check_type').value;
    document.getElementById('url-field').style.display = type === 'http' ? 'block' : 'none';
    document.getElementById('host-field').style.display = type === 'tcp' || type === 'ping' ? 'block' : 'none';
    document.getElementById('port-field').style.display = type === 'tcp' ? 'block' : 'none';
    document.getElementById('expected-status-field').style.display = type === 'http' ? 'block' : 'none';
    sanitizeEndpointFieldsByType(type);
}

function sanitizeEndpointFieldsByType(checkType) {
    // Clear fields not applicable to the selected check type
    if (checkType === 'http') {
        document.getElementById('endpoint-host').value = '';
        document.getElementById('endpoint-port').value = '';
    } else if (checkType === 'tcp') {
        document.getElementById('endpoint-url').value = '';
    } else if (checkType === 'ping') {
        document.getElementById('endpoint-url').value = '';
        document.getElementById('endpoint-port').value = '';
    }
}

function openEndpointModal(id = null) {
    document.getElementById('endpoint-form').reset();
    document.getElementById('endpoint-id').value = '';
    document.getElementById('endpoint-modal-title').textContent = 'Add Endpoint';
    toggleEndpointFields();
    if (id) {
        const e = endpoints.find(ep => ep.id === id);
        if (e) {
            document.getElementById('endpoint-id').value = e.id;
            document.getElementById('endpoint-modal-title').textContent = 'Edit Endpoint';
            document.getElementById('endpoint-name').value = e.name;
            document.getElementById('endpoint-check_type').value = e.check_type;
            document.getElementById('endpoint-url').value = e.url || '';
            document.getElementById('endpoint-host').value = e.host || '';
            document.getElementById('endpoint-port').value = e.port || '';
            document.getElementById('endpoint-expected_status').value = e.expected_status || 200;
            document.getElementById('endpoint-timeout').value = e.timeout || 5;
            document.getElementById('endpoint-check_interval').value = e.check_interval || 60;
            document.getElementById('endpoint-is_enabled').value = e.is_enabled ? 'true' : 'false';
            toggleEndpointFields();
        }
    }
    document.getElementById('endpoint-modal').classList.add('active');
}

function closeEndpointModal() {
    document.getElementById('endpoint-modal').classList.remove('active');
}

function editEndpoint(id) {
    openEndpointModal(id);
}

async function saveEndpoint(e) {
    e.preventDefault();
    const id = document.getElementById('endpoint-id').value;
    const checkType = document.getElementById('endpoint-check_type').value;
    sanitizeEndpointFieldsByType(checkType);

    const data = {
        name: document.getElementById('endpoint-name').value,
        check_type: checkType,
        url: document.getElementById('endpoint-url').value || null,
        host: document.getElementById('endpoint-host').value || null,
        port: parseInt(document.getElementById('endpoint-port').value) || null,
        expected_status: parseInt(document.getElementById('endpoint-expected_status').value) || 200,
        timeout: parseInt(document.getElementById('endpoint-timeout').value) || 5,
        check_interval: parseInt(document.getElementById('endpoint-check_interval').value) || 60,
        is_enabled: document.getElementById('endpoint-is_enabled').value === 'true'
    };
    try {
        if (id) {
            await API.put('/endpoints/' + id, data);
            showMessage('Endpoint updated');
        } else {
            await API.post('/endpoints', data);
            showMessage('Endpoint created');
        }
        closeEndpointModal();
        loadEndpoints();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

async function deleteEndpoint(id) {
    if (!confirm('Delete this endpoint?')) return;
    try {
        await API.delete('/endpoints/' + id);
        showMessage('Endpoint deleted');
        loadEndpoints();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

// ============ INCIDENTS ============
let incidents = [];

async function loadIncidents() {
    try {
        incidents = await API.get('/incidents');
        renderIncidents();
    } catch (e) {
        showMessage('Failed to load incidents: ' + e.message, true);
    }
}

const SEVERITY_CLASS_MAP = {
    'critical': 'status-outage',
    'major': 'status-degraded',
    'minor': 'status-degraded',
    'cosmetic': 'status-maintenance'
};

const INCIDENT_STATUS_CLASS_MAP = {
    'investigating': 'status-outage',
    'identified': 'status-degraded',
    'monitoring': 'status-degraded',
    'resolved': 'status-operational'
};

function renderIncidents() {
    const tbody = document.getElementById('incidents-tbody');
    if (incidents.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="no-data">No incidents</td></tr>';
        return;
    }
    tbody.innerHTML = incidents.map(i => `
        <tr>
            <td>${escapeHtml(i.title)}</td>
            <td>${i.endpoint_name || '-'}</td>
            <td><span class="status-badge ${SEVERITY_CLASS_MAP[i.severity] || 'status-operational'}">${i.severity}</span></td>
            <td><span class="status-badge ${INCIDENT_STATUS_CLASS_MAP[i.status] || 'status-operational'}">${i.status}</span></td>
            <td>${formatDate(i.started_at)}</td>
            <td class="actions">
                ${i.resolved_at ? '' : '<button class="btn btn-primary" onclick="resolveIncident(' + i.id + ')">Resolve</button>'}
                <button class="btn btn-secondary" onclick="editIncident(' + i.id + ')">Edit</button>
                <button class="btn btn-danger" onclick="deleteIncident(' + i.id + ')">Delete</button>
            </td>
        </tr>
    `).join('');
}

function openIncidentModal(id = null) {
    document.getElementById('incident-form').reset();
    document.getElementById('incident-id').value = '';
    document.getElementById('incident-modal-title').textContent = 'Create Incident';
    
    // Load endpoints for dropdown
    const select = document.getElementById('incident-endpoint_id');
    select.innerHTML = endpoints.map(e => `<option value="${e.id}">${escapeHtml(e.name)}</option>`).join('');
    
    if (id) {
        const inc = incidents.find(i => i.id === id);
        if (inc) {
            document.getElementById('incident-id').value = inc.id;
            document.getElementById('incident-modal-title').textContent = 'Edit Incident';
            document.getElementById('incident-endpoint_id').value = inc.endpoint_id || '';
            document.getElementById('incident-title').value = inc.title;
            document.getElementById('incident-description').value = inc.description || '';
            document.getElementById('incident-severity').value = inc.severity;
            document.getElementById('incident-status').value = inc.status;
        }
    }
    document.getElementById('incident-modal').classList.add('active');
}

function closeIncidentModal() {
    document.getElementById('incident-modal').classList.remove('active');
}

function editIncident(id) {
    openIncidentModal(id);
}

async function saveIncident(e) {
    e.preventDefault();
    const id = document.getElementById('incident-id').value;
    const data = {
        endpoint_id: parseInt(document.getElementById('incident-endpoint_id').value) || null,
        title: document.getElementById('incident-title').value,
        description: document.getElementById('incident-description').value,
        severity: document.getElementById('incident-severity').value,
        status: document.getElementById('incident-status').value
    };
    try {
        if (id) {
            await API.put('/incidents/' + id, data);
            showMessage('Incident updated');
        } else {
            await API.post('/incidents', data);
            showMessage('Incident created');
        }
        closeIncidentModal();
        loadIncidents();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

async function resolveIncident(id) {
    try {
        await API.post('/incidents/' + id + '/resolve', {});
        showMessage('Incident resolved');
        loadIncidents();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

async function deleteIncident(id) {
    if (!confirm('Delete this incident?')) return;
    try {
        await API.delete('/incidents/' + id);
        showMessage('Incident deleted');
        loadIncidents();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

// ============ MAINTENANCE ============
let maintenanceWindows = [];

async function loadMaintenance() {
    try {
        maintenanceWindows = await API.get('/maintenance');
        renderMaintenance();
    } catch (e) {
        showMessage('Failed to load maintenance windows: ' + e.message, true);
    }
}

function renderMaintenance() {
    const tbody = document.getElementById('maintenance-tbody');
    if (maintenanceWindows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="no-data">No maintenance windows</td></tr>';
        return;
    }
    tbody.innerHTML = maintenanceWindows.map(m => `
        <tr>
            <td>${escapeHtml(m.title)}</td>
            <td>${m.endpoint_name || 'All'}</td>
            <td>${formatDate(m.scheduled_start)}</td>
            <td>${formatDate(m.scheduled_end)}</td>
            <td><span class="status-badge status-${m.is_active ? 'maintenance' : 'operational'}">${m.is_active ? 'Active' : 'Inactive'}</span></td>
            <td class="actions">
                <button class="btn btn-secondary" onclick="editMaintenance(' + m.id + ')">Edit</button>
                <button class="btn btn-danger" onclick="deleteMaintenance(' + m.id + ')">Delete</button>
            </td>
        </tr>
    `).join('');
}

function openMaintenanceModal(id = null) {
    document.getElementById('maintenance-form').reset();
    document.getElementById('maintenance-id').value = '';
    document.getElementById('maintenance-modal-title').textContent = 'Add Maintenance';
    
    // Load endpoints for dropdown
    const select = document.getElementById('maintenance-endpoint_id');
    select.innerHTML = '<option value="">All Endpoints</option>' + endpoints.map(e => `<option value="${e.id}">${escapeHtml(e.name)}</option>`).join('');
    
    if (id) {
        const m = maintenanceWindows.find(mw => mw.id === id);
        if (m) {
            document.getElementById('maintenance-id').value = m.id;
            document.getElementById('maintenance-modal-title').textContent = 'Edit Maintenance';
            document.getElementById('maintenance-endpoint_id').value = m.endpoint_id || '';
            document.getElementById('maintenance-title').value = m.title;
            document.getElementById('maintenance-description').value = m.description || '';
            document.getElementById('maintenance-scheduled_start').value = m.scheduled_start?.slice(0, 16) || '';
            document.getElementById('maintenance-scheduled_end').value = m.scheduled_end?.slice(0, 16) || '';
            document.getElementById('maintenance-is_active').value = m.is_active ? 'true' : 'false';
        }
    }
    document.getElementById('maintenance-modal').classList.add('active');
}

function closeMaintenanceModal() {
    document.getElementById('maintenance-modal').classList.remove('active');
}

function editMaintenance(id) {
    openMaintenanceModal(id);
}

async function saveMaintenance(e) {
    e.preventDefault();
    const id = document.getElementById('maintenance-id').value;
    const data = {
        endpoint_id: parseInt(document.getElementById('maintenance-endpoint_id').value) || null,
        title: document.getElementById('maintenance-title').value,
        description: document.getElementById('maintenance-description').value,
        scheduled_start: document.getElementById('maintenance-scheduled_start').value,
        scheduled_end: document.getElementById('maintenance-scheduled_end').value,
        is_active: document.getElementById('maintenance-is_active').value === 'true'
    };
    try {
        if (id) {
            await API.put('/maintenance/' + id, data);
            showMessage('Maintenance window updated');
        } else {
            await API.post('/maintenance', data);
            showMessage('Maintenance window created');
        }
        closeMaintenanceModal();
        loadMaintenance();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

async function deleteMaintenance(id) {
    if (!confirm('Delete this maintenance window?')) return;
    try {
        await API.delete('/maintenance/' + id);
        showMessage('Maintenance window deleted');
        loadMaintenance();
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

// ============ CONFIG ============
async function loadSMTPConfig() {
    try {
        const config = await API.get('/config/smtp');
        document.getElementById('smtp_host').value = config.smtp_host || '';
        document.getElementById('smtp_port').value = config.smtp_port || 587;
        document.getElementById('smtp_user').value = config.smtp_user || '';
        document.getElementById('smtp_password').value = '';
        document.getElementById('smtp_from').value = config.smtp_from || '';
        document.getElementById('smtp_tls').value = config.smtp_tls ? 'true' : 'false';
    } catch (e) {
        showMessage('Failed to load SMTP config: ' + e.message, true);
    }
}

async function saveSMTPConfig(e) {
    e.preventDefault();
    const data = {
        smtp_host: document.getElementById('smtp_host').value,
        smtp_port: parseInt(document.getElementById('smtp_port').value) || 587,
        smtp_user: document.getElementById('smtp_user').value,
        smtp_password: document.getElementById('smtp_password').value,
        smtp_from: document.getElementById('smtp_from').value,
        smtp_tls: document.getElementById('smtp_tls').value === 'true'
    };
    // Only send password if filled
    if (!data.smtp_password) delete data.smtp_password;
    try {
        await API.put('/config/smtp', data);
        showMessage('SMTP configuration saved');
    } catch (err) {
        showMessage('Error: ' + err.message, true);
    }
}

// ============ UTILS ============
function syncSection(btn, loadFn) {
    btn.textContent = '…';
    loadFn().finally(() => { btn.textContent = '⟳ Sync'; });
}

async function doFullSync() {
    const btn = document.querySelector('button[onclick="doFullSync()"]');
    btn.textContent = '…';
    try {
        await Promise.all([loadEndpoints(), loadIncidents(), loadMaintenance()]);
        await syncStatus();
        document.getElementById('last-sync-time').textContent = new Date().toLocaleTimeString();
    } finally {
        btn.textContent = '⟳ Sync All';
    }
}

async function syncStatus() {
    try {
        const data = await API.get('/status');
        const cssClass = STATUS_BANNER_CLASS_MAP[data.status] || 'operational';
        const banner = document.getElementById('status-banner');
        banner.className = 'status-banner status-banner-' + cssClass;
        let html = `<span style="font-weight:bold;text-transform:uppercase">${data.status}</span>`;
        if (data.endpoints_affected && data.endpoints_affected > 0) {
            html += ` <span>· ${data.endpoints_affected} endpoint${data.endpoints_affected !== 1 ? 's' : ''} affected</span>`;
        }
        if (data.active_incidents && data.active_incidents > 0) {
            html += ` <span>· ${data.active_incidents} active incident${data.active_incidents !== 1 ? 's' : ''}</span>`;
        }
        banner.innerHTML = html;
        banner.style.display = 'flex';
    } catch (e) {
        console.error('Failed to load status:', e);
    }
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
}

// Load all data in parallel on page load
Promise.all([loadEndpoints(), loadIncidents(), loadMaintenance()]).then(() => syncStatus());