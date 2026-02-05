from fdc3.client.models import parse_message
from fdc3.models.dacp.dacp import BroadcastEvent
from fdc3.models.dacp.external_models import ForwardedIntentMessage
from pydantic import ValidationError
import pytest

from fdc3.models.dacp.dacp import MESSAGE_TYPE_MAP

base_meta_request = {"requestUuid": "r1", "timestamp": "2025-01-01T00:00:00Z"}
base_meta_response = {
    "requestUuid": "r1",
    "responseUuid": "resp1",
    "timestamp": "2025-01-01T00:00:00Z",
}
base_meta_event = {"eventUuid": "e1", "timestamp": "2025-01-01T00:00:00Z"}


def test_parse_broadcast_event():
    msg = {
        "type": "broadcastEvent",
        "payload": {"context": {"type": "test", "value": 1}},
        "meta": {"eventUuid": "e1", "timestamp": "2025-01-01T00:00:00Z"},
    }

    model = parse_message(msg)
    assert model is not None
    assert isinstance(model, BroadcastEvent)
    assert model.type == "broadcastEvent"
    assert model.payload.context["type"] == "test"


def test_parse_forwarded_intent():
    msg = {
        "type": "forwardedIntent",
        "payload": {
            "request_uuid": "r1",
            "intent": "TestIntent",
            "context": {"type": "test"},
        },
        "meta": {"requestUuid": "r1", "timestamp": "2025-01-01T00:00:00Z"},
    }

    model = parse_message(msg)
    assert model is not None
    assert isinstance(model, ForwardedIntentMessage)
    assert model.type == "forwardedIntent"
    assert model.payload.intent == "TestIntent"


def test_invalid_message_raises():
    msg = {"type": "broadcastEvent", "payload": {"bad": object()}, "meta": {}}
    with pytest.raises(ValidationError):
        parse_message(msg)


@pytest.mark.parametrize(
    "message_type",
    sorted(MESSAGE_TYPE_MAP.keys()),
)
def test_parse_each_registered_type(message_type):
    """Parametrized test that parses an explicit example for each registered type.

    Uses fixtures for the common meta envelopes and a per-type explicit
    example mapping to exercise `parse_message` individually.
    """

    def build_example(t: str, req_meta, resp_meta, evt_meta):
        examples = {
            "heartbeatAcknowledgmentRequest": {
                "payload": {"heartbeatEventUuid": "e1"},
                "meta": req_meta,
            },
            "open": {"payload": {"app": {"appId": "a1"}}, "meta": req_meta},
            "broadcast": {
                "payload": {"context": {"type": "test", "value": 1}},
                "meta": req_meta,
            },
            "broadcastEvent": {
                "payload": {"context": {"type": "test", "value": 1}},
                "meta": evt_meta,
            },
            "addContextListener": {
                "payload": {"contextType": "test"},
                "meta": req_meta,
            },
            "addContextListenerResponse": {
                "payload": {"listenerUuid": "l1"},
                "meta": resp_meta,
            },
            "contextListenerUnsubscribe": {
                "payload": {"listenerUuid": "l1"},
                "meta": req_meta,
            },
            "contextListenerUnsubscribeResponse": {
                "payload": {},
                "meta": resp_meta,
            },
            "addEventListener": {
                "payload": {"eventType": "test"},
                "meta": req_meta,
            },
            "addEventListenerResponse": {
                "payload": {"listenerUuid": "l1"},
                "meta": resp_meta,
            },
            "removeEventListener": {
                "payload": {"listenerUuid": "l1"},
                "meta": req_meta,
            },
            "removeEventListenerResponse": {"payload": {}, "meta": resp_meta},
            "privateChannelEvent": {
                "payload": {
                    "channelId": "c1",
                    "eventType": "onDisconnect",
                    "details": {},
                },
                "meta": evt_meta,
            },
            "forwardedIntent": {
                "payload": {
                    "requestUuid": "r1",
                    "request_uuid": "r1",
                    "intent": "I1",
                    "context": {"type": "test"},
                    "source": {"appId": "a1"},
                },
                "meta": req_meta,
            },
            "getUserChannels": {"payload": {}, "meta": req_meta},
            "getUserChannelsResponse": {
                "payload": {"channels": [{"id": "c1", "type": "user"}]},
                "meta": resp_meta,
            },
            "getSystemChannels": {"payload": {}, "meta": req_meta},
            "getSystemChannelsResponse": {
                "payload": {"channels": [{"id": "c1", "type": "user"}]},
                "meta": resp_meta,
            },
            "getCurrentChannel": {"payload": {}, "meta": req_meta},
            "getCurrentChannelResponse": {
                "payload": {"channel": {"id": "c1", "type": "user"}},
                "meta": resp_meta,
            },
            "getCurrentContext": {
                "payload": {"contextType": None},
                "meta": req_meta,
            },
            "getCurrentContextResponse": {
                "payload": {"context": {"type": "test"}},
                "meta": resp_meta,
            },
            "joinUserChannel": {"payload": {"channelId": "c1"}, "meta": req_meta},
            "joinUserChannelResponse": {
                "payload": {"channel": {"id": "c1", "type": "user"}},
                "meta": resp_meta,
            },
            "joinChannel": {"payload": {"channelId": "c1"}, "meta": req_meta},
            "joinChannelResponse": {
                "payload": {"channel": {"id": "c1", "type": "user"}},
                "meta": resp_meta,
            },
            "leaveCurrentChannel": {"payload": {}, "meta": req_meta},
            "leaveCurrentChannelResponse": {"payload": {}, "meta": resp_meta},
            "createPrivateChannel": {
                "payload": {"displayMetadata": {}},
                "meta": req_meta,
            },
            "createPrivateChannelResponse": {
                "payload": {"channel": {"id": "p1", "type": "private"}},
                "meta": req_meta,
            },
            "createPrivateChannelInvitation": {
                "payload": {"channelId": "p1"},
                "meta": req_meta,
            },
            "createPrivateChannelInvitationResponse": {
                "payload": {"invitationToken": "tok1"},
                "meta": req_meta,
            },
            "joinPrivateChannel": {
                "payload": {"channelId": "p1", "invitationToken": "tok1"},
                "meta": req_meta,
            },
            "joinPrivateChannelResponse": {
                "payload": {"channel": {"id": "p1", "type": "private"}},
                "meta": req_meta,
            },
            "leavePrivateChannel": {
                "payload": {"channelId": "p1"},
                "meta": req_meta,
            },
            "leavePrivateChannelResponse": {"payload": {}, "meta": req_meta},
            "privateChannelAddEventListener": {
                "payload": {"channelId": "p1"},
                "meta": req_meta,
            },
            "privateChannelAddEventListenerResponse": {
                "payload": {"listenerUuid": "l1"},
                "meta": resp_meta,
            },
            "privateChannelDisconnect": {
                "payload": {"channelId": "p1"},
                "meta": req_meta,
            },
            "privateChannelDisconnectResponse": {"payload": {}, "meta": resp_meta},
            "getInfo": {"payload": {}, "meta": req_meta},
            "getInfoResponse": {
                "payload": {
                    "implementationMetadata": {
                        "fdc3Version": "1.2",
                        "provider": "p",
                        "optionalFeatures": {},
                        "appMetadata": {"appId": "a1"},
                    }
                },
                "meta": resp_meta,
            },
            "getAppMetadata": {
                "payload": {"app": {"appId": "a1"}},
                "meta": req_meta,
            },
            "getAppMetadataResponse": {
                "payload": {"appMetadata": {"appId": "a1"}},
                "meta": resp_meta,
            },
            "addIntentListener": {"payload": {"intent": "I1"}, "meta": req_meta},
            "addIntentListenerResponse": {
                "payload": {"listenerUuid": "l1"},
                "meta": resp_meta,
            },
            "intentListenerUnsubscribe": {
                "payload": {"listenerUuid": "l1"},
                "meta": req_meta,
            },
            "intentListenerUnsubscribeResponse": {"payload": {}, "meta": resp_meta},
            "findIntent": {"payload": {"intent": "I1"}, "meta": req_meta},
            "findIntentResponse": {
                "payload": {
                    "appIntent": {
                        "intent": {"name": "I1"},
                        "apps": [{"appId": "a1"}],
                    }
                },
                "meta": resp_meta,
            },
            "findIntentsByContext": {
                "payload": {"context": {"type": "test"}},
                "meta": req_meta,
            },
            "findIntentsByContextResponse": {
                "payload": {
                    "appIntents": [
                        {"intent": {"name": "I1"}, "apps": [{"appId": "a1"}]}
                    ]
                },
                "meta": resp_meta,
            },
            "findInstances": {
                "payload": {"app": {"appId": "a1"}},
                "meta": req_meta,
            },
            "findInstancesResponse": {
                "payload": {"instances": [{"appId": "a1"}]},
                "meta": resp_meta,
            },
            "raiseIntent": {
                "payload": {"intent": "I1", "context": {"type": "test"}},
                "meta": req_meta,
            },
            "raiseIntentResponse": {
                "payload": {
                    "intentResolution": {"source": {"appId": "a1"}, "intent": "I1"}
                },
                "meta": resp_meta,
            },
            "raiseIntentForContext": {
                "payload": {"context": {"type": "test"}},
                "meta": req_meta,
            },
            "raiseIntentForContextResponse": {
                "payload": {
                    "intentResolution": {"source": {"appId": "a1"}, "intent": "I1"}
                },
                "meta": resp_meta,
            },
            "intentEvent": {
                "payload": {"intent": "I1", "context": {"type": "test"}},
                "meta": evt_meta,
            },
            "intentResultRequest": {
                "payload": {"intentResult": {}},
                "meta": req_meta,
            },
            "intentResult": {
                "payload": {"requestUuid": "r1", "request_uuid": "r1", "result": {}},
                "meta": req_meta,
            },
            "intentResultResponse": {"payload": {}, "meta": resp_meta},
            "raiseIntentResultResponse": {"payload": {}, "meta": resp_meta},
            "registerExternalHandler": {
                "payload": {
                    "handlerId": "h1",
                    "handler_id": "h1",
                    "intents": ["I1"],
                },
                "meta": req_meta,
            },
            "registerExternalHandlerResponse": {
                "payload": {"handlerUuid": "hu1", "handler_uuid": "hu1"},
                "meta": resp_meta,
            },
            "unregisterExternalHandler": {
                "payload": {"handlerUuid": "hu1", "handler_uuid": "hu1"},
                "meta": req_meta,
            },
        }

        return {"type": t, **examples.get(t, {"payload": {}, "meta": req_meta})}

    msg = build_example(
        message_type, base_meta_request, base_meta_response, base_meta_event
    )
    try:
        res = parse_message(msg)
    except Exception as exc:
        pytest.fail(
            f"parse_message raised unexpected exception for {message_type}: {exc}"
        )
    assert res is not None
