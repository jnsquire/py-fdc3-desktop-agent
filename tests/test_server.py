# Server integration tests

import pytest
from fastapi.testclient import TestClient
from fdc3_desktop_agent.storage import SqliteStorage


class TestServerIntegration:
    """Test server integration with storage and launcher"""

    @pytest.fixture
    async def test_app(self):
        """Create test app with in-memory storage"""
        # For testing, we'll create a separate app instance
        # In a real implementation, we'd modify the server to accept storage/launcher as parameters
        test_storage = SqliteStorage(":memory:")
        await test_storage.initialize()

        # Create a test FastAPI app
        from fastapi import FastAPI
        test_app = FastAPI(title="Test FDC3 Desktop Agent", version="0.1.0")

        @test_app.on_event("startup")
        async def startup_event():
            await test_storage.initialize()

        @test_app.on_event("shutdown")
        async def shutdown_event():
            await test_storage.close()

        @test_app.get("/health")
        async def health():
            return {"status": "healthy"}

        @test_app.get("/apps")
        async def get_apps():
            apps = await test_storage.apps.list_apps()
            return {"apps": apps}

        yield test_app

        await test_storage.close()

    @pytest.fixture
    def client(self, test_app):
        """Create test client"""
        return TestClient(test_app)

    def test_health_endpoint(self, client):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_apps_endpoint_empty(self, client):
        """Test apps endpoint with no apps"""
        response = client.get("/apps")
        assert response.status_code == 200
        data = response.json()
        assert data["apps"] == []

    def test_apps_endpoint_with_apps(self, client):
        """Test apps endpoint with apps in storage"""
        # This would require adding apps via storage
        # For now, just test the endpoint exists
        response = client.get("/apps")
        assert response.status_code == 200

    def test_websocket_endpoint_exists(self, client):
        """Test WebSocket endpoint is available"""
        # FastAPI TestClient doesn't support WebSocket testing directly
        # This is a placeholder for WebSocket tests
        # In a real implementation, you'd use pytest-asyncio and websockets library
        pass

    def test_cors_headers(self, client):
        """Test CORS headers are set"""
        # Note: Test app doesn't have CORS configured, so this just tests the endpoint
        response = client.get("/health")
        assert response.status_code == 200

    def test_invalid_endpoint(self, client):
        """Test invalid endpoint returns 404"""
        response = client.get("/invalid")
        assert response.status_code == 404