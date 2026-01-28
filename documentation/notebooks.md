# Data Science & Jupyter Integration

The Python FDC3 Desktop Agent is uniquely suited for Data Science workflows, allowing you to bridge interactive analysis in Jupyter Notebooks or Streamlit with the broader desktop ecosystem.

## Using FDC3 in Jupyter

To use FDC3 within a notebook, install the client package:

```bash
pip install fdc3-client
```

### Initializing the Client

The `FDC3Client` automatically connects to the local agent via WebSocket.

```python
from fdc3.client import FDC3Client
import asyncio

# In a Jupyter cell (which supports top-level await in many environments)
client = FDC3Client()
await client.connect()

print(f"Connected as: {client.instance_id}")
```

### Listening for Contexts

You can use the agent to drive notebook updates when a user selects a ticker in another app (like Bloomberg or a specialized terminal).

```python
def on_instrument(context):
    ticker = context.get("id", {}).get("ticker")
    print(f"Selected Ticker: {ticker}")
    # Trigger cell re-calculation or update a hvPlot/Plotly widget here

await client.add_context_listener("fdc3.instrument", on_instrument)
```

### Broadcasting from a Notebook

Broadcasting from a notebook allows your analysis results to drive other desktop applications.

```python
# Broadcast a price update or a signal
await client.broadcast({
    "type": "fdc3.instrument",
    "name": "Apple Inc.",
    "id": { "ticker": "AAPL" }
})
```

## Streamlit Integration

Streamlit apps can serve as powerful FDC3-enabled dashboards.

```python
import streamlit as st
from fdc3.client import FDC3Client

st.title("FDC3 Analysis Dashboard")

if 'fdc3' not in st.session_state:
    client = FDC3Client()
    # Note: Streamlit lifecycle requires careful async management
    # Search for 'streamlit-async' patterns for production use
    st.session_state.fdc3 = client
```

## Why use this agent?

1. **Native Python**: No need to wrap Electron or use complex JavaScript bridges.
2. **Context-Aware Research**: Your research notebooks become "active" participants in your trading or analysis desktop.
3. **Easy Deployment**: Can be run as a sidecar to your data science environment.
