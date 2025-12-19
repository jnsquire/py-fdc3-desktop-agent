import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fdc3.desktop_agent.storage.interfaces import Storage, LaunchConfig
from fdc3.desktop_agent.core import core_services
from fdc3.desktop_agent.server import create_app
from fdc3.desktop_agent.config import DesktopAgentConfig


@pytest.fixture
def mock_storage():
    """Mock storage instance"""
    storage = MagicMock(spec=Storage)

    # Mock apps
    mock_app = MagicMock()
    mock_app.app_id = "test-app"
    mock_app.name = "Test App"
    mock_app.version = "1.0.0"
    mock_app.description = "A test app"
    mock_app.icons = [{"src": "icon.png", "size": "32x32"}]
    mock_app.intents = ["test.intent"]

    storage.apps.list_apps = AsyncMock(return_value=[mock_app])

    # Mock launch configs
    mock_config = LaunchConfig(
        app_id="test-app",
        command="python",
        args=["-m", "test"],
        env={"TEST": "value"},
        cwd="/tmp",
        timeout=30,
    )
    storage.launch_configs.list_launch_configs = AsyncMock(return_value=[mock_config])
    storage.launch_configs.set_launch_config = AsyncMock()
    storage.launch_configs.remove_launch_config = AsyncMock()

    return storage


@pytest.fixture
def mock_channel_manager():
    """Mock channel manager"""
    manager = MagicMock()
    mock_channel = MagicMock()
    mock_channel.id = "test-channel"
    mock_channel.type = "user"
    mock_channel.members = ["instance-1", "instance-2"]
    mock_channel.display_metadata = MagicMock()
    mock_channel.display_metadata.name = "Test Channel"
    mock_channel.display_metadata.color = "#ff0000"

    def create_channel(channel_id, channel_type, display_metadata):
        # Parse the channel_id to get the id part
        if ":" in channel_id:
            parsed_id = channel_id.split(":", 1)[1]
        else:
            parsed_id = channel_id
        mock_channel.id = parsed_id
        mock_channel.type = channel_type
        mock_channel.display_metadata = display_metadata
        mock_channel.members = [
            "instance-1",
            "instance-2",
        ]  # Set members for memberCount
        return mock_channel

    manager.list_channels.return_value = [mock_channel]
    manager.get_channel_members.return_value = ["instance-1", "instance-2"]
    manager.subscribe_to_events.return_value = "sub-123"
    manager.unsubscribe_from_events = MagicMock()
    manager.create_channel = create_channel
    manager.channels = {"test-channel": mock_channel}
    manager.instance_channels = {"instance-1": "test-channel"}
    manager._emit_event = MagicMock()
    manager.broadcast_to_channel = MagicMock()

    return manager


@pytest.fixture
def test_app(mock_storage, mock_channel_manager):
    """Create test FastAPI app with mocked dependencies"""
    config = DesktopAgentConfig(
        storage=mock_storage,
        auto_discover_plugins=False,
        plugins=[],
        distributed_adapter=None,
    )

    with patch.object(core_services, "channel_manager", mock_channel_manager):
        app = create_app(config)
        yield app


@pytest.fixture(autouse=True)
def mock_core_services(mock_channel_manager):
    """Mock core services globally"""
    with patch.object(core_services, "channel_manager", mock_channel_manager):
        yield


@pytest.fixture
def client(test_app):
    """Test client for GraphQL API"""
    return TestClient(test_app)


class TestGraphQLQueries:
    def test_apps_query(self, client):
        """Test apps GraphQL query"""
        query = """
        query {
            apps {
                appId
                name
                version
                description
                icons {
                    src
                    size
                }
                intents
            }
        }
        """
        response = client.post("/graphql", json={"query": query})
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]["apps"]) == 1
        app = data["data"]["apps"][0]
        assert app["appId"] == "test-app"
        assert app["name"] == "Test App"
        assert app["version"] == "1.0.0"
        assert app["description"] == "A test app"
        assert len(app["icons"]) == 1
        assert app["icons"][0]["src"] == "icon.png"
        assert app["icons"][0]["size"] == "32x32"
        assert app["intents"] == ["test.intent"]

    def test_launch_configs_query(self, client):
        """Test launchConfigs GraphQL query"""
        query = """
        query {
            launchConfigs {
                appId
                command
                args
                env {
                    key
                    value
                }
                cwd
                timeout
            }
        }
        """
        response = client.post("/graphql", json={"query": query})
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]["launchConfigs"]) == 1
        config = data["data"]["launchConfigs"][0]
        assert config["appId"] == "test-app"
        assert config["command"] == "python"
        assert config["args"] == ["-m", "test"]
        assert len(config["env"]) == 1
        assert config["env"][0]["key"] == "TEST"
        assert config["env"][0]["value"] == "value"
        assert config["cwd"] == "/tmp"
        assert config["timeout"] == 30

    def test_instances_query(self, client):
        """Test instances GraphQL query"""
        # Mock app registry
        mock_instance = MagicMock()
        mock_instance.app_id = "test-app"
        mock_instance.instance_id = "instance-1"
        mock_instance.instance_uuid = "uuid-123"
        mock_instance.connected = True
        mock_instance.channels = ["channel-1"]

        with patch.object(
            core_services.app_registry, "list_instances", return_value=[mock_instance]
        ):
            query = """
            query {
                instances {
                    appId
                    instanceId
                    instanceUuid
                    connected
                    channels
                }
            }
            """
            response = client.post("/graphql", json={"query": query})
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]["instances"]) == 1
            instance = data["data"]["instances"][0]
            assert instance["appId"] == "test-app"
            assert instance["instanceId"] == "instance-1"
            assert instance["instanceUuid"] == "uuid-123"
            assert instance["connected"] is True
            assert instance["channels"] == ["channel-1"]

    def test_channels_query(self, client):
        """Test channels GraphQL query"""
        query = """
        query {
            channels {
                id
                type
                displayName
                color
                memberCount
            }
        }
        """
        response = client.post("/graphql", json={"query": query})
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]["channels"]) == 1
        channel = data["data"]["channels"][0]
        assert channel["id"] == "test-channel"
        assert channel["type"] == "user"
        assert channel["displayName"] == "Test Channel"
        assert channel["color"] == "#ff0000"
        assert channel["memberCount"] == 2


class TestGraphQLMutations:
    def test_create_launch_config_mutation(self, client):
        """Test createLaunchConfig GraphQL mutation"""
        mutation = """
        mutation CreateLaunchConfig($config: LaunchConfigInput!) {
            createLaunchConfig(config: $config) {
                appId
                command
                args
                env {
                    key
                    value
                }
                cwd
                timeout
            }
        }
        """
        variables = {
            "config": {
                "appId": "test-app",
                "command": "python",
                "args": ["-m", "test"],
                "env": [{"key": "TEST", "value": "value"}],
                "cwd": "/tmp",
                "timeout": 30,
            }
        }
        response = client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        config = data["data"]["createLaunchConfig"]
        assert config["appId"] == "test-app"
        assert config["command"] == "python"
        assert config["args"] == ["-m", "test"]
        assert len(config["env"]) == 1
        assert config["env"][0]["key"] == "TEST"
        assert config["env"][0]["value"] == "value"
        assert config["cwd"] == "/tmp"
        assert config["timeout"] == 30

    def test_delete_launch_config_mutation(self, client):
        """Test deleteLaunchConfig GraphQL mutation"""
        mutation = """
        mutation DeleteLaunchConfig($appId: String!) {
            deleteLaunchConfig(appId: $appId)
        }
        """
        variables = {"appId": "test-app"}
        response = client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["deleteLaunchConfig"] is True

    def test_create_channel_mutation(self, client):
        """Test createChannel GraphQL mutation"""
        mutation = """
        mutation CreateChannel($input: CreateChannelInput!) {
            createChannel(input: $input) {
                id
                type
                displayName
                color
                memberCount
            }
        }
        """
        variables = {
            "input": {
                "channelId": "user:test-channel",
                "channelType": "user",
                "displayMetadata": {"name": "Test Channel", "color": "#ff0000"},
            }
        }
        response = client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        channel = data["data"]["createChannel"]
        assert channel["id"] == "test-channel"
        assert channel["type"] == "user"
        assert channel["displayName"] == "Test Channel"
        assert channel["color"] == "#ff0000"
        assert channel["memberCount"] == 2

    def test_delete_channel_mutation(self, client):
        """Test deleteChannel GraphQL mutation"""
        mutation = """
        mutation DeleteChannel($channelId: String!) {
            deleteChannel(channelId: $channelId)
        }
        """
        variables = {"channelId": "test-channel"}
        response = client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["deleteChannel"] is True

    def test_broadcast_to_channel_mutation(self, client):
        """Test broadcastToChannel GraphQL mutation"""
        mutation = """
        mutation BroadcastToChannel($channelId: String!, $context: String!) {
            broadcastToChannel(channelId: $channelId, context: $context)
        }
        """
        variables = {"channelId": "test-channel", "context": '{"test": "data"}'}
        response = client.post(
            "/graphql", json={"query": mutation, "variables": variables}
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["broadcastToChannel"] is True


class TestGraphQLSubscriptions:
    def test_channel_events_subscription_setup(self, client):
        """Test channelEvents subscription setup"""
        # Note: Full subscription testing requires WebSocket support
        # This test verifies the subscription can be created without errors
        subscription_query = """
        subscription {
            channelEvents {
                eventType
                channelId
                instanceUuid
                context
            }
        }
        """
        # Just verify the query is valid (doesn't execute subscription)
        response = client.post("/graphql", json={"query": subscription_query})
        # Strawberry returns an error for subscriptions over HTTP
        assert response.status_code == 200
        data = response.json()
        assert "errors" in data  # Expected for HTTP subscription attempt
