# Desktop Agent Bridging (experimental)

This agent supports the experimental FDC3 Desktop Agent Bridging protocols (BCP/BMP) to enable
cross-desktop-agent discovery and request forwarding via a Desktop Agent Bridge.

## Configuration

Desktop Agent Bridging (experimental) is configurable via environment variables:

- `FDC3_BRIDGE_ENABLED`: Enable bridging (default: `false`)
- `FDC3_BRIDGE_HOST`: Bridge host (default: `127.0.0.1`)
- `FDC3_BRIDGE_PORT_START`: Start of bridge discovery port range (default: `4475`)
- `FDC3_BRIDGE_PORT_END`: End of bridge discovery port range (default: `4575`)
- `FDC3_BRIDGE_REQUESTED_NAME`: Preferred Desktop Agent name to request from the bridge (default: machine hostname)
- `FDC3_BRIDGE_CONNECT_RETRY_SECONDS`: Seconds to wait before retrying discovery after exhausting the port range (default: `5`)
- `FDC3_BRIDGE_REQUEST_TIMEOUT_SECONDS`: Per-request timeout when awaiting a bridge response (default: `3`)

## Overview

- When enabled, the agent will attempt to connect to a bridge at `ws://<FDC3_BRIDGE_HOST>:<port>`
    by scanning ports in the configured range (`FDC3_BRIDGE_PORT_START`..`FDC3_BRIDGE_PORT_END`).
- On connect it performs the BCP handshake (hello -> handshake -> connectedAgentsUpdate).
- Once connected, the agent can:
    - forward `broadcast` messages to the bridge (best-effort; still delivered locally);
    - forward `raiseIntent` to a remote desktop agent when the request target includes `desktopAgent`.
- The agent can also accept requests forwarded from the bridge and service them locally.

Notes/limitations:

- Bridging is best-effort: the agent still starts if the bridge is down; it will retry until it connects.
- `channelsState` is currently reported as an empty map during handshake (no channel state sync yet).

## Enabling bridging

On macOS/Linux:

```bash
export FDC3_BRIDGE_ENABLED=true
export FDC3_BRIDGE_HOST=127.0.0.1
export FDC3_BRIDGE_PORT_START=4475
export FDC3_BRIDGE_PORT_END=4575
```

On Windows PowerShell:

```powershell
$env:FDC3_BRIDGE_ENABLED = "true"
$env:FDC3_BRIDGE_HOST = "127.0.0.1"
$env:FDC3_BRIDGE_PORT_START = "4475"
$env:FDC3_BRIDGE_PORT_END = "4575"
```
