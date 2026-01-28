# Getting started

This guide provides a single recommended path to get a working agent locally.

## 1) Start the agent (Docker)

```bash
docker-compose up
```

The agent will be available at:

- WebSocket: `ws://localhost:8000/ws`
- Admin UI: `http://localhost:8000/admin`
- GraphQL: `http://localhost:8000/graphql`

## 2) Run a sample client

```bash
python examples/tui_chat_client.py --name Alice --channel demo
```

Open a second client if you want to see events in both directions:

```bash
python examples/tui_chat_client.py --name Bob --channel demo
```

## 3) Register your first app

To add your own application to the agent, use the `fdc3-agent` CLI tool:

```bash
# Create a JSON definition for your app
cat <<EOF > my-app.json
{
  "appId": "my-app",
  "name": "My Application",
  "title": "My Analysis Tool",
  "manifest": {
    "url": "http://localhost:3000"
  },
  "intents": [
    { "name": "ViewChart", "contexts": ["fdc3.instrument"] }
  ],
  "launch": {
    "command": "python",
    "args": ["examples/tui_chat_client.py", "--name", "MyClient"]
  }
}
EOF

# Register it with the agent
fdc3-agent register-app my-app.json

# Verify it was added
fdc3-agent list-apps
```

You can also use the [Admin UI](http://localhost:8000/admin) to manage applications visually.

## 4) Next steps

- Configure the agent: see [configuration.md](configuration.md)
- Explore bridging (experimental): see [bridging.md](bridging.md)
- Review the embedding API: see [embedding-api.md](embedding-api.md)
