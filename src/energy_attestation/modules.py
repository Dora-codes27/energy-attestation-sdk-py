"""SDK modules. Same surface as the JS SDK, in snake_case."""

from __future__ import annotations

from typing import List, Sequence, Union

from web3 import Web3

from ._tx import SDKContext, call, estimate_gas, find_events, send_tx, tx_hash_hex
from .encoding import compute_to_timestamp, decode_attestation_data, encode_attestation_data
from .errors import ConfigurationError, decode_contract_error
from .types import (
    AttestationData,
    AttestParams,
    AttestResult,
    BatchAttestResult,
    CreateProjectResult,
    CreateWatcherResult,
    OverwriteAttestParams,
    Project,
    ProjectStats,
    TxResult,
    Watcher,
    WatcherStats,
    ZeroPeriodParams,
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_HASH = b"\x00" * 32
UINT64_MAX = (1 << 64) - 1
DEFAULT_ZERO_PERIOD_METHOD = "0 report"

IntLike = Union[int, str]


def _addr(address: str, label: str) -> str:
    if not isinstance(address, str) or not Web3.is_address(address):
        raise ConfigurationError(f"{label} must be a valid Ethereum address")
    return Web3.to_checksum_address(address)


def _bytes32(uid: Union[str, bytes], label: str = "uid") -> bytes:
    if isinstance(uid, (bytes, bytearray)):
        b = bytes(uid)
    elif isinstance(uid, str) and uid.startswith("0x") and len(uid) == 66:
        b = bytes.fromhex(uid[2:])
    else:
        raise ConfigurationError(f"{label} must be a bytes32 hex string (0x + 64 hex chars)")
    if len(b) != 32:
        raise ConfigurationError(f"{label} must be 32 bytes")
    return b


def _hex(b) -> str:
    h = b.hex() if isinstance(b, (bytes, bytearray)) else str(b)
    return h if h.startswith("0x") else "0x" + h


# ---------------------------------------------------------------------------
# Watchers
# ---------------------------------------------------------------------------


class WatcherModule:
    def __init__(self, ctx: SDKContext):
        self._ctx = ctx

    def create_watcher(self, name: str) -> CreateWatcherResult:
        receipt = send_tx(self._ctx, self._ctx.registry.functions.registerWatcher(name))
        events = find_events(receipt, self._ctx.registry, "WatcherRegistered")
        if not events:
            raise ConfigurationError(
                f"WatcherRegistered event not found (tx: {tx_hash_hex(receipt)}); watcher ID unknown"
            )
        return CreateWatcherResult(int(events[0]["args"]["watcherId"]), name, tx_hash_hex(receipt))

    def transfer_watcher_ownership(self, watcher_id: int, new_owner: str) -> TxResult:
        new_owner = _addr(new_owner, "new_owner")
        r = send_tx(self._ctx, self._ctx.registry.functions.transferWatcherOwnership(int(watcher_id), new_owner))
        return TxResult(tx_hash_hex(r))

    def estimate_create_watcher_gas(self, name: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.registerWatcher(name))

    def estimate_transfer_watcher_ownership_gas(self, watcher_id: int, new_owner: str) -> int:
        new_owner = _addr(new_owner, "new_owner")
        return estimate_gas(self._ctx, self._ctx.registry.functions.transferWatcherOwnership(int(watcher_id), new_owner))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class ProjectModule:
    def __init__(self, ctx: SDKContext):
        self._ctx = ctx

    def create_project(self, watcher_id: int, name: str, energy_type: int) -> CreateProjectResult:
        energy_type = int(energy_type)
        if energy_type != 0 and not call(self._ctx.registry.functions.isEnergyTypeRegistered(energy_type)):
            raise ConfigurationError(f"Energy type {energy_type} is not registered")
        receipt = send_tx(
            self._ctx, self._ctx.registry.functions.registerProject(int(watcher_id), name, energy_type)
        )
        events = find_events(receipt, self._ctx.registry, "ProjectRegistered")
        if not events:
            raise ConfigurationError(
                f"ProjectRegistered event not found (tx: {tx_hash_hex(receipt)}); project ID unknown"
            )
        return CreateProjectResult(int(events[0]["args"]["projectId"]), name, energy_type, tx_hash_hex(receipt))

    def deregister_project(self, project_id: int) -> TxResult:
        return TxResult(tx_hash_hex(send_tx(self._ctx, self._ctx.registry.functions.deregisterProject(int(project_id)))))

    def transfer_project(self, project_id: int, to_watcher_id: int) -> TxResult:
        fn = self._ctx.registry.functions.transferProject(int(project_id), int(to_watcher_id))
        return TxResult(tx_hash_hex(send_tx(self._ctx, fn)))

    def set_project_metadata_uri(self, project_id: int, uri: str) -> TxResult:
        fn = self._ctx.registry.functions.setProjectMetadataURI(int(project_id), uri)
        return TxResult(tx_hash_hex(send_tx(self._ctx, fn)))

    def estimate_create_project_gas(self, watcher_id: int, name: str, energy_type: int) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.registerProject(int(watcher_id), name, int(energy_type)))

    def estimate_deregister_project_gas(self, project_id: int) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.deregisterProject(int(project_id)))

    def estimate_transfer_project_gas(self, project_id: int, to_watcher_id: int) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.transferProject(int(project_id), int(to_watcher_id)))

    def estimate_set_project_metadata_uri_gas(self, project_id: int, uri: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.setProjectMetadataURI(int(project_id), uri))


# ---------------------------------------------------------------------------
# Attesters
# ---------------------------------------------------------------------------


class AttesterModule:
    def __init__(self, ctx: SDKContext):
        self._ctx = ctx

    def _send(self, fn) -> TxResult:
        return TxResult(tx_hash_hex(send_tx(self._ctx, fn)))

    def add_attester(self, project_id: int, attester: str) -> TxResult:
        return self._send(self._ctx.registry.functions.addAttester(int(project_id), _addr(attester, "attester")))

    def remove_attester(self, project_id: int, attester: str) -> TxResult:
        return self._send(self._ctx.registry.functions.removeAttester(int(project_id), _addr(attester, "attester")))

    def add_attesters(self, project_id: int, attesters: Sequence[str]) -> TxResult:
        addrs = [_addr(a, "attester") for a in attesters]
        return self._send(self._ctx.registry.functions.addAttesters(int(project_id), addrs))

    def remove_attesters(self, project_id: int, attesters: Sequence[str]) -> TxResult:
        addrs = [_addr(a, "attester") for a in attesters]
        return self._send(self._ctx.registry.functions.removeAttesters(int(project_id), addrs))

    def add_watcher_attester(self, watcher_id: int, attester: str) -> TxResult:
        return self._send(self._ctx.registry.functions.addWatcherAttester(int(watcher_id), _addr(attester, "attester")))

    def remove_watcher_attester(self, watcher_id: int, attester: str) -> TxResult:
        return self._send(self._ctx.registry.functions.removeWatcherAttester(int(watcher_id), _addr(attester, "attester")))

    def estimate_add_attester_gas(self, project_id: int, attester: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.addAttester(int(project_id), _addr(attester, "attester")))

    def estimate_remove_attester_gas(self, project_id: int, attester: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.removeAttester(int(project_id), _addr(attester, "attester")))

    def estimate_add_attesters_gas(self, project_id: int, attesters: Sequence[str]) -> int:
        addrs = [_addr(a, "attester") for a in attesters]
        return estimate_gas(self._ctx, self._ctx.registry.functions.addAttesters(int(project_id), addrs))

    def estimate_remove_attesters_gas(self, project_id: int, attesters: Sequence[str]) -> int:
        addrs = [_addr(a, "attester") for a in attesters]
        return estimate_gas(self._ctx, self._ctx.registry.functions.removeAttesters(int(project_id), addrs))

    def estimate_add_watcher_attester_gas(self, watcher_id: int, attester: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.addWatcherAttester(int(watcher_id), _addr(attester, "attester")))

    def estimate_remove_watcher_attester_gas(self, watcher_id: int, attester: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.removeWatcherAttester(int(watcher_id), _addr(attester, "attester")))


# ---------------------------------------------------------------------------
# Energy types (admin only)
# ---------------------------------------------------------------------------


class EnergyTypeModule:
    def __init__(self, ctx: SDKContext):
        self._ctx = ctx

    def register_energy_type(self, type_id: int, name: str) -> TxResult:
        if int(type_id) == 0:
            raise ConfigurationError("Energy type ID 0 is reserved for consumer projects and cannot be registered")
        return TxResult(tx_hash_hex(send_tx(self._ctx, self._ctx.registry.functions.registerEnergyType(int(type_id), name))))

    def remove_energy_type(self, type_id: int) -> TxResult:
        return TxResult(tx_hash_hex(send_tx(self._ctx, self._ctx.registry.functions.removeEnergyType(int(type_id)))))

    def transfer_energy_type_admin(self, new_admin: str) -> TxResult:
        fn = self._ctx.registry.functions.transferEnergyTypeAdmin(_addr(new_admin, "new_admin"))
        return TxResult(tx_hash_hex(send_tx(self._ctx, fn)))

    def estimate_register_energy_type_gas(self, type_id: int, name: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.registerEnergyType(int(type_id), name))

    def estimate_remove_energy_type_gas(self, type_id: int) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.removeEnergyType(int(type_id)))

    def estimate_transfer_energy_type_admin_gas(self, new_admin: str) -> int:
        return estimate_gas(self._ctx, self._ctx.registry.functions.transferEnergyTypeAdmin(_addr(new_admin, "new_admin")))


# ---------------------------------------------------------------------------
# Attestations
# ---------------------------------------------------------------------------


def validate_params(p: AttestParams) -> None:
    if int(p.project_id) <= 0:
        raise ConfigurationError("project_id must be a positive integer")
    readings = list(p.readings)
    if not readings:
        raise ConfigurationError("readings must not be empty")
    for i, r in enumerate(readings):
        if not isinstance(r, int) or isinstance(r, bool):
            raise ConfigurationError(f"readings[{i}] must be an integer number of Wh (got {r!r})")
        if r < 0:
            raise ConfigurationError(f"readings[{i}] is negative ({r}); energy values must be unsigned")
    if int(p.reading_interval_minutes) <= 0:
        raise ConfigurationError("reading_interval_minutes must be a positive integer")
    if int(p.from_timestamp) <= 0:
        raise ConfigurationError("from_timestamp must be a positive integer")
    if not p.method or not p.method.strip():
        raise ConfigurationError("method must not be empty")
    to_ts = compute_to_timestamp(p.from_timestamp, len(readings), p.reading_interval_minutes)
    if to_ts > UINT64_MAX:
        raise ConfigurationError(f"computed to_timestamp ({to_ts}) exceeds uint64 max")


class AttestationModule:
    def __init__(self, ctx: SDKContext):
        self._ctx = ctx

    def _request(self, params: AttestParams, ref_uid: bytes) -> tuple:
        return (
            ZERO_ADDRESS,  # recipient
            0,  # expirationTime
            True,  # revocable
            ref_uid,
            encode_attestation_data(params),
            0,  # value
        )

    def _submit(self, params: AttestParams, ref_uid: bytes) -> AttestResult:
        validate_params(params)
        fn = self._ctx.eas.functions.attest((self._ctx.schema_uid, self._request(params, ref_uid)))
        receipt = send_tx(self._ctx, fn)
        events = find_events(receipt, self._ctx.eas, "Attested")
        uid = _hex(events[0]["args"]["uid"]) if events else ""
        return AttestResult(uid, tx_hash_hex(receipt))

    def _estimate(self, params: AttestParams, ref_uid: bytes) -> int:
        validate_params(params)
        fn = self._ctx.eas.functions.attest((self._ctx.schema_uid, self._request(params, ref_uid)))
        return estimate_gas(self._ctx, fn)

    def attest(self, params: AttestParams) -> AttestResult:
        """Submit one energy attestation. The period must start at the project's chain tip."""
        return self._submit(params, ZERO_HASH)

    def _validate_overwrite(self, params: OverwriteAttestParams) -> bytes:
        if not params.ref_uid:
            raise ConfigurationError("ref_uid must be a non-zero bytes32 attestation UID")
        ref = _bytes32(params.ref_uid, "ref_uid")
        if ref == ZERO_HASH:
            raise ConfigurationError("ref_uid must be a non-zero bytes32 attestation UID")
        validate_params(params)
        original = call(self._ctx.eas.functions.getAttestation(ref))
        if not original or bytes(original[0]) == ZERO_HASH:
            raise ConfigurationError(f"attestation {_hex(ref)} does not exist")
        replacement = bytes(call(self._ctx.registry.functions.getReplacementUID(ref)))
        if replacement != ZERO_HASH:
            raise ConfigurationError(f"attestation {_hex(ref)} is already replaced; it cannot be overwritten again")
        orig = decode_attestation_data(bytes(original[9]))
        orig_to = compute_to_timestamp(orig.from_timestamp, orig.reading_count, orig.reading_interval_minutes)
        new_to = compute_to_timestamp(params.from_timestamp, len(list(params.readings)), params.reading_interval_minutes)
        if int(params.from_timestamp) != orig.from_timestamp:
            raise ConfigurationError(
                f"from_timestamp mismatch: replacement starts at {params.from_timestamp} "
                f"but original starts at {orig.from_timestamp}"
            )
        if new_to != orig_to:
            raise ConfigurationError(
                f"to_timestamp mismatch: replacement ends at {new_to} but original ends at {orig_to}; period must be identical"
            )
        return ref

    def overwrite_attestation(self, params: OverwriteAttestParams) -> AttestResult:
        """Replace an attestation with corrected readings, then revoke the original on EAS."""
        ref = self._validate_overwrite(params)
        result = self._submit(params, ref)
        send_tx(self._ctx, self._ctx.eas.functions.revoke((self._ctx.schema_uid, (ref, 0))))
        return result

    def attest_batch(self, params_list: Sequence[AttestParams]) -> BatchAttestResult:
        if not params_list:
            raise ConfigurationError("params_list must not be empty")
        for p in params_list:
            validate_params(p)
        data = [self._request(p, ZERO_HASH) for p in params_list]
        receipt = send_tx(self._ctx, self._ctx.eas.functions.multiAttest([(self._ctx.schema_uid, data)]))
        uids = [_hex(e["args"]["uid"]) for e in find_events(receipt, self._ctx.eas, "Attested")]
        return BatchAttestResult(uids, tx_hash_hex(receipt))

    def _zero_params(self, params: ZeroPeriodParams) -> AttestParams:
        if int(params.project_id) <= 0:
            raise ConfigurationError("project_id must be a positive integer")
        last = int(call(self._ctx.registry.functions.getProjectLastTimestamp(int(params.project_id))))
        if last <= 0:
            raise ConfigurationError("project has no prior attestation; use attest() with an explicit from_timestamp")
        return AttestParams(
            project_id=params.project_id,
            readings=[0],
            reading_interval_minutes=int(params.interval),
            from_timestamp=last,
            method=params.method or DEFAULT_ZERO_PERIOD_METHOD,
            metadata_uri=params.metadata_uri,
        )

    def attest_zero_period(self, params: ZeroPeriodParams) -> AttestResult:
        """Record a zero energy period (device offline) so the chain stays gapless."""
        return self._submit(self._zero_params(params), ZERO_HASH)

    def revoke_attestation(self, uid: str) -> TxResult:
        ref = _bytes32(uid)
        if ref == ZERO_HASH:
            raise ConfigurationError("uid must be a non-zero bytes32 attestation UID")
        r = send_tx(self._ctx, self._ctx.eas.functions.revoke((self._ctx.schema_uid, (ref, 0))))
        return TxResult(tx_hash_hex(r))

    def estimate_attest_gas(self, params: AttestParams) -> int:
        return self._estimate(params, ZERO_HASH)

    def estimate_overwrite_attestation_gas(self, params: OverwriteAttestParams) -> int:
        ref = self._validate_overwrite(params)
        attest_gas = self._estimate(params, ref)
        try:
            revoke_gas = estimate_gas(self._ctx, self._ctx.eas.functions.revoke((self._ctx.schema_uid, (ref, 0))))
        except Exception:  # noqa: BLE001  revoke is only valid after the replacement lands
            revoke_gas = 50_000
        return attest_gas + revoke_gas

    def estimate_attest_batch_gas(self, params_list: Sequence[AttestParams]) -> int:
        if not params_list:
            raise ConfigurationError("params_list must not be empty")
        for p in params_list:
            validate_params(p)
        data = [self._request(p, ZERO_HASH) for p in params_list]
        return estimate_gas(self._ctx, self._ctx.eas.functions.multiAttest([(self._ctx.schema_uid, data)]))

    def estimate_attest_zero_period_gas(self, params: ZeroPeriodParams) -> int:
        return self._estimate(self._zero_params(params), ZERO_HASH)

    def estimate_revoke_attestation_gas(self, uid: str) -> int:
        ref = _bytes32(uid)
        return estimate_gas(self._ctx, self._ctx.eas.functions.revoke((self._ctx.schema_uid, (ref, 0))))


# ---------------------------------------------------------------------------
# Reads (free view calls)
# ---------------------------------------------------------------------------


class ReadModule:
    def __init__(self, ctx: SDKContext):
        self._ctx = ctx

    def _c(self, name: str, *args):
        return call(getattr(self._ctx.registry.functions, name)(*args))

    def get_watcher(self, watcher_id: int) -> Watcher:
        w = self._c("getWatcher", int(watcher_id))
        # struct Watcher { address owner; bool registered; string name; }
        return Watcher(owner=w[0], registered=bool(w[1]), name=w[2])

    def get_project(self, project_id: int) -> Project:
        p = self._c("getProject", int(project_id))
        return Project(watcher_id=int(p[0]), registered=bool(p[1]), energy_type=int(p[2]), name=p[3])

    def is_project_registered(self, project_id: int) -> bool:
        return bool(self._c("isProjectRegistered", int(project_id)))

    def is_watcher_registered(self, watcher_id: int) -> bool:
        return bool(self._c("isWatcherRegistered", int(watcher_id)))

    def get_project_last_timestamp(self, project_id: int) -> int:
        return int(self._c("getProjectLastTimestamp", int(project_id)))

    def get_total_generated_energy(self, project_id: int) -> int:
        return int(self._c("getTotalGeneratedEnergy", int(project_id)))

    def get_total_consumed_energy(self, project_id: int) -> int:
        return int(self._c("getTotalConsumedEnergy", int(project_id)))

    def get_total_generated_energy_by_watcher(self, watcher_id: int) -> int:
        return int(self._c("getTotalGeneratedEnergyByWatcher", int(watcher_id)))

    def get_total_consumed_energy_by_watcher(self, watcher_id: int) -> int:
        return int(self._c("getTotalConsumedEnergyByWatcher", int(watcher_id)))

    def get_watcher_projects(self, watcher_id: int) -> List[int]:
        return [int(i) for i in self._c("getWatcherProjects", int(watcher_id))]

    def is_project_attester(self, project_id: int, attester: str) -> bool:
        return bool(self._c("isProjectAttester", int(project_id), _addr(attester, "attester")))

    def is_watcher_attester(self, watcher_id: int, attester: str) -> bool:
        return bool(self._c("isWatcherAttester", int(watcher_id), _addr(attester, "attester")))

    def get_project_metadata_uri(self, project_id: int) -> str:
        return self._c("getProjectMetadataURI", int(project_id))

    def get_project_energy_type(self, project_id: int) -> int:
        return int(self._c("getProjectEnergyType", int(project_id)))

    def get_replacement_uid(self, uid: str) -> str:
        return _hex(self._c("getReplacementUID", _bytes32(uid)))

    def get_attested_period_uid(self, project_id: int, from_ts: int, to_ts: int) -> str:
        return _hex(self._c("getAttestedPeriodUID", int(project_id), int(from_ts), int(to_ts)))

    def get_attested_period_start_uid(self, project_id: int, from_ts: int) -> str:
        return _hex(self._c("getAttestedPeriodStartUID", int(project_id), int(from_ts)))

    def get_next_project_id(self) -> int:
        return int(self._c("getNextProjectId"))

    def get_next_watcher_id(self) -> int:
        return int(self._c("getNextWatcherId"))

    def get_project_watcher_id(self, project_id: int) -> int:
        return int(self._c("getProjectWatcherId", int(project_id)))

    def get_project_type(self, project_id: int) -> int:
        return int(self._c("getProjectType", int(project_id)))

    def is_authorized_resolver(self, resolver: str) -> bool:
        return bool(self._c("isAuthorizedResolver", _addr(resolver, "resolver")))

    def is_energy_type_registered(self, type_id: int) -> bool:
        return bool(self._c("isEnergyTypeRegistered", int(type_id)))

    def get_energy_type_name(self, type_id: int) -> str:
        return self._c("getEnergyTypeName", int(type_id))

    def get_energy_type_admin(self) -> str:
        return self._c("getEnergyTypeAdmin")

    def get_watcher_projects_with_details(self, watcher_id: int) -> List[Project]:
        return [self.get_project(i) for i in self.get_watcher_projects(watcher_id)]

    def get_attestation_data(self, uid: str) -> AttestationData:
        a = call(self._ctx.eas.functions.getAttestation(_bytes32(uid)))
        return decode_attestation_data(bytes(a[9]))

    def get_owner(self) -> str:
        return self._c("owner")

    def get_pending_owner(self) -> str:
        return self._c("pendingOwner")

    def get_watcher_stats(self, watcher_id: int) -> WatcherStats:
        return WatcherStats(
            watcher=self.get_watcher(watcher_id),
            total_generated=self.get_total_generated_energy_by_watcher(watcher_id),
            total_consumed=self.get_total_consumed_energy_by_watcher(watcher_id),
        )

    def get_project_stats(self, project_id: int) -> ProjectStats:
        return ProjectStats(
            project=self.get_project(project_id),
            total_generated=self.get_total_generated_energy(project_id),
            total_consumed=self.get_total_consumed_energy(project_id),
            last_timestamp=self.get_project_last_timestamp(project_id),
            metadata_uri=self.get_project_metadata_uri(project_id),
        )


__all__ = [
    "WatcherModule",
    "ProjectModule",
    "AttesterModule",
    "EnergyTypeModule",
    "AttestationModule",
    "ReadModule",
    "validate_params",
    "decode_contract_error",
]
