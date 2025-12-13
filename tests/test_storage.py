# Storage tests

import pytest
from fdc3_desktop_agent.storage import SqliteStorage, AppMetadata, LaunchConfig


class TestSqliteStorage:
    """Test SqliteStorage functionality"""

    @pytest.fixture
    async def storage(self):
        """Create in-memory storage for testing"""
        storage = SqliteStorage(":memory:")
        await storage.initialize()
        yield storage
        await storage.close()

    @pytest.mark.asyncio
    async def test_app_metadata_crud(self, storage):
        """Test app metadata create, read, update, delete"""
        # Create app metadata
        metadata = AppMetadata(
            app_id="test-app",
            name="Test Application",
            version="1.0.0",
            description="A test app",
            icons=[{"src": "icon.png", "size": "32x32"}],
            intents=["ViewChart", "CreateInteraction"],
        )

        # Add app
        await storage.apps.add_app(metadata)

        # Retrieve app
        retrieved = await storage.apps.get_app_metadata("test-app")
        assert retrieved is not None
        assert retrieved.app_id == "test-app"
        assert retrieved.name == "Test Application"
        assert retrieved.version == "1.0.0"
        assert retrieved.description == "A test app"
        assert len(retrieved.icons) == 1
        assert retrieved.intents == ["ViewChart", "CreateInteraction"]

        # List apps
        apps = await storage.apps.list_apps()
        assert len(apps) == 1
        assert apps[0].app_id == "test-app"

        # Remove app
        await storage.apps.remove_app("test-app")
        retrieved = await storage.apps.get_app_metadata("test-app")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_launch_config_crud(self, storage):
        """Test launch config create, read, update, delete"""
        # Create launch config
        config = LaunchConfig(
            app_id="test-app",
            command="python",
            args=["-m", "myapp"],
            env={"ENV_VAR": "value"},
            cwd="/path/to/app",
            timeout=60,
        )

        # Set config
        await storage.launch_configs.set_launch_config(config)

        # Retrieve config
        retrieved = await storage.launch_configs.get_launch_config("test-app")
        assert retrieved is not None
        assert retrieved.app_id == "test-app"
        assert retrieved.command == "python"
        assert retrieved.args == ["-m", "myapp"]
        assert retrieved.env == {"ENV_VAR": "value"}
        assert retrieved.cwd == "/path/to/app"
        assert retrieved.timeout == 60

        # Remove config
        await storage.launch_configs.remove_launch_config("test-app")
        retrieved = await storage.launch_configs.get_launch_config("test-app")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_origins_crud(self, storage):
        """Test allowed origins create, read, update, delete"""
        origins = ["https://example.com", "https://app.example.com"]

        # Set origins
        await storage.origins.set_allowed_origins("test-app", origins)

        # Retrieve origins
        retrieved = await storage.origins.get_allowed_origins("test-app")
        assert retrieved == origins

        # Update origins
        new_origins = ["https://new.example.com"]
        await storage.origins.set_allowed_origins("test-app", new_origins)
        retrieved = await storage.origins.get_allowed_origins("test-app")
        assert retrieved == new_origins

    @pytest.mark.asyncio
    async def test_empty_origins(self, storage):
        """Test getting origins for app with no origins set"""
        origins = await storage.origins.get_allowed_origins("nonexistent-app")
        assert origins == []

    @pytest.mark.asyncio
    async def test_app_not_found(self, storage):
        """Test getting metadata for non-existent app"""
        metadata = await storage.apps.get_app_metadata("nonexistent-app")
        assert metadata is None

    @pytest.mark.asyncio
    async def test_launch_config_not_found(self, storage):
        """Test getting launch config for non-existent app"""
        config = await storage.launch_configs.get_launch_config("nonexistent-app")
        assert config is None
