"""AgentView: FastAPI example that monitors desktop agent state in realtime.

Run:
    python examples/agentview/main.py

Configure agent endpoints with:
    FDC3_AGENT_GRAPHQL_URL (default: http://localhost:8000/graphql)
    FDC3_AGENT_GRAPHQL_WS  (default: ws://localhost:8000/graphql)
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Set, TypedDict, cast

from gql import Client, gql
from gql.transport.httpx import HTTPXAsyncTransport
from gql.transport.websockets import WebsocketsTransport
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

AGENT_GRAPHQL_URL = os.getenv("FDC3_AGENT_GRAPHQL_URL", "http://localhost:8000/graphql")
AGENT_GRAPHQL_WS = os.getenv("FDC3_AGENT_GRAPHQL_WS", "ws://localhost:8000/graphql")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = cast(AppState, app.state)
    state.snapshot_task = asyncio.create_task(_snapshot_loop())
    state.subscription_task = asyncio.create_task(_subscribe_channel_events())
    try:
        yield
    finally:
        tasks = [state.snapshot_task, state.subscription_task]
        for task in tasks:
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in tasks if task is not None),
            return_exceptions=True,
        )


app = FastAPI(title="AgentView", lifespan=lifespan)


class AppState:
    snapshot_task: asyncio.Task[None] | None
    subscription_task: asyncio.Task[None] | None


class ChannelSnapshot(TypedDict):
    id: str
    type: str
    displayName: str | None
    color: str | None
    memberCount: int
    members: List[str]


class InstanceSnapshot(TypedDict):
    appId: str
    instanceId: str
    instanceUuid: str
    connected: bool
    channels: List[str]


class AgentSnapshot(TypedDict):
    version: str
    instances: List[InstanceSnapshot]
    channels: List[ChannelSnapshot]


class ChannelEvent(TypedDict):
    eventType: str
    channelId: str
    instanceUuid: str | None
    context: str | None
    timestamp: str


class OutboundMessage(TypedDict):
    type: str
    data: Any


_clients: Set[WebSocket] = set()
_clients_lock = asyncio.Lock()


async def _broadcast(payload: OutboundMessage) -> None:
    async with _clients_lock:
        clients = list(_clients)
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception:
            async with _clients_lock:
                _clients.discard(ws)


async def _fetch_snapshot() -> AgentSnapshot:
    snapshot_query = gql(
        """
        query AgentSnapshot {
          version
          instances {
            appId
            instanceId
            instanceUuid
            connected
            channels
          }
          channels {
            id
            type
            displayName
            color
            memberCount
            members
          }
        }
        """
    )
    transport = HTTPXAsyncTransport(url=AGENT_GRAPHQL_URL, timeout=10.0)
    async with Client(
        transport=transport,
        fetch_schema_from_transport=False,
    ) as session:
        data = await session.execute(snapshot_query)

    return cast(AgentSnapshot, data)


async def _snapshot_loop() -> None:
    while True:
        try:
            snapshot = await _fetch_snapshot()
            await _broadcast({"type": "snapshot", "data": snapshot})
        except Exception as exc:
            logger.warning("snapshot fetch failed: %s", exc)
        await asyncio.sleep(5)


async def _subscribe_graphql(query: Any) -> AsyncIterator[Dict[str, Any]]:
    transport = WebsocketsTransport(
        url=AGENT_GRAPHQL_WS,
        subprotocols=["graphql-ws"],
    )
    async with Client(
        transport=transport,
        fetch_schema_from_transport=False,
    ) as session:
        async for result in session.subscribe(query):
            yield result


async def _subscribe_channel_events() -> None:
    query = gql(
        """
        subscription AgentChannelEvents {
          channelEvents { eventType channelId instanceUuid context timestamp }
        }
        """
    )

    while True:
        try:
            async for result in _subscribe_graphql(query):
                payload = (result or {}).get("channelEvents")
                if payload is not None:
                    await _broadcast(
                        {"type": "event", "data": cast(ChannelEvent, payload)}
                    )
        except Exception as exc:
            logger.warning("subscription error: %s", exc)
            await asyncio.sleep(1)


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>AgentView</title>
    <style>
      body { font-family: sans-serif; margin: 20px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
      pre { background: #f6f6f6; padding: 10px; border-radius: 6px; }
      .events { max-height: 320px; overflow: auto; border: 1px solid #ddd; padding: 10px; }
      .event { border-bottom: 1px solid #eee; padding: 6px 0; }
    .meta { color: #666; font-size: 12px; }
      .snapshot-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fafafa; }
    .card h3 { margin: 0 0 10px 0; font-size: 14px; text-transform: uppercase; letter-spacing: 0.02em; color: #444; }
      .list { margin: 0; padding: 0; list-style: none; }
    .list li { padding: 8px 0; border-bottom: 1px solid #eee; }
      .list li:last-child { border-bottom: none; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
    .row { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
    .title { font-weight: 600; color: #222; }
    .muted { color: #777; }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border-radius: 999px; background: #e9eefb; color: #2b4db3; font-size: 12px; font-weight: 600; }
    .badge { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 6px; background: #e6f4ea; color: #1f7a3a; font-size: 12px; font-weight: 600; }
    .kv { display: flex; gap: 6px; align-items: center; font-size: 12px; color: #555; }
    .kv span { font-weight: 600; color: #333; }
    .stack { display: grid; gap: 4px; }
    details.members { margin-top: 6px; }
    details.members summary { cursor: pointer; color: #2b4db3; font-size: 12px; list-style: none; }
    details.members summary::-webkit-details-marker { display: none; }
    details.members ul { margin: 6px 0 0 0; padding: 0; list-style: none; }
    details.members li { padding: 2px 0; color: #444; font-size: 12px; }
    </style>
  </head>
  <body>
    <h1>AgentView</h1>
    <p>Realtime view of agent state via GraphQL + WebSocket.</p>
    <div class="grid">
      <div>
        <h2>Snapshot</h2>
                <div class="snapshot-grid">
                    <div class="card">
                        <h3>Version</h3>
                        <div id="snapshot-version" class="mono">Loading…</div>
                    </div>
                    <div class="card">
                        <h3>Instances</h3>
                        <ul id="snapshot-instances" class="list"></ul>
                    </div>
                    <div class="card">
                        <h3>Channels</h3>
                        <ul id="snapshot-channels" class="list"></ul>
                    </div>
                </div>
      </div>
      <div>
        <h2>Channel Events</h2>
        <div id="events" class="events"></div>
      </div>
    </div>

    <script>
      const ws = new WebSocket(`ws://${location.host}/ws`);
    const snapshotVersionEl = document.getElementById('snapshot-version');
    const snapshotInstancesEl = document.getElementById('snapshot-instances');
    const snapshotChannelsEl = document.getElementById('snapshot-channels');
      const eventsEl = document.getElementById('events');
    let instanceNameByUuid = {};
    let instanceAppByUuid = {};

      function addEvent(ev) {
                const name = instanceNameByUuid[ev.instanceUuid] || ev.instanceUuid || 'system';
        const div = document.createElement('div');
        div.className = 'event';
        div.innerHTML = `<div><strong>${ev.eventType}</strong> — <em>${ev.channelId}</em></div>` +
                    `<div class="meta">instance: ${name} — ${ev.timestamp}</div>` +
          (ev.context ? `<pre>${ev.context}</pre>` : '');
        eventsEl.prepend(div);
      }

            function renderSnapshot(snapshot) {
                snapshotVersionEl.textContent = snapshot.version || 'unknown';

                snapshotInstancesEl.innerHTML = '';
                instanceNameByUuid = {};
                instanceAppByUuid = {};
                (snapshot.instances || []).forEach(inst => {
                    const li = document.createElement('li');
                    const channels = (inst.channels || []).join(', ');
                    const name = `${inst.appId} / ${inst.instanceId}`;
                    instanceNameByUuid[inst.instanceUuid] = name;
                    instanceAppByUuid[inst.instanceUuid] = inst.appId;
                    li.innerHTML =
                        `<div class="row"><div class="title">${inst.appId}</div>` +
                        `<div class="muted">${inst.instanceId}</div></div>` +
                        `<div class="stack">` +
                        `<div class="kv mono"><span>uuid</span>${inst.instanceUuid}</div>` +
                        `<div class="row">` +
                        `<div class="pill">${inst.connected ? 'connected' : 'disconnected'}</div>` +
                        `<div class="kv mono"><span>channels</span>${channels || 'none'}</div>` +
                        `</div>` +
                        `</div>`;
                    snapshotInstancesEl.appendChild(li);
                });

                snapshotChannelsEl.innerHTML = '';
                (snapshot.channels || []).forEach(ch => {
                    const li = document.createElement('li');
                    const members = (ch.members || []).map(uuid => instanceAppByUuid[uuid] || uuid);
                    const membersText = members.length ? members.join(', ') : 'none';
                    const membersList = members.length
                        ? members.map(member => `<li>${member}</li>`).join('')
                        : '<li>none</li>';
                    li.innerHTML =
                        `<div class="row">` +
                        `<div class="title">${ch.id}</div>` +
                        `<div class="pill">${ch.type}</div>` +
                        `<div class="badge">${ch.memberCount} members</div>` +
                        `<div class="kv mono"><span>display</span>${ch.displayName || '—'}</div>` +
                        `</div>`;
                    li.innerHTML +=
                        `<details class="members">` +
                        `<summary>Joined (${members.length})</summary>` +
                        `<ul class="mono">${membersList}</ul>` +
                        `</details>`;
                    snapshotChannelsEl.appendChild(li);
                });
            }

      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === 'snapshot') {
                    renderSnapshot(data.data || {});
        } else if (data.type === 'event') {
          addEvent(data.data);
        }
      };
    </script>
  </body>
</html>
"""
    )


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    async with _clients_lock:
        _clients.add(websocket)

    try:
        snapshot = await _fetch_snapshot()
        await websocket.send_json({"type": "snapshot", "data": snapshot})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _clients_lock:
            _clients.discard(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
