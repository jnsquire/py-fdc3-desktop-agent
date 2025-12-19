"""Desktop Agent Bridging (experimental).

This package implements a minimal Bridge Connection Protocol (BCP) and Bridge
Messaging Protocol (BMP) client so this Desktop Agent can interoperate with
other agents via a standalone Desktop Agent Bridge.
"""

from .client import BridgeClient

__all__ = ["BridgeClient"]
