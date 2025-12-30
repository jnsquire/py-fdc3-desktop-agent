# Plugin API

The Plugin API allows you to extend the desktop agent with custom intent handlers. Plugins can intercept and handle intents before the standard resolution logic runs, enabling custom workflows, integrations with external systems, or specialized intent handling.

## Creating a Plugin

Create a plugin by subclassing `IntentHandlerPlugin`:

```python
from fdc3.desktop_agent import IntentHandlerPlugin, IntentHandlerResult

class MyCustomIntentHandler(IntentHandlerPlugin):
    """Handle custom intents for my application."""

    @property
    def name(self) -> str:
        return "my-custom-handler"

    @property
    def handled_intents(self) -> list[str]:
        # List of intent names this plugin can handle
        return ["ViewChart", "AnalyzeData", "ExportReport"]

    @property
    def priority(self) -> int:
        # Higher priority plugins are checked first (default is 0)
        return 10

    async def handle_intent(
        self,
        intent: str,
        context: dict,
        source: dict,
        target: dict | None = None,
    ) -> IntentHandlerResult:
        """Handle an intent request.

        Args:
            intent: The intent name (e.g., "ViewChart")
            context: The FDC3 context object being passed
            source: Metadata about the source application
            target: Optional target application metadata

        Returns:
            IntentHandlerResult indicating whether the intent was handled
        """
        if intent == "ViewChart":
            # Handle the intent and return a result
            chart_data = await self._generate_chart(context)
            return IntentHandlerResult(
                handled=True,
                result={"chartUrl": chart_data["url"]},
            )

        if intent == "AnalyzeData":
            try:
                analysis = await self._analyze(context)
                return IntentHandlerResult(handled=True, result=analysis)
            except Exception as e:
                return IntentHandlerResult(handled=True, error=str(e))

        # Return handled=False to let other plugins or default resolution handle it
        return IntentHandlerResult(handled=False)
```

## Registering Plugins

### Via Configuration

Pass plugins when creating the app:

```python
from fdc3.desktop_agent import create_app, DesktopAgentConfig

config = DesktopAgentConfig(
    plugins=[
        MyCustomIntentHandler(),
        AnotherPlugin(),
    ],
)
app = create_app(config)
```

### Via Entry Points (Automatic Discovery)

External packages can register plugins using Python's entry points system. This allows plugins to be automatically discovered and loaded when the agent starts.

Add an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."fdc3.plugins"]
my-handler = "my_package.plugins:MyCustomIntentHandler"
analytics = "my_package.plugins:AnalyticsPlugin"
```

When the FDC3 Desktop Agent starts, it will automatically discover and instantiate these plugins. The entry point value must be a class that inherits from `IntentHandlerPlugin` and can be instantiated with no arguments.

**Controlling Auto-Discovery:**

Auto-discovery is enabled by default. You can disable it:

```python
# Via configuration
config = DesktopAgentConfig(auto_discover_plugins=False)

# Or via environment variable
# FDC3_AUTO_DISCOVER_PLUGINS=false
```

**Listing Available Plugins:**

```python
from fdc3.desktop_agent import list_plugin_entry_points, discover_plugins

# List entry points without loading
entry_points = list_plugin_entry_points()
for ep in entry_points:
    print(f"{ep['name']}: {ep['value']}")

# Discover and instantiate all plugins
plugins = discover_plugins()
for plugin in plugins:
    print(f"{plugin.name}: handles {plugin.handled_intents}")
```

### At Runtime

Register plugins dynamically through `CoreServices`:

```python
# During lifespan or within your application logic
plugin = MyCustomIntentHandler()
await core_services.register_plugin(plugin)

# Later, if needed
await core_services.unregister_plugin(plugin)
```

## Plugin Lifecycle

Plugins have lifecycle hooks that are called during registration:

```python
class MyPlugin(IntentHandlerPlugin):
    async def on_register(self, core_services) -> None:
        """Called when the plugin is registered.

        Use this to initialize resources, subscribe to events, etc.
        """
        self.db = await self._connect_to_database()
        # Access core services if needed
        self._core = core_services

    async def on_unregister(self) -> None:
        """Called when the plugin is unregistered.

        Use this to clean up resources.
        """
        await self.db.close()
```

## Intent Resolution Order

When an intent is raised:

1. **System intents** (like `fdc3.StartApp`) are handled first by the agent
2. **Plugins** are checked in priority order (highest first)
   - The first plugin returning `handled=True` wins
   - If a plugin returns an error, it's returned to the caller
3. **Standard resolution** proceeds if no plugin handled the intent

## IntentHandlerResult

The result object controls how the intent is processed:

| Field     | Type            | Description                                             |
| --------- | --------------- | ------------------------------------------------------- |
| `handled` | `bool`          | `True` if the plugin handled the intent                 |
| `result`  | `dict \| None` | The result to return to the caller (if handled successfully) |
| `error`   | `str \| None`  | Error message to return (if handled but failed)         |

```python
# Successfully handled
IntentHandlerResult(handled=True, result={"data": "value"})

# Handled but with error
IntentHandlerResult(handled=True, error="Failed to process")

# Not handled - let another plugin or default resolution try
IntentHandlerResult(handled=False)
```
