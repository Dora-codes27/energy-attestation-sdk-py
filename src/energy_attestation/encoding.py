"""ABI encoding of the energy attestation schema.

Schema: uint64 projectId, uint32 readingCount, uint32 readingIntervalMinutes,
        uint256[] readings, uint64 fromTimestamp, string method, string metadataURI
"""

from __future__ import annotations

from typing import Iterable, Union

from eth_abi import decode, encode

from .types import AttestationData, AttestParams

ATTESTATION_SCHEMA = (
    "uint64 projectId, uint32 readingCount, uint32 readingIntervalMinutes, "
    "uint256[] readings, uint64 fromTimestamp, string method, string metadataURI"
)

ATTESTATION_TYPES = ["uint64", "uint32", "uint32", "uint256[]", "uint64", "string", "string"]


def encode_attestation_data(params: AttestParams) -> bytes:
    readings = [int(r) for r in params.readings]
    return encode(
        ATTESTATION_TYPES,
        [
            int(params.project_id),
            len(readings),
            int(params.reading_interval_minutes),
            readings,
            int(params.from_timestamp),
            params.method,
            params.metadata_uri or "",
        ],
    )


def decode_attestation_data(data: Union[bytes, str]) -> AttestationData:
    if isinstance(data, str):
        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    pid, count, interval, readings, from_ts, method, uri = decode(ATTESTATION_TYPES, data)
    return AttestationData(
        project_id=int(pid),
        reading_count=int(count),
        reading_interval_minutes=int(interval),
        readings=[int(r) for r in readings],
        from_timestamp=int(from_ts),
        method=method,
        metadata_uri=uri,
    )


def compute_to_timestamp(from_timestamp: int, reading_count: int, reading_interval_minutes: int) -> int:
    return int(from_timestamp) + int(reading_count) * int(reading_interval_minutes) * 60


def sum_readings(readings: Iterable[int]) -> int:
    return sum(int(r) for r in readings)
