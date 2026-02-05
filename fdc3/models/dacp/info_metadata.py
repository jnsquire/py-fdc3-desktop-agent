"""DACP Info and Metadata Models."""

from pydantic import BaseModel, Field
from typing import Literal
from .envelopes import (
    DacpMessage,
    AppRequestMeta,
    AgentResponseMeta,
    register_message_type,
)
from fdc3.models.identifiers import AppIdentifier, AppMetadata, ImplementationMetadata


# getInfo
class GetInfoRequestPayload(BaseModel):
    pass


@register_message_type("getInfo")
class GetInfoRequest(DacpMessage):
    type: Literal["getInfo"]
    payload: GetInfoRequestPayload = Field(default_factory=GetInfoRequestPayload)
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetInfoResponsePayload(BaseModel):
    implementationMetadata: ImplementationMetadata


# `implementationMetadata` can include vendor-specific fields; parse via
# the generic `AgentResponse` envelope to accept implementation details.
class GetInfoResponse(BaseModel):
    type: Literal["getInfoResponse"]
    payload: GetInfoResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# getAppMetadata
class GetAppMetadataRequestPayload(BaseModel):
    app: AppIdentifier


@register_message_type("getAppMetadata")
class GetAppMetadataRequest(DacpMessage):
    type: Literal["getAppMetadata"]
    payload: GetAppMetadataRequestPayload
    meta: AppRequestMeta = Field(default_factory=AppRequestMeta)


class GetAppMetadataResponsePayload(BaseModel):
    appMetadata: AppMetadata


# `appMetadata` can come from external registries and vary by agent;
# parse via the generic `AgentResponse` envelope.
class GetAppMetadataResponse(BaseModel):
    type: Literal["getAppMetadataResponse"]
    payload: GetAppMetadataResponsePayload
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)
