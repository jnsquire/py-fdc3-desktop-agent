from pydantic import BaseModel, Field, AnyUrl
from typing import Optional, Literal
from fdc3.models.primitives import ConnectionAttemptUuid, Timestamp


class WCP1HelloPayload(BaseModel):
    identityUrl: AnyUrl
    actualUrl: AnyUrl
    fdc3Version: str
    intentResolver: Optional[bool] = None
    channelSelector: Optional[bool] = None


class WCP1HelloMeta(BaseModel):
    connectionAttemptUuid: ConnectionAttemptUuid
    timestamp: Timestamp


class WCP1Hello(BaseModel):
    type: Literal["WCP1Hello"] = Field(default="WCP1Hello")
    payload: WCP1HelloPayload
    meta: WCP1HelloMeta


# Similarly for others, but placeholder for now


class WCP2LoadUrlPayload(BaseModel):
    iframeUrl: str


class WCP2LoadUrl(BaseModel):
    type: Literal["WCP2LoadUrl"] = Field(default="WCP2LoadUrl")
    payload: WCP2LoadUrlPayload
    meta: WCP1HelloMeta  # same meta


class WCP3HandshakePayload(BaseModel):
    fdc3Version: str
    intentResolverUrl: Optional[str] = None
    channelSelectorUrl: Optional[str] = None


class WCP3Handshake(BaseModel):
    type: Literal["WCP3Handshake"] = Field(default="WCP3Handshake")
    payload: WCP3HandshakePayload
    meta: WCP1HelloMeta


class WCP4ValidateAppIdentityPayload(BaseModel):
    instanceId: Optional[str] = None
    instanceUuid: Optional[str] = None
    # For self-registering external handlers (e.g., "external-handler:my-handler")
    appId: Optional[str] = None


class WCP4ValidateAppIdentity(BaseModel):
    type: Literal["WCP4ValidateAppIdentity"] = Field(default="WCP4ValidateAppIdentity")
    payload: WCP4ValidateAppIdentityPayload
    meta: WCP1HelloMeta


class WCP5ValidateAppIdentityResponsePayload(BaseModel):
    appId: str
    instanceId: str
    instanceUuid: str
    implementationMetadata: dict  # placeholder


class WCP5ValidateAppIdentityResponse(BaseModel):
    type: Literal["WCP5ValidateAppIdentityResponse"] = Field(
        default="WCP5ValidateAppIdentityResponse"
    )
    payload: WCP5ValidateAppIdentityResponsePayload
    meta: dict  # response meta


class WCP5ValidateAppIdentityFailedResponsePayload(BaseModel):
    message: str


class WCP5ValidateAppIdentityFailedResponse(BaseModel):
    type: Literal["WCP5ValidateAppIdentityFailedResponse"] = Field(
        default="WCP5ValidateAppIdentityFailedResponse"
    )
    payload: WCP5ValidateAppIdentityFailedResponsePayload
    meta: dict


class WCP6Goodbye(BaseModel):
    type: Literal["WCP6Goodbye"] = Field(default="WCP6Goodbye")
    payload: dict = Field(default_factory=dict)
    meta: WCP1HelloMeta
