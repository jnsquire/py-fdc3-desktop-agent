# System flowcharts

This document breaks the agent into a few small Mermaid diagrams so they render cleanly in VS Code’s Markdown preview and are easier to reason about.

## 1) High-level overview

This shows the major subsystems and how requests enter the system (WebSocket, HTTP pages, GraphQL), plus the optional bridging/distributed components.

```mermaid
flowchart LR
	subgraph Clients["Clients / Integrations"]
		WebApp["FDC3 Web App (Browser)"]
		AdminUI["Admin UI (Browser)"]
		LaunchedApp["Launched App Process"]
		ExternalHandlerProc["External Handler Process"]
		Bridge["Desktop Agent Bridge (BCP/BMP)"]
		Etcd[(etcd)]
		Consul[(Consul)]
	end

	subgraph Runtime["Runtime (ASGI)"]
		Uvicorn["Uvicorn / ASGI Server"]
		FastAPI["FastAPI App (create_app)"]
		WS["WebSocket /ws"]
		HTTP["HTTP Pages (/admin, /diagnostics, ...)"]
		GQL["GraphQL /graphql (Strawberry)"]
	end

	subgraph Core["Core Services (shared singleton state)"]
		CoreServices["CoreServices singleton"]
		AppReg["AppRegistry"]
		ListenerStore["ListenerStore"]
		ChannelMgr["ChannelManager"]
		CtxRouter["ContextRouter"]
		IntentRes["IntentResolver"]
		PluginReg["PluginRegistry"]
		ExtReg["ExternalHandlerRegistry"]
	end

	subgraph Data["Storage"]
		Storage["SqliteStorage"]
		SQLite[(SQLite DB file)]
	end

	subgraph Launching["App Launching"]
		Launcher["SubprocessLauncher"]
	end

	subgraph Bridging["Desktop Agent Bridging (optional)"]
		BridgeClient["BridgeClient"]
		BridgeRouter["BridgeRequestRouter"]
	end

	subgraph Distributed["Distributed Events (optional)"]
		DistAdapter["DistributedLogAdapter"]
	end

	WebApp <--> WS
	ExternalHandlerProc <--> WS
	AdminUI --> HTTP
	AdminUI --> GQL

	Uvicorn --> FastAPI
	FastAPI --> WS
	FastAPI --> HTTP
	FastAPI --> GQL

	WS --> CoreServices
	GQL --> CoreServices
	GQL --> Storage

	Storage --> SQLite
	CoreServices --> AppReg
	CoreServices --> ListenerStore
	CoreServices --> ChannelMgr
	CoreServices --> CtxRouter
	CoreServices --> IntentRes
	CoreServices --> PluginReg
	CoreServices --> ExtReg

	Launcher --> LaunchedApp

	BridgeClient <--> Bridge
	BridgeClient --> BridgeRouter
	BridgeRouter --> CoreServices
	BridgeRouter --> Storage
	BridgeRouter --> Launcher

	DistAdapter -.-> Etcd
	DistAdapter -.-> Consul
```

## 2) WebSocket protocol phases (WCP → DACP)

The `/ws` endpoint starts in the WCP handshake/identity validation phase. Once validated, it transitions to the DACP phase for ongoing FDC3 operations.

```mermaid
sequenceDiagram
	autonumber
	participant Client as Browser App / Client
	participant WS as /ws WebSocket
	participant AC as AccessControlHandler
	participant WCP as WCPHandler
	participant DACP as DACPHandler
	participant Core as CoreServices

	Client->>WS: Connect
	WS->>AC: validate_connection(origin, user-agent)
	AC-->>WS: allow/deny
	alt denied
		WS-->>Client: close(1008)
	else allowed
		Client->>WCP: WCP1Hello
		WCP-->>Client: WCP3Handshake
		Client->>WCP: WCP4ValidateAppIdentity
		WCP->>Core: register_instance(appId, instanceId, instanceUuid)
		WCP-->>Client: WCP5ValidateAppIdentityResponse
		Note over WS,DACP: Connection now in DACP mode
		Client->>DACP: DACP requests (broadcast/open/find/raise...)
		DACP->>Core: route via listeners/channels/intent resolver
	end
```

## 3) Core services and message routing

This diagram focuses on how context and intents move through the in-memory core. The core is a singleton so WebSocket handlers, GraphQL, plugins, and background components all share the same state.

```mermaid
flowchart TB
	CoreServices["CoreServices singleton"]

	AppReg["AppRegistry<br/>instances + connection state"]
	ListenerStore["ListenerStore<br/>context/intent listeners"]
	ChannelMgr["ChannelManager<br/>channels + events"]
	CtxRouter["ContextRouter<br/>broadcast routing"]
	IntentRes["IntentResolver<br/>resolve + deliver intents"]
	PluginReg["PluginRegistry<br/>in-process intent plugins"]
	ExtReg["ExternalHandlerRegistry<br/>external process handlers"]

	CoreServices --> AppReg
	CoreServices --> ListenerStore
	CoreServices --> ChannelMgr
	CoreServices --> CtxRouter
	CoreServices --> IntentRes
	CoreServices --> PluginReg
	CoreServices --> ExtReg

	CtxRouter --> ListenerStore
	CtxRouter --> ChannelMgr
	CtxRouter --> AppReg
	IntentRes --> ListenerStore
	IntentRes --> AppReg
```

## 4) Storage + admin/GraphQL surfaces

Admin pages are static HTML templates, while GraphQL provides read/write access to app directory and launch config data plus observability over connected instances and channels.

```mermaid
flowchart LR
	AdminUI["Admin UI (Browser)"]
	HTTP["HTTP pages (/admin, /diagnostics, ...)"]
	Templates["Jinja2 templates"]
	GQL["GraphQL /graphql"]
	GraphQLSchema["Schema + resolvers"]
	Storage["SqliteStorage"]
	SQLite[(SQLite DB file)]
	Core["CoreServices"]

	AdminUI --> HTTP --> Templates
	AdminUI --> GQL --> GraphQLSchema
	GraphQLSchema --> Storage --> SQLite
	GraphQLSchema --> Core
```

## 5) Desktop Agent Bridging (experimental, optional)

When bridging is enabled, the agent maintains an outbound WebSocket connection to a Desktop Agent Bridge. Some outbound actions are forwarded best-effort, and inbound bridged requests are routed through the BridgeRequestRouter into local storage/core/launcher/connection manager.

```mermaid
flowchart LR
	subgraph Local["Local Desktop Agent"]
		DACP["DACPHandler"]
		BridgeClient["BridgeClient"]
		BridgeRouter["BridgeRequestRouter"]
		Core["CoreServices"]
		Storage["SqliteStorage"]
		Launcher["SubprocessLauncher"]
		ConnMgr["WebSocketConnectionManager"]
	end

	Bridge["Desktop Agent Bridge (BCP/BMP)"]

	DACP -. "forward broadcast / raiseIntent (targeted)" .-> BridgeClient
	BridgeClient <--> Bridge
	BridgeClient -. "inbound bridged requests" .-> BridgeRouter

	BridgeRouter --> Core
	BridgeRouter --> Storage
	BridgeRouter --> Launcher
	BridgeRouter --> ConnMgr
```

## 6) Distributed channel events (optional)

If a distributed adapter is configured, channel events are published to an external backend so multiple agent workers can observe each other’s channel activity. Local delivery still happens even if the adapter fails.

```mermaid
flowchart LR
	ChannelMgr["ChannelManager"]
	DistAdapter["DistributedLogAdapter\n(Noop/Etcd/Consul)"]
	Etcd[(etcd)]
	Consul[(Consul)]

	ChannelMgr -. "publish channel_events" .-> DistAdapter
	DistAdapter -.-> Etcd
	DistAdapter -.-> Consul
	DistAdapter -. "subscribe channel_events" .-> ChannelMgr
```
