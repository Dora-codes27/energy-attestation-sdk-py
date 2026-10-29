"""EnergySDK: the entry point for writing and reading energy attestations."""

from __future__ import annotations

import re
from typing import Optional

from eth_account import Account
from web3 import HTTPProvider, Web3

from ._abi import EAS_ABI, ENERGY_REGISTRY_ABI
from ._tx import SDKContext
from .errors import ConfigurationError
from .modules import (
    AttestationModule,
    AttesterModule,
    EnergyTypeModule,
    ProjectModule,
    ReadModule,
    WatcherModule,
)
from .networks import get_network_config
from .types import Network, TxFeeConfig

_BYTES32 = re.compile(r"^0x[0-9a-fA-F]{64}$")


class EnergySDK:
    """Synchronous SDK for the Energy Attestation Service (attest.energy).

    Built for scripts, backends and IoT devices such as a Raspberry Pi next to
    an inverter. Every write is signed locally with the given private key.
    """

    def __init__(
        self,
        w3: Web3,
        private_key: str,
        network: Network | str,
        *,
        registry_address: Optional[str] = None,
        schema_uid: Optional[str] = None,
        eas_address: Optional[str] = None,
        tx: Optional[TxFeeConfig] = None,
        chain_id: Optional[int] = None,
        check_chain: bool = True,
    ):
        if not private_key:
            raise ConfigurationError("private_key is required")
        self.network = Network(network)
        cfg = get_network_config(self.network)

        registry_address = registry_address or cfg.registry
        if not registry_address:
            raise ConfigurationError(f"Energy Attestation Service is not deployed on {self.network.value}; pass registry_address")
        if not Web3.is_address(registry_address):
            raise ConfigurationError("registry_address must be a valid Ethereum address")
        schema_uid = schema_uid or cfg.schema_uid
        if not schema_uid or not _BYTES32.match(schema_uid):
            raise ConfigurationError("schema_uid must be a valid bytes32 hex string (0x + 64 hex chars)")
        eas_address = eas_address or cfg.eas
        if not eas_address or not Web3.is_address(eas_address):
            raise ConfigurationError("eas_address must be a valid Ethereum address")

        tx = tx or TxFeeConfig()
        if tx.max_fee_multiplier < 1:
            raise ConfigurationError("tx.max_fee_multiplier must be >= 1")
        if tx.min_priority_fee_gwei < 0:
            raise ConfigurationError("tx.min_priority_fee_gwei must be >= 0")

        expected_chain = chain_id or cfg.chain_id
        if check_chain:
            try:
                actual = int(w3.eth.chain_id)
            except Exception as e:  # noqa: BLE001  transport errors are tolerated, like the JS SDK
                actual = None
                self._chain_warning = str(e)
            if actual is not None and actual != expected_chain:
                raise ConfigurationError(
                    f'RPC endpoint returned chain ID {actual}, expected {expected_chain} for network "{self.network.value}". '
                    "Check that your rpc_url points to the correct network."
                )

        self.w3 = w3
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        ctx = SDKContext(
            w3=w3,
            account=self.account,
            registry=w3.eth.contract(address=Web3.to_checksum_address(registry_address), abi=ENERGY_REGISTRY_ABI),
            eas=w3.eth.contract(address=Web3.to_checksum_address(eas_address), abi=EAS_ABI),
            schema_uid=bytes.fromhex(schema_uid[2:]),
            tx=tx,
            gas_strategy=cfg.gas_strategy,
            chain_id=expected_chain,
        )
        self.watchers = WatcherModule(ctx)
        self.projects = ProjectModule(ctx)
        self.attesters = AttesterModule(ctx)
        self.attestations = AttestationModule(ctx)
        self.energy_types = EnergyTypeModule(ctx)
        self.read = ReadModule(ctx)

    @classmethod
    def from_private_key(
        cls,
        private_key: str,
        network: Network | str,
        rpc_url: Optional[str] = None,
        **kwargs,
    ) -> "EnergySDK":
        """Create an SDK that signs with a local private key.

        rpc_url defaults to the network's public endpoint. Use your own
        (Alchemy, Infura, QuickNode) in production to avoid rate limits.
        """
        cfg = get_network_config(Network(network))
        w3 = Web3(HTTPProvider(rpc_url or cfg.default_rpc_url, request_kwargs={"timeout": 30}))
        # Polygon and Celo blocks have long extraData; let web3 read them anywhere it needs a block.
        from web3.middleware import ExtraDataToPOAMiddleware

        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return cls(w3, private_key, network, **kwargs)

    def assert_signer_address(self, expected: str) -> None:
        if not Web3.is_address(expected):
            raise ConfigurationError("expected must be a valid Ethereum address")
        if self.address.lower() != expected.lower():
            raise ConfigurationError(f"Signer address mismatch: {self.address} != {expected}")
