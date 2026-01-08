"""Shared FDC3 domain models.

These Pydantic models are used across the desktop agent and client code.
"""

from .identifiers import (  # noqa: F401
    AppIdentifier,
    AppMetadata,
    Channel,
    FDC3Event,
    FDC3EventType,
    ImplementationMetadata,
    IntentMetadata,
)

__all__ = [
    "AppIdentifier",
    "AppMetadata",
    "Channel",
    "FDC3Event",
    "FDC3EventType",
    "ImplementationMetadata",
    "IntentMetadata",
]
