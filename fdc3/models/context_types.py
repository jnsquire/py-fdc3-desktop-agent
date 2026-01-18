"""TypedDicts for common FDC3 context types.

These TypedDicts aim to mirror the common fields in the FDC3 context JSON
schemas (v2.x). They are not strict schema validators but provide structured
typing for examples and small apps. Fields are modeled to be permissive where
the FDC3 schema allows extensions.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ContextBase(TypedDict, total=False):
    """Base fields present on all FDC3 context types."""

    type: str
    name: Optional[str]
    id: Optional[Dict[str, str]]


class Instrument(ContextBase, total=False):
    """fdc3.instrument

    Example id keys: ticker, ISIN, CUSIP, FIGI
    """

    type: str  # 'fdc3.instrument'
    name: Optional[str]
    id: Optional[Dict[str, Optional[str]]]


class MessageText(TypedDict, total=False):
    """Representation for message text bodies keyed by mime-type.

    Use keys like 'text/plain' in practice; TypedDict keys in Python
    cannot contain slashes reliably, so examples may use variants.
    """

    text_plain: Optional[str]
    text_markdown: Optional[str]


class Message(ContextBase, total=False):
    """fdc3.message

    Minimal representation: a mapping of mime-type to text bodies and
    optional entities (attachments/actions).
    """

    type: str  # 'fdc3.message'
    text: Optional[Dict[str, str]]
    entities: Optional[Dict[str, Any]]


class ChatRoomId(TypedDict, total=False):
    streamId: Optional[str]
    channelId: Optional[str]


class ChatRoom(ContextBase, total=False):
    """fdc3.chat.room

    Provider-specific room identifier objects are permitted; keep common
    providerName and id fields.
    """

    type: str  # 'fdc3.chat.room'
    providerName: Optional[str]
    id: Optional[ChatRoomId]


class ChatMessage(ContextBase, total=False):
    """fdc3.chat.message

    Contains a `chatRoom` describing where the message belongs and a
    `message` payload which is an `fdc3.message` object.
    """

    type: str  # 'fdc3.chat.message'
    chatRoom: Optional[ChatRoom]
    message: Optional[Message]


class Chart(ContextBase, total=False):
    type: str  # 'fdc3.chart'
    instruments: Optional[List[Instrument]]
    range: Optional[Dict[str, Any]]
    style: Optional[str]


class Action(ContextBase, total=False):
    type: str  # 'fdc3.action'
    title: Optional[str]
    intent: Optional[str]
    context: Optional[Dict[str, Any]]


class Contact(ContextBase, total=False):
    type: str  # 'fdc3.contact'
    name: Optional[str]
    id: Optional[Dict[str, str]]


class Email(ContextBase, total=False):
    type: str  # 'fdc3.email'
    recipients: Optional[Dict[str, Any]]
    subject: Optional[str]
    textBody: Optional[str]


class ChatInitSettings(ContextBase, total=False):
    type: str  # 'fdc3.chat.initSettings'
    chatRoom: Optional[ChatRoom]
    prepopulatedMessage: Optional[Message]


# Convenience aliases for importers
ChatMessageContext = ChatMessage
MessageContext = Message
InstrumentContext = Instrument
ChartContext = Chart
ActionContext = Action
ChatRoomContext = ChatRoom
