"""Transaction plumbing: fee policy, signing, retries, receipts and log parsing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract import Contract

from .errors import EnergySDKError, TransactionError, decode_contract_error
from .types import TxFeeConfig


@dataclass
class SDKContext:
    w3: Web3
    account: LocalAccount
    registry: Contract
    eas: Contract
    schema_uid: bytes
    tx: TxFeeConfig
    gas_strategy: str
    chain_id: int


def fee_overrides(ctx: SDKContext) -> dict:
    multiplier = max(1, int(ctx.tx.max_fee_multiplier))
    if ctx.gas_strategy == "legacy":
        return {"gasPrice": int(ctx.w3.eth.gas_price) * multiplier}
    # Raw RPC on purpose: Polygon and Celo blocks carry more than 32 bytes of
    # extraData, which web3.py's get_block() rejects (ExtraDataLengthError).
    # The JS SDK reads the base fee the same way.
    resp = ctx.w3.provider.make_request("eth_getBlockByNumber", ["latest", False])
    block = (resp or {}).get("result") or {}
    base_fee = int(block.get("baseFeePerGas") or "0x0", 16)
    min_priority = int(Web3.to_wei(ctx.tx.min_priority_fee_gwei, "gwei"))
    return {"maxPriorityFeePerGas": min_priority, "maxFeePerGas": base_fee * multiplier + min_priority}


def _build_and_send(ctx: SDKContext, fn) -> Any:
    tx = fn.build_transaction(
        {
            "from": ctx.account.address,
            "nonce": ctx.w3.eth.get_transaction_count(ctx.account.address, "pending"),
            "chainId": ctx.chain_id,
            **fee_overrides(ctx),
        }
    )
    signed = ctx.account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = ctx.w3.eth.send_raw_transaction(raw)
    receipt = ctx.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=ctx.tx.receipt_timeout_s)
    if receipt["status"] != 1:
        # Replay the call at the failing block to surface the revert reason.
        try:
            ctx.w3.eth.call({k: tx[k] for k in ("from", "to", "data", "value") if k in tx}, receipt["blockNumber"])
        except Exception as e:  # noqa: BLE001
            raise decode_contract_error(e) from e
        raise TransactionError(f"Transaction reverted without data (tx: {tx_hash.hex()})")
    return receipt


def send_tx(ctx: SDKContext, fn) -> Any:
    """Send a contract call and wait for its receipt.

    Contract reverts are never retried (they are deterministic). Transport
    failures are retried ctx.tx.retry_count times with exponential backoff.
    """
    attempts = 1 + max(0, ctx.tx.retry_count)
    last: Optional[BaseException] = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(ctx.tx.retry_delay_s * 2 ** (attempt - 1))
        try:
            return _build_and_send(ctx, fn)
        except EnergySDKError:
            raise
        except Exception as e:  # noqa: BLE001
            decoded = decode_contract_error(e)
            if not isinstance(decoded, TransactionError):
                raise decoded from e
            last = e
    raise decode_contract_error(last) from last


def estimate_gas(ctx: SDKContext, fn) -> int:
    try:
        return int(fn.estimate_gas({"from": ctx.account.address}))
    except Exception as e:  # noqa: BLE001
        raise decode_contract_error(e) from e


def call(fn) -> Any:
    try:
        return fn.call()
    except Exception as e:  # noqa: BLE001
        raise decode_contract_error(e) from e


def find_events(receipt, contract: Contract, event_name: str) -> List[Any]:
    event = getattr(contract.events, event_name)()
    topic0 = Web3.keccak(text=_event_signature(event.abi)).hex()
    topic0 = topic0 if topic0.startswith("0x") else "0x" + topic0
    out = []
    for log in receipt["logs"]:
        if log["address"].lower() != contract.address.lower() or not log["topics"]:
            continue
        t0 = log["topics"][0]
        t0 = t0.hex() if isinstance(t0, (bytes, bytearray)) else t0
        t0 = t0 if t0.startswith("0x") else "0x" + t0
        if t0.lower() != topic0.lower():
            continue
        out.append(event.process_log(log))
    return out


def _event_signature(abi: dict) -> str:
    types = ",".join(i["type"] for i in abi["inputs"])
    return f"{abi['name']}({types})"


def tx_hash_hex(receipt) -> str:
    h = receipt["transactionHash"]
    h = h.hex() if isinstance(h, (bytes, bytearray)) else str(h)
    return h if h.startswith("0x") else "0x" + h


Caller = Callable[..., Any]
