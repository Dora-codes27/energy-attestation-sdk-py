"""Polygon and Celo return blocks with more than 32 bytes of extraData. The SDK must still price gas."""

from web3 import Web3
from web3.providers.base import BaseProvider

from energy_attestation._tx import SDKContext, fee_overrides
from energy_attestation.types import TxFeeConfig


class PolygonLikeProvider(BaseProvider):
    def make_request(self, method, params):
        assert method == "eth_getBlockByNumber"
        return {"jsonrpc": "2.0", "id": 1, "result": {"number": "0x1", "extraData": "0x" + "88" * 97, "baseFeePerGas": "0x77359400"}}


def test_fee_overrides_on_poa_chain():
    w3 = Web3(PolygonLikeProvider())
    ctx = SDKContext(w3, None, None, None, b"", TxFeeConfig(min_priority_fee_gwei=30, max_fee_multiplier=2), "eip1559", 80002)
    fees = fee_overrides(ctx)
    tip = 30 * 10**9
    assert fees == {"maxPriorityFeePerGas": tip, "maxFeePerGas": 2 * 2_000_000_000 + tip}
