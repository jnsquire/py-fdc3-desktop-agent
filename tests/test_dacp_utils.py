from fdc3.desktop_agent.handlers.dacp import DACPHandler
from fdc3.models.dacp.dacp import Fdc3Context
from fdc3.models.primitives import RequestUuid
from typing import cast


def test_normalize_app_id_variants():
    assert DACPHandler._normalize_app_id(None) is None
    assert DACPHandler._normalize_app_id("") is None
    assert DACPHandler._normalize_app_id("app@desktop") == "app"
    # if the part before @ is empty, return original
    assert DACPHandler._normalize_app_id("@desktop") == "@desktop"


def test_matches_result_type_and_typed_channel():
    assert DACPHandler._matches_result_type(None, None)
    assert DACPHandler._matches_result_type("x", "x")
    assert not DACPHandler._matches_result_type("x", None)
    assert DACPHandler._matches_result_type("channel", "channel<foo>")
    assert DACPHandler._matches_result_type("channel<foo>", "channel<foo>")
    assert not DACPHandler._matches_result_type("channel<foo>", "channel<bar>")


def test_extract_typed_channel_context():
    assert DACPHandler._extract_typed_channel_context(None) is None
    assert DACPHandler._extract_typed_channel_context("channel<foo>") == "foo"
    assert DACPHandler._extract_typed_channel_context("channel<>") is None


def test_is_nothing_and_normalize_context_and_context_as_dict():
    assert DACPHandler._is_nothing_context({"type": "fdc3.nothing"})
    assert not DACPHandler._is_nothing_context({"type": "other"})
    # normalize_context should return dict copies for dict inputs
    ctx = {"type": "fdc3.test"}
    assert DACPHandler._normalize_context(ctx) == ctx
    assert DACPHandler._normalize_context(None) is None
    assert DACPHandler._context_as_dict(None) is None
    typed_ctx = cast(Fdc3Context, {"type": "fdc3.test"})
    assert DACPHandler._context_as_dict(typed_ctx) == {"type": "fdc3.test"}


def test_extract_storage_app_id_and_wire_app_metadata():
    class MetaA:
        app_id = "from_app_id"

    class MetaB:
        appId = "from_appId"

    assert DACPHandler._extract_storage_app_id(MetaA()) == "from_app_id"
    assert DACPHandler._extract_storage_app_id(MetaB()) == "from_appId"

    # wire app metadata maps attributes through
    class MetaC:
        name = "Name"
        version = "1.2"
        description = "desc"
        icons = None
        resultType = "rt"

    am = DACPHandler._wire_app_metadata("app1", MetaC())
    assert am.appId == "app1"
    assert am.name == "Name"
    assert am.version == "1.2"
    assert am.description == "desc"
    assert am.icons is None
    assert am.resultType == "rt"


def test_wire_channel_and_meta_from_request():
    class Disp:
        name = "X"
        color = "#000"
        glyph = "g"

    class Channel:
        id = "chan1"
        type = "user"
        display_metadata = Disp()

    w = DACPHandler._wire_channel(Channel())
    assert w.id == "chan1"
    assert w.type == "user"
    assert w.displayMetadata is not None
    assert w.displayMetadata.name == "X"

    # meta_from_request should copy requestUuid and bridge meta fields
    class Req:
        def __init__(self):
            self.meta = type("M", (), {"requestUuid": RequestUuid(root="r-1")})

    r = Req()
    bridge_meta = {"errorSources": ["a"], "errorDetails": "d"}
    meta = DACPHandler._meta_from_request(r, bridge_meta)
    assert meta.requestUuid.root == "r-1"
    assert meta.errorSources == ["a"]
    assert meta.errorDetails == "d"
