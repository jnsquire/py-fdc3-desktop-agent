'use strict';

const MAX_EVENT_HISTORY = 50;
const WEBSOCKET_SUBID = '1';
let socket = null;
let subId = WEBSOCKET_SUBID;

// Load channels on page load
document.addEventListener('DOMContentLoaded', () => {
  loadChannels();
  // wire up create form
  const form = document.getElementById('createChannelForm');
  if (form) form.addEventListener('submit', async (e) => { e.preventDefault(); await createChannel(); });
  // monitoring controls
  const startBtn = document.getElementById('startMonitor');
  const stopBtn = document.getElementById('stopMonitor');
  const clearBtn = document.getElementById('clearEvents');
  if (startBtn && !startBtn._bound) { startBtn.addEventListener('click', startEventMonitor); startBtn._bound = true; }
  if (stopBtn && !stopBtn._bound) { stopBtn.addEventListener('click', stopEventMonitor); stopBtn._bound = true; }
  if (clearBtn && !clearBtn._bound) { clearBtn.addEventListener('click', () => { document.getElementById('eventsMonitor').innerHTML = ''; document.getElementById('eventsMonitor').innerHTML = '<p style="color: #666; text-align: center;">Not monitoring. Click "Start Monitoring" to see live events.</p>'; }); clearBtn._bound = true; }
});

async function loadChannels() {
  try {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: `query { channels { id type displayName color memberCount } }` }),
    });

    const result = await response.json();
    if (result.errors) { showStatus('Error loading channels: ' + result.errors[0].message, 'error'); return; }
    displayChannels(result.data.channels);
  } catch (error) {
    showStatus('Error loading channels: ' + error.message, 'error');
  }
}

// client-side pagination
let allChannels = [];
let currentChannelPage = 1;
let channelPageSize = 10;

function displayChannels(channels) {
  allChannels = channels || [];
  currentChannelPage = 1;
  renderChannels();
}

function renderChannels() {
  const container = document.getElementById('channelsList');
  const search = (document.getElementById('channel-search')?.value || '').toLowerCase();
  channelPageSize = parseInt(document.getElementById('channel-page-size')?.value) || channelPageSize;

  const filtered = allChannels.filter(c => {
    const id = (c.id || '').toLowerCase();
    const name = (c.displayName || '').toLowerCase();
    return id.includes(search) || name.includes(search);
  });

  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / channelPageSize));
  if (currentChannelPage > pages) currentChannelPage = pages;
  const start = (currentChannelPage - 1) * channelPageSize;
  const pageItems = filtered.slice(start, start + channelPageSize);

  if (pageItems.length === 0) {
    container.innerHTML = '<p style="color: #666;">No channels found. Create one above!</p>';
  } else {
    container.innerHTML = '';
    pageItems.forEach(channel => {
      const div = document.createElement('div');
      div.className = 'channel-card';

      const colorStyle = channel.color ? `background-color: ${channel.color}` : 'background-color: #ccc';
      const displayName = channel.displayName || channel.id;

      div.innerHTML = `
        <h3>
          <span class="channel-color" style="${colorStyle}"></span>
          ${displayName}
          <span class="badge ${channel.type}">${channel.type}</span>
        </h3>
        <div class="channel-info">
          <p><strong>ID:</strong> ${channel.id}</p>
          <p><strong>Members:</strong> ${channel.memberCount}</p>
        </div>
        <div class="channel-actions">
          <button onclick="viewMembers('${channel.id}')">View Members</button>
          <button onclick="showBroadcastForm('${channel.id}')">Broadcast Context</button>
          <button class="danger" onclick="deleteChannel('${channel.id}')">Delete</button>
        </div>
        <div id="members-${channel.id}" class="members-list" style="display: none;"></div>
        <div id="broadcast-${channel.id}" class="broadcast-form"></div>
      `;
      container.appendChild(div);
    });
  }

  document.getElementById('channel-page-info').textContent = `Page ${currentChannelPage} of ${pages} (${total} channels)`;
  document.getElementById('channel-prev').disabled = currentChannelPage <= 1;
  document.getElementById('channel-next').disabled = currentChannelPage >= pages;
  const stats = document.getElementById('channel-stats'); if (stats) stats.textContent = `${total} result${total === 1 ? '' : 's'}`;
}

async function createChannel() {
  const channelId = document.getElementById('channelId').value.trim();
  const channelType = document.getElementById('channelType').value;
  const displayName = document.getElementById('displayName').value.trim();
  const color = document.getElementById('color').value;

  const input = {
    channelId: channelId,
    channelType: channelType,
    displayMetadata: displayName || color ? {
      name: displayName || null,
      color: color || null,
      glyph: null
    } : null
  };

  try {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: `mutation CreateChannel($input: CreateChannelInput!) { createChannel(input: $input) { id type displayName color } }`, variables: { input } })
    });

    const result = await response.json();
    if (result.errors) { showStatus('Error creating channel: ' + result.errors[0].message, 'error'); return; }
    showStatus('Channel created', 'success');
    loadChannels();
  } catch (error) { showStatus('Error creating channel: ' + error.message, 'error'); }
}

async function deleteChannel(channelId) {
  if (!confirm(`Delete channel ${channelId}?`)) return;
  try {
    const response = await fetch('/graphql', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: `mutation DeleteChannel($id: String!) { deleteChannel(id: $id) }`, variables: { id: channelId } }) });
    const result = await response.json();
    if (result.errors) { showStatus('Error deleting channel: ' + result.errors[0].message, 'error'); return; }
    showStatus('Channel deleted', 'success');
    loadChannels();
  } catch (err) { showStatus('Error deleting channel: ' + err.message, 'error'); }
}

function viewMembers(channelId) {
  const el = document.getElementById(`members-${channelId}`);
  if (!el) return;
  if (el.style.display === 'block') { el.style.display = 'none'; el.innerHTML = ''; return; }
  // For demo: show placeholder content
  el.style.display = 'block';
  el.innerHTML = '<div class="member-item">user:alice</div><div class="member-item">app:chart</div>';
}

function showBroadcastForm(channelId) {
  const el = document.getElementById(`broadcast-${channelId}`);
  if (!el) return;
  if (el.style.display === 'block') { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = 'block';
  el.innerHTML = `
    <label>Context (JSON):</label>
    <textarea id="broadcast-context-${channelId}" rows="3" style="width:100%" placeholder='{ "id": "AAPL" }'></textarea>
    <div style="margin-top:8px"><button class="btn" onclick="broadcastContext('${channelId}')">Send</button></div>
  `;
}

async function broadcastContext(channelId) {
  const txt = document.getElementById(`broadcast-context-${channelId}`).value.trim();
  let ctx = null;
  try { ctx = txt ? JSON.parse(txt) : null; } catch (e) { showStatus('Invalid JSON: ' + e.message, 'error'); return; }
  try {
    const response = await fetch('/graphql', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: `mutation Broadcast($channelId: String!, $context: JSON) { broadcast(channelId: $channelId, context: $context) }`, variables: { channelId, context: ctx } }) });
    const result = await response.json();
    if (result.errors) { showStatus('Broadcast failed: ' + result.errors[0].message, 'error'); return; }
    showStatus('Broadcast queued', 'success');
  } catch (e) { showStatus('Broadcast failed: ' + e.message, 'error'); }
}

// Event monitor (websocket)
function startEventMonitor() {
  const channel = document.getElementById('channel-search')?.value.trim();
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const host = location.host;
  const url = `${wsProto}://${host}/graphql`;

  socket = new WebSocket(url, 'graphql-ws');
  socket.onopen = () => {
    socket.send(JSON.stringify({ type: 'connection_init', payload: {} }));
    setTimeout(() => {
      const query = `subscription ($channelId: String) { channelEvents(channelId: $channelId) { eventType channelId instanceUuid context timestamp } }`;
      const payload = { query, variables: { channelId: channel || null } };
      socket.send(JSON.stringify({ id: subId, type: 'start', payload }));
    }, 50);
  };

  socket.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.type === 'data' && data.id === subId) {
        const event = data.payload.data.channelEvents;
        appendEvent(event);
      }
    } catch (e) { console.warn('Invalid WS message', e); }
  };

  socket.onclose = () => { document.getElementById('startMonitor').disabled = false; document.getElementById('stopMonitor').disabled = true; };
  socket.onerror = (error) => { showStatus('WebSocket error: ' + (error.message || 'error'), 'error'); };

  document.getElementById('startMonitor').disabled = true;
  document.getElementById('stopMonitor').disabled = false;
}

function stopEventMonitor() {
  if (socket && socket.readyState === WebSocket.OPEN) { socket.send(JSON.stringify({ id: subId, type: 'stop' })); socket.close(); }
  document.getElementById('startMonitor').disabled = false;
  document.getElementById('stopMonitor').disabled = true;
}

function appendEvent(event) {
  const monitor = document.getElementById('eventsMonitor');
  if (monitor.querySelector('p')) { monitor.innerHTML = ''; }

  const eventDiv = document.createElement('div');
  eventDiv.className = 'event-item';

  let contextButtonHtml = '';
  let contextPreHtml = '';
  if (event.context) {
    try {
      const pretty = JSON.stringify(JSON.parse(event.context), null, 2);
      contextButtonHtml = `<button class="btn" type="button" onclick="toggleEventContext(this)">Show JSON</button>`;
      contextPreHtml = `<pre class="event-context" style="display:none">${pretty}</pre>`;
    } catch (e) {
      contextPreHtml = `<pre class="event-context" style="display:none">Invalid JSON</pre>`;
    }
  }

  eventDiv.innerHTML = `
    <div><strong>${event.event_type.toUpperCase()}</strong> — ${event.channel_id}</div>
    <div class="event-meta">Instance: ${event.instance_uuid || 'system'} — ${new Date(event.timestamp).toLocaleString()}</div>
    <div style="margin-top:6px">${contextButtonHtml}${contextPreHtml}</div>
  `;

  monitor.insertBefore(eventDiv, monitor.firstChild);
  while (monitor.children.length > MAX_EVENT_HISTORY) { monitor.removeChild(monitor.lastChild); }
}

// expose helpers used by inline buttons
window.viewMembers = viewMembers;
window.showBroadcastForm = showBroadcastForm;
window.broadcastContext = broadcastContext;
window.deleteChannel = deleteChannel;
