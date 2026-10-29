"""Offline tests: encoding, validation and error decoding."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from eth_utils import keccak

from energy_attestation import (
    AttestParams,
    ConfigurationError,
    ContractRevertError,
    compute_to_timestamp,
    decode_attestation_data,
    encode_attestation_data,
    sum_readings,
)
from energy_attestation.errors import decode_contract_error, decode_revert_data
from energy_attestation.modules import validate_params

CASES = [
    AttestParams(1, [1500, 1800, 2100, 1900], 60, 1_700_000_000, "iot", "ipfs://Qm"),
    AttestParams(42, [0], 1440, 1_761_609_600, "0 report", ""),
    AttestParams(2**64 - 1, [2**256 - 1, 7], 2**32 - 1, 1, "manual", "https://example.com/évidence"),
]


def test_round_trip():
    for c in CASES:
        d = decode_attestation_data(encode_attestation_data(c))
        assert (d.project_id, d.readings, d.reading_interval_minutes, d.from_timestamp, d.method, d.metadata_uri) == (
            c.project_id, list(c.readings), c.reading_interval_minutes, c.from_timestamp, c.method, c.metadata_uri
        )
        assert d.reading_count == len(c.readings)


ETHERS = os.environ.get("ETHERS_DIR")  # a node_modules dir that contains ethers v6


@pytest.mark.skipif(not ETHERS, reason="set ETHERS_DIR to compare byte for byte with the JS SDK encoding")
def test_matches_js_sdk_encoding():
    js = f"""
const {{ AbiCoder }} = require({json.dumps(os.path.join(ETHERS, 'ethers'))});
const T = ["uint64","uint32","uint32","uint256[]","uint64","string","string"];
const cases = JSON.parse(process.argv[1]);
console.log(JSON.stringify(cases.map(c => AbiCoder.defaultAbiCoder().encode(T,
  [c.p, c.r.length, c.i, c.r.map(BigInt), c.f, c.m, c.u]))));
"""
    payload = json.dumps(
        [{"p": str(c.project_id), "r": [str(r) for r in c.readings], "i": c.reading_interval_minutes, "f": str(c.from_timestamp), "m": c.method, "u": c.metadata_uri} for c in CASES]
    )
    out = json.loads(subprocess.check_output(["node", "-e", js, payload], text=True))
    for c, hex_js in zip(CASES, out):
        assert "0x" + encode_attestation_data(c).hex() == hex_js


def test_helpers():
    assert compute_to_timestamp(1_700_000_000, 24, 60) == 1_700_086_400
    assert sum_readings([1500, 1800, 2100, 1900]) == 7300


@pytest.mark.parametrize(
    "params,msg",
    [
        (AttestParams(0, [1], 60, 1, "iot"), "project_id"),
        (AttestParams(1, [], 60, 1, "iot"), "empty"),
        (AttestParams(1, [-5], 60, 1, "iot"), "negative"),
        (AttestParams(1, [1.5], 60, 1, "iot"), "integer"),
        (AttestParams(1, [1], 0, 1, "iot"), "reading_interval"),
        (AttestParams(1, [1], 60, 0, "iot"), "from_timestamp"),
        (AttestParams(1, [1], 60, 1, "  "), "method"),
        (AttestParams(1, [1], 60, 2**64 - 10, "iot"), "uint64"),
    ],
)
def test_validation(params, msg):
    with pytest.raises(ConfigurationError, match=msg):
        validate_params(params)


def test_decode_custom_errors():
    sel = keccak(text="NonSequentialAttestation(uint64,uint64,uint64)")[:4]
    data = "0x" + (sel + (5).to_bytes(32, "big") + (100).to_bytes(32, "big") + (200).to_bytes(32, "big")).hex()
    e = decode_revert_data(data)
    assert e.error_name == "NonSequentialAttestation" and e.source == "registry"
    assert e.error_args == {"projectId": "5", "expectedFrom": "100", "actualFrom": "200"}

    sel = keccak(text="UnauthorizedAttester(address)")[:4]
    e = decode_revert_data("0x" + (sel + b"\x00" * 12 + b"\x11" * 20).hex())
    assert e.error_name == "UnauthorizedAttester" and e.source == "resolver"

    assert decode_revert_data("0xdeadbeef").error_name == "UnknownError"


def test_decode_from_web3_shaped_exception():
    sel = keccak(text="DirectRevocationBlocked()")[:4]

    class FakeLogicError(Exception):
        def __init__(self):
            super().__init__("execution reverted")
            self.data = "0x" + sel.hex()

    err = decode_contract_error(FakeLogicError())
    assert isinstance(err, ContractRevertError) and err.error_name == "DirectRevocationBlocked"
