from pydantic import BaseModel, Field
from typing import Optional, List


class AppIdentifier(BaseModel):
    appId: str = Field(..., description="The unique application identifier")
    instanceId: Optional[str] = None
    desktopAgent: Optional[str] = None


class Icon(BaseModel):
    src: str
    size: Optional[str] = None
    type: Optional[str] = None


class Image(BaseModel):
    src: str
    size: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None


class AppMetadata(AppIdentifier):
    name: Optional[str] = None
    version: Optional[str] = None
    instanceMetadata: Optional[dict] = None
    title: Optional[str] = None
    tooltip: Optional[str] = None
    description: Optional[str] = None
    icons: Optional[List[Icon]] = None
    screenshots: Optional[List[Image]] = None
    resultType: Optional[str] = None


class IntentMetadata(BaseModel):
    name: str
    displayName: Optional[str] = None


class AppIntent(BaseModel):
    intent: IntentMetadata
    apps: List[AppMetadata]


class DisplayMetadata(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    glyph: Optional[str] = None


class Channel(BaseModel):
    id: str
    type: str  # "user", "app", "private"
    displayMetadata: Optional[DisplayMetadata] = None


class ContextMetadata(BaseModel):
    source: AppIdentifier


class DesktopAgentIdentifier(BaseModel):
    desktopAgent: str


class BaseImplementationMetadata(BaseModel):
    fdc3Version: str
    provider: str
    providerVersion: Optional[str] = None
    optionalFeatures: dict  # with specific keys


class ImplementationMetadata(BaseImplementationMetadata):
    appMetadata: AppMetadata


class IntentResolution(BaseModel):
    source: AppIdentifier
    intent: str


class IntentResult(BaseModel):
    # anyOf context, channel, or void
    pass  # placeholder


class FDC3EventType(str):
    USER_CHANNEL_CHANGED = "USER_CHANNEL_CHANGED"


class FDC3Event(BaseModel):
    type: FDC3EventType
    details: dict
