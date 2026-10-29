"""Python SDK for the Energy Attestation Service (attest.energy).

Record energy generation and consumption on chain through the Ethereum
Attestation Service, from scripts, backends and IoT devices.
"""

from .encoding import (
    ATTESTATION_SCHEMA,
    compute_to_timestamp,
    decode_attestation_data,
    encode_attestation_data,
    sum_readings,
)
from .errors import (
    ConfigurationError,
    ContractErrorCode,
    ContractRevertError,
    EnergySDKError,
    TransactionError,
)
from .networks import CHAIN_IDS, NETWORK_CONFIG, get_network_config
from .query import EnergyQuery, SubgraphError
from .sdk import EnergySDK
from .types import (
    AttestationData,
    AttestParams,
    AttestResult,
    BatchAttestResult,
    CreateProjectResult,
    CreateWatcherResult,
    EnergyType,
    Interval,
    Network,
    OverwriteAttestParams,
    Project,
    ProjectStats,
    TxFeeConfig,
    TxResult,
    Watcher,
    WatcherStats,
    ZeroPeriodParams,
)

ENERGY_TYPE_NAMES = {t.value: t.name.lower() for t in EnergyType}

__version__ = "0.1.0"

__all__ = [
    "EnergySDK",
    "EnergyQuery",
    "Network",
    "Interval",
    "EnergyType",
    "TxFeeConfig",
    "AttestParams",
    "OverwriteAttestParams",
    "ZeroPeriodParams",
    "AttestationData",
    "AttestResult",
    "BatchAttestResult",
    "CreateWatcherResult",
    "CreateProjectResult",
    "TxResult",
    "Watcher",
    "Project",
    "WatcherStats",
    "ProjectStats",
    "EnergySDKError",
    "ConfigurationError",
    "ContractRevertError",
    "TransactionError",
    "SubgraphError",
    "ContractErrorCode",
    "ATTESTATION_SCHEMA",
    "ENERGY_TYPE_NAMES",
    "CHAIN_IDS",
    "NETWORK_CONFIG",
    "get_network_config",
    "encode_attestation_data",
    "decode_attestation_data",
    "compute_to_timestamp",
    "sum_readings",
]
