from fdc3_desktop_agent import __version__, create_app, DesktopAgentConfig
from fdc3_desktop_agent.version import __version__ as package_version


def test_version():
    # Ensure package exposes the same version as the centralized version module
    assert __version__ == package_version


def test_create_app():
    """Test that create_app returns a FastAPI app."""
    app = create_app(DesktopAgentConfig(db_path=":memory:"))
    assert app is not None
    assert app.title == "FDC3 Desktop Agent"
