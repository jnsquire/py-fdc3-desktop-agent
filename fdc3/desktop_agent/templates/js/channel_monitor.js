'use strict';

// Minimal graphql-ws client implementation for channel monitor
let socketMonitor = null;
let monitorSubId = '1';

document.getElementById && document.addEventListener('DOMContentLoaded', () => {
  const start = document.getElementById('start');
  const stop = document.getElementById('stop');
  const clearBtn = document.getElementById('clear');
  if (start && !start._bound) { start.addEventListener('click', startSubscription); start._bound = true; }
  if (stop && !stop._bound) { stop.addEventListener('click', stopSubscription); stop._bound = true; }
  if (clearBtn && !clearBtn._bound) { clearBtn.addEventListener('click', () => { document.getElementById('mermaidTarget').innerHTML = ''; }); clearBtn._bound = true; }
});

function appendEvent(ev) {
  const out = document.getElementById('events');
  if (out.querySelector('.meta')) out.querySelector('.meta').remove();
  const div = document.createElement('div');
  div.className = 'event';
  let ctx = '';
  let ctxButton = '';
  if (ev.context) {
    try { ctx = JSON.stringify(JSON.parse(ev.context), null, 2); ctxButton = `<button class="btn" type="button" onclick="toggleEventContext(this)">Show JSON</button>` } catch(e) { ctx = 'Invalid JSON'; }
  }
  div.innerHTML = `<div><strong>${ev.eventType}</strong> — <em>${ev.channelId}</em></div>` +
                   `<div class="meta">instance: ${ev.instanceUuid || 'system'} — ${ev.timestamp}</div>` +
                   `<div style="margin-top:6px">${ctxButton}<pre class="event-context" style="display:none;white-space:pre-wrap;background:#f9f9f9;padding:8px;border-radius:4px;margin-top:6px">${ctx}</pre></div>`;
  out.prepend(div);
}

function startSubscription() {
  const channel = document.getElementById('channel').value.trim();
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const host = location.host;
  const url = `${wsProto}://${host}/graphql`;

  socketMonitor = new WebSocket(url, 'graphql-ws');
  socketMonitor.onopen = () => {
    socketMonitor.send(JSON.stringify({ type: 'connection_init', payload: {} }));
    setTimeout(() => {
      const query = `subscription ($channelId: String) { channelEvents(channelId: $channelId) { eventType channelId instanceUuid context timestamp } }`;
      const payload = { query, variables: { channelId: channel || null } };
      socketMonitor.send(JSON.stringify({ id: monitorSubId, type: 'start', payload }));
    }, 50);

    // Toggle buttons to reflect active subscription
    const startBtn = document.getElementById('start');
    const stopBtn = document.getElementById('stop');
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;
  };

  socketMonitor.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.type === 'data' && data.id === monitorSubId) {
        const ev = data.payload.data.channelEvents;
        appendEvent(ev);
      }
    } catch (e) { console.warn('Invalid WS message', e); }
  };

  socketMonitor.onclose = () => { document.getElementById('start').disabled = false; document.getElementById('stop').disabled = true; };
}

function stopSubscription() {
  if (socketMonitor && socketMonitor.readyState === WebSocket.OPEN) { socketMonitor.send(JSON.stringify({ id: monitorSubId, type: 'stop' })); socketMonitor.close(); }
  document.getElementById('start').disabled = false; document.getElementById('stop').disabled = true;
}

window.appendEvent = appendEvent; // expose for other modules if needed
