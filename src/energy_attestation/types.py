"""Public types for the Energy Attestation SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Optional, Sequence, Union


class Network(str, Enum):
    """Networks where the Energy Attestation Service is deployed."""

    POLYGON = "polygon"
    AMOY = "amoy"
    CELO = "celo"


class Interval(IntEnum):
    """Common reading interval presets, in minutes."""

    HOURLY = 60
    FOUR_HOURS = 240
    EIGHT_HOURS = 480
    TWELVE_HOURS = 720
    DAILY = 1440
    WEEKLY = 10080
    BIWEEKLY = 20160
    FOUR_WEEKS = 40320


class EnergyType(IntEnum):
    """Energy source of a project. 0 means the project is a consumer."""

    CONSUMER = 0
    SOLAR_PV = 1
    WIND_ONSHORE = 2
    WIND_OFFSHORE = 3
    HYDRO = 4
    BIOMASS = 5
    GEOTHERMAL = 6
    OCEAN_TIDAL = 7
    NUCLEAR = 8
    NATURAL_GAS = 9
    COAL = 10
    OIL = 11
    STORAGE_DISCHARGE = 12
    HYDROGEN_FUEL_CELL = 13


@dataclass
class TxFeeConfig:
    """Fee policy applied to every write transaction.

    min_priority_fee_gwei: tip floor. Celo validators often reject low tips.
    max_fee_multiplier: multiplier applied to the latest base fee.
    retry_count / retry_delay_s: retries for transport failures only, never for reverts.
    """

    min_priority_fee_gwei: float = 25
    max_fee_multiplier: int = 2
    retry_count: int = 0
    retry_delay_s: float = 1.0
    receipt_timeout_s: float = 180.0


@dataclass
class AttestParams:
    project_id: int
    readings: Sequence[int]
    """Energy per interval in watt hours (Wh), never kWh."""
    reading_interval_minutes: Union[int, Interval]
    from_timestamp: int
    method: str
    """How the data was collected: "iot", "manual", "estimated"."""
    metadata_uri: str = ""


@dataclass
class OverwriteAttestParams(AttestParams):
    ref_uid: str = ""


@dataclass
class ZeroPeriodParams:
    project_id: int
    interval: Union[int, Interval]
    method: Optional[str] = None
    metadata_uri: str = ""


@dataclass
class AttestationData:
    project_id: int
    reading_count: int
    reading_interval_minutes: int
    readings: List[int]
    from_timestamp: int
    method: str
    metadata_uri: str


@dataclass
class TxResult:
    tx_hash: str


@dataclass
class CreateWatcherResult:
    watcher_id: int
    name: str
    tx_hash: str


@dataclass
class CreateProjectResult:
    project_id: int
    name: str
    energy_type: int
    tx_hash: str


@dataclass
class AttestResult:
    uid: str
    tx_hash: str


@dataclass
class BatchAttestResult:
    uids: List[str]
    tx_hash: str


@dataclass
class Watcher:
    owner: str
    registered: bool
    name: str


@dataclass
class Project:
    watcher_id: int
    registered: bool
    energy_type: int
    name: str


@dataclass
class ProjectStats:
    project: Project
    total_generated: int
    total_consumed: int
    last_timestamp: int
    metadata_uri: str


@dataclass
class WatcherStats:
    watcher: Watcher
    total_generated: int
    total_consumed: int


@dataclass
class PageResult:
    items: list = field(default_factory=list)
    has_more: bool = False
