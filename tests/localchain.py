"""Deploy EAS plus Suno's EnergyRegistry (UUPS proxy) and resolver to a local chain.

Mirrors deployFixture() in suno-finance/energy-attestation-service/test, so the
SDK is tested against the real contracts, not mocks.

Usage: python tests/localchain.py ARTIFACTS_JSON [RPC_URL] > deployment.json
"""

from __future__ import annotations

import json
import sys

from eth_account import Account
from web3 import HTTPProvider, Web3

from energy_attestation.encoding import ATTESTATION_SCHEMA

# Hardhat's well known dev keys. Never use these anywhere real.
DEV_KEYS = [
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
]


def _send(w3: Web3, acct, tx_fn_or_tx):
    tx = tx_fn_or_tx
    tx.setdefault("from", acct.address)
    tx["nonce"] = w3.eth.get_transaction_count(acct.address, "pending")
    tx["chainId"] = w3.eth.chain_id
    tx.setdefault("gas", 12_000_000)
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw))
    assert receipt["status"] == 1, receipt
    return receipt


def deploy(artifacts_path: str, rpc_url: str = "http://127.0.0.1:8545") -> dict:
    art = json.load(open(artifacts_path))
    w3 = Web3(HTTPProvider(rpc_url))
    owner = Account.from_key(DEV_KEYS[0])

    def deploy_one(name, *args):
        c = w3.eth.contract(abi=art[name]["abi"], bytecode=art[name]["bytecode"])
        r = _send(w3, owner, c.constructor(*args).build_transaction({"from": owner.address}))
        return w3.eth.contract(address=r["contractAddress"], abi=art[name]["abi"])

    schema_registry = deploy_one("SchemaRegistry")
    eas = deploy_one("EAS", schema_registry.address)
    impl = deploy_one("EnergyRegistry")
    init = impl.encode_abi("initialize", [owner.address])
    proxy = deploy_one("ERC1967Proxy", impl.address, init)
    registry = w3.eth.contract(address=proxy.address, abi=art["EnergyRegistry"]["abi"])
    resolver = deploy_one("EnergyAttestationResolver", eas.address, registry.address)
    _send(w3, owner, registry.functions.authorizeResolver(resolver.address).build_transaction({"from": owner.address}))
    schema_uid = schema_registry.functions.register(ATTESTATION_SCHEMA, resolver.address, True).call({"from": owner.address})
    _send(
        w3,
        owner,
        schema_registry.functions.register(ATTESTATION_SCHEMA, resolver.address, True).build_transaction({"from": owner.address}),
    )
    return {
        "rpc_url": rpc_url,
        "chain_id": w3.eth.chain_id,
        "eas": eas.address,
        "schema_registry": schema_registry.address,
        "registry": registry.address,
        "resolver": resolver.address,
        "schema_uid": "0x" + bytes(schema_uid).hex(),
        "keys": DEV_KEYS,
    }


if __name__ == "__main__":
    print(json.dumps(deploy(*sys.argv[1:]), indent=2))
