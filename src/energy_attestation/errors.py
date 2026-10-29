"""Typed errors, with on chain custom errors decoded from both contract ABIs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from eth_abi import decode
from eth_utils import keccak

from ._abi import ENERGY_ATTESTATION_RESOLVER_ABI, ENERGY_REGISTRY_ABI


class ContractErrorCode:
    """Known revert names, for refactor proof matching (same set as the JS SDK)."""

    AttestationAlreadyReplaced = "AttestationAlreadyReplaced"
    AttestationNotFound = "AttestationNotFound"
    AttesterAlreadyAuthorized = "AttesterAlreadyAuthorized"
    AttesterNotAuthorized = "AttesterNotAuthorized"
    DirectRevocationBlocked = "DirectRevocationBlocked"
    EmptyAttesterArray = "EmptyAttesterArray"
    EnergyTypeNotRegistered = "EnergyTypeNotRegistered"
    InvalidEnergyType = "InvalidEnergyType"
    NonSequentialAttestation = "NonSequentialAttestation"
    InvalidInitialization = "InvalidInitialization"
    UUPSUnauthorizedCallContext = "UUPSUnauthorizedCallContext"
    ERC1967InvalidImplementation = "ERC1967InvalidImplementation"
    OwnableInvalidOwner = "OwnableInvalidOwner"
    OwnableUnauthorizedAccount = "OwnableUnauthorizedAccount"
    PeriodAlreadyAttested = "PeriodAlreadyAttested"
    PeriodStartAlreadyAttested = "PeriodStartAlreadyAttested"
    ProjectNotRegistered = "ProjectNotRegistered"
    ReplacementPeriodMismatch = "ReplacementPeriodMismatch"
    UnauthorizedEnergyTypeAdmin = "UnauthorizedEnergyTypeAdmin"
    UnauthorizedResolver = "UnauthorizedResolver"
    UnauthorizedWatcherOwner = "UnauthorizedWatcherOwner"
    WatcherNotRegistered = "WatcherNotRegistered"
    AccessDenied = "AccessDenied"
    EnforcedPause = "EnforcedPause"
    ExpectedPause = "ExpectedPause"
    InsufficientValue = "InsufficientValue"
    InvalidEAS = "InvalidEAS"
    InvalidLength = "InvalidLength"
    InvalidMethod = "InvalidMethod"
    InvalidReadingCount = "InvalidReadingCount"
    InvalidReadingInterval = "InvalidReadingInterval"
    InvalidReadingsLength = "InvalidReadingsLength"
    InvalidTimestamps = "InvalidTimestamps"
    NotPayable = "NotPayable"
    ReplacementProjectMismatch = "ReplacementProjectMismatch"
    TimestampOverflow = "TimestampOverflow"
    UnauthorizedAttester = "UnauthorizedAttester"


class EnergySDKError(Exception):
    pass


class ConfigurationError(EnergySDKError):
    """Bad config or bad parameters. Raised before any transaction is sent."""


class ContractRevertError(EnergySDKError):
    def __init__(self, error_name: str, error_args: Dict[str, Any], raw_data: str, source: str):
        self.error_name = error_name
        self.error_args = error_args
        self.raw_data = raw_data
        self.source = source  # "registry", "resolver" or "unknown"
        super().__init__(f"Contract reverted: {error_name} (source: {source})")


class TransactionError(EnergySDKError):
    def __init__(self, message: str, original_error: Optional[BaseException] = None):
        self.original_error = original_error
        super().__init__(message)


def _canonical_type(inp: dict) -> str:
    t = inp["type"]
    if t.startswith("tuple"):
        inner = ",".join(_canonical_type(c) for c in inp["components"])
        return f"({inner}){t[5:]}"
    return t


def _build_error_table(abi: list) -> Dict[bytes, dict]:
    table = {}
    for item in abi:
        if item.get("type") != "error":
            continue
        types = [_canonical_type(i) for i in item.get("inputs", [])]
        sig = f"{item['name']}({','.join(types)})"
        table[keccak(text=sig)[:4]] = {"name": item["name"], "inputs": item.get("inputs", []), "types": types}
    return table


_REGISTRY_ERRORS = _build_error_table(ENERGY_REGISTRY_ABI)
_RESOLVER_ERRORS = _build_error_table(ENERGY_ATTESTATION_RESOLVER_ABI)


def _to_jsonable(v: Any) -> Any:
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    return v


def decode_revert_data(data: str) -> ContractRevertError:
    raw = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    selector, payload = raw[:4], raw[4:]
    for table, source in ((_REGISTRY_ERRORS, "registry"), (_RESOLVER_ERRORS, "resolver")):
        entry = table.get(selector)
        if entry is None:
            continue
        try:
            values = decode(entry["types"], payload) if entry["types"] else ()
        except Exception:  # malformed payload, keep the name
            values = ()
        args = {
            (inp.get("name") or str(i)): _to_jsonable(val)
            for i, (inp, val) in enumerate(zip(entry["inputs"], values))
        }
        return ContractRevertError(entry["name"], args, "0x" + raw.hex(), source)
    return ContractRevertError("UnknownError", {}, "0x" + raw.hex(), "unknown")


def _extract_revert_data(error: BaseException) -> Optional[str]:
    """Pull hex revert data out of the many shapes web3 and RPC nodes use."""
    candidates = []
    data = getattr(error, "data", None)
    candidates.append(data)
    for arg in getattr(error, "args", ()):
        candidates.append(arg)
        if isinstance(arg, dict):
            candidates.append(arg.get("data"))
            inner = arg.get("error")
            if isinstance(inner, dict):
                candidates.append(inner.get("data"))
    for c in candidates:
        if isinstance(c, dict):
            c = c.get("data")
        if isinstance(c, str) and c.startswith("0x") and len(c) >= 10:
            return c
    return None


def decode_contract_error(error: BaseException):
    if isinstance(error, EnergySDKError):
        return error
    data = _extract_revert_data(error)
    if data:
        return decode_revert_data(data)
    return TransactionError(str(error) or "Transaction failed", error)
