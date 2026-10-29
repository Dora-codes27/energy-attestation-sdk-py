"""Inverter bridge: read a real solar inverter and attest its output to attest.energy."""

from .runner import Bridge, BridgeState, TickResult
from .sources import (
    PRESETS,
    CounterSource,
    ManualSource,
    ModbusRtuTransport,
    ModbusTcpTransport,
    PowerIntegrationSource,
    Preset,
    RegisterSpec,
    SolarmanTransport,
    SourceError,
    build_source,
    build_transport,
)

__all__ = [
    "Bridge",
    "BridgeState",
    "TickResult",
    "PRESETS",
    "Preset",
    "RegisterSpec",
    "CounterSource",
    "PowerIntegrationSource",
    "ManualSource",
    "ModbusTcpTransport",
    "ModbusRtuTransport",
    "SolarmanTransport",
    "SourceError",
    "build_source",
    "build_transport",
]
