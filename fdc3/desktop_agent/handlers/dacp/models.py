"""
Pydantic helper models for DACP message validation.
"""

from pydantic import BaseModel, Field, field_validator


class GetAppMetadataApp(BaseModel):
    appId: str = Field(..., min_length=1)

    @field_validator("appId")
    @classmethod
    def _normalize_app_id(cls, value: str) -> str:
        if "@" in value:
            base, _ = value.split("@", 1)
            return base or value
        return value


class GetAppMetadataPayload(BaseModel):
    app: GetAppMetadataApp


class FindIntentTarget(BaseModel):
    appId: str = Field(..., min_length=1)
    instanceId: str | None = None

    @field_validator("appId")
    @classmethod
    def _normalize_app_id(cls, value: str) -> str:
        if "@" in value:
            base, _ = value.split("@", 1)
            return base or value
        return value


class FindIntentPayload(BaseModel):
    intent: str = Field(..., min_length=1)
    resultType: str | None = None
    target: FindIntentTarget | None = None


class FindInstancesApp(BaseModel):
    appId: str | None = None
    instanceId: str | None = None

    @field_validator("appId")
    @classmethod
    def _normalize_app_id(cls, value: str | None) -> str | None:
        if not value:
            return None
        if "@" in value:
            base, _ = value.split("@", 1)
            return base or value
        return value


class FindInstancesPayload(BaseModel):
    app: FindInstancesApp | None = None
