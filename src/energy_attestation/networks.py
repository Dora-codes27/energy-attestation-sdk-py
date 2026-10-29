"""Built-in network configuration, kept identical to energy-attestation-sdk (JS) v1.2.0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .types import Network


@dataclass(frozen=True)
class NetworkConfig:
    eas: str
    schema_registry: str
    registry: Optional[str]
    schema_uid: Optional[str]
    default_rpc_url: str
    subgraph_url: Optional[str]
    chain_id: int
    gas_strategy: str  # "eip1559" or "legacy"


NETWORK_CONFIG: Dict[Network, NetworkConfig] = {
    Network.AMOY: NetworkConfig(
        eas="0xb101275a60d8bfb14529C421899aD7CA1Ae5B5Fc",
        schema_registry="0x23c5701A1BDa89C61d181BD79E5203c730708AE7",
        registry="0x059D4655941204cf6aaC1cF578Aa9dc5D3ed6B39",
        schema_uid="0x4673141c77c3d54962edf6ef7f25a0c62656f9bd08138b4c4f9561413c235435",
        default_rpc_url="https://polygon-amoy-bor-rpc.publicnode.com",
        subgraph_url="https://gateway.thegraph.com/api/subgraphs/id/33b8nJcqxLyH96eSyyHC9vsdvHifUXejLzMEtqLeySBC",
        chain_id=80002,
        gas_strategy="eip1559",
    ),
    Network.POLYGON: NetworkConfig(
        eas="0x5E634ef5355f45A855d02D66eCD687b1502AF790",
        schema_registry="0x7876EEF51A891E737AF8ba5A5E0f0Fd29073D5a7",
        registry="0xA5B5f895091d79d1f099531cDB8cb896F17ec4C1",
        schema_uid="0xb9c136082a935b39c6e276ea137ac489bdc090aac17a116347c7ea90442ef7e0",
        default_rpc_url="https://polygon-bor-rpc.publicnode.com",
        subgraph_url="https://gateway.thegraph.com/api/subgraphs/id/D8AgWoxUr3aDgWQCEy2hVeU8hnsrs5N3vmPSeGMphgEi",
        chain_id=137,
        gas_strategy="eip1559",
    ),
    Network.CELO: NetworkConfig(
        eas="0x72E1d8ccf5299fb36fEfD8CC4394B8ef7e98Af92",
        schema_registry="0x5ece93bE4BDCF293Ed61FA78698B594F2135AF34",
        registry="0xA5B5f895091d79d1f099531cDB8cb896F17ec4C1",
        schema_uid="0xb9c136082a935b39c6e276ea137ac489bdc090aac17a116347c7ea90442ef7e0",
        default_rpc_url="https://forno.celo.org",
        subgraph_url="https://gateway.thegraph.com/api/subgraphs/id/9BM6kQzg7jtcbnphW7UXCGMmvJ2QtDkxnU8fqDYinUx1",
        chain_id=42220,
        gas_strategy="eip1559",
    ),
}

CHAIN_IDS: Dict[Network, int] = {n: c.chain_id for n, c in NETWORK_CONFIG.items()}


def get_network_config(network: Network | str) -> NetworkConfig:
    return NETWORK_CONFIG[Network(network)]
