from fdc3_desktop_agent import __version__, create_app, DesktopAgentConfig


def test_version():
    assert __version__ == "0.9.0"


def test_create_app():
    """Test that create_app returns a FastAPI app."""
    app = create_app(DesktopAgentConfig(db_path=":memory:"))
    assert app is not None
    assert app.title == "FDC3 Desktop Agent"
