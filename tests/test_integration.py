"""End to end tests against the real EnergyRegistry, resolver and EAS on a local chain.

Run a local node (npx hardhat node), deploy with tests/localchain.py, then:
    EAS_DEPLOYMENT=deployment.json pytest tests/test_integration.py
"""

from __future__ import annotations

import pytest
from web3 import HTTPProvider, Web3

from energy_attestation import (
    AttestParams,
    ConfigurationError,
    ContractErrorCode,
    ContractRevertError,
    EnergySDK,
    EnergyType,
    Interval,
    Network,
    OverwriteAttestParams,
    ZeroPeriodParams,
)
from conftest import DEPLOYMENT, make_sdk
pytestmark = pytest.mark.skipif(not DEPLOYMENT, reason="set EAS_DEPLOYMENT to a localchain deployment json")




@pytest.fixture(scope="session")
def admin(dep):
    return make_sdk(dep, 0)


@pytest.fixture(scope="session")
def owner(dep):
    return make_sdk(dep, 1)


@pytest.fixture(scope="session")
def device(dep):
    return make_sdk(dep, 2)


@pytest.fixture(scope="session")
def stranger(dep):
    return make_sdk(dep, 3)


@pytest.fixture()
def solar_project(owner, device):
    w = owner.watchers.create_watcher("Test Solar Co")
    p = owner.projects.create_project(w.watcher_id, "Rooftop 6kW", EnergyType.SOLAR_PV)
    owner.attesters.add_attester(p.project_id, device.address)
    return w.watcher_id, p.project_id


T0 = 1_761_609_600  # 2025-10-28T00:00:00Z, hour aligned


def test_wrong_chain_is_rejected(dep):
    w3 = Web3(HTTPProvider(dep["rpc_url"]))
    with pytest.raises(ConfigurationError, match="chain ID"):
        EnergySDK(w3, dep["keys"][0], Network.CELO, registry_address=dep["registry"], schema_uid=dep["schema_uid"], eas_address=dep["eas"])


def test_watcher_and_project_registration(owner, solar_project):
    watcher_id, project_id = solar_project
    w = owner.read.get_watcher(watcher_id)
    assert w.name == "Test Solar Co" and w.registered and w.owner == owner.address
    p = owner.read.get_project(project_id)
    assert p.name == "Rooftop 6kW" and p.energy_type == EnergyType.SOLAR_PV and p.watcher_id == watcher_id
    assert project_id in owner.read.get_watcher_projects(watcher_id)
    assert owner.read.get_project_type(project_id) == 0  # generator


def test_attest_and_read_back(owner, device, solar_project):
    _, project_id = solar_project
    assert device.read.is_project_attester(project_id, device.address)
    res = device.attestations.attest(
        AttestParams(project_id, [1500, 1800, 2100, 1900], Interval.HOURLY, T0, "iot", "ipfs://evidence")
    )
    assert res.uid.startswith("0x") and len(res.uid) == 66
    stats = device.read.get_project_stats(project_id)
    assert stats.total_generated == 7300
    assert stats.last_timestamp == T0 + 4 * 3600
    data = device.read.get_attestation_data(res.uid)
    assert data.readings == [1500, 1800, 2100, 1900] and data.method == "iot" and data.metadata_uri == "ipfs://evidence"
    assert device.read.get_attested_period_uid(project_id, T0, T0 + 4 * 3600) == res.uid


def test_gap_is_rejected_with_decoded_error(device, solar_project):
    _, project_id = solar_project
    device.attestations.attest(AttestParams(project_id, [100], Interval.HOURLY, T0, "iot"))
    with pytest.raises(ContractRevertError) as e:
        device.attestations.attest(AttestParams(project_id, [100], Interval.HOURLY, T0 + 7200, "iot"))
    assert e.value.error_name == ContractErrorCode.NonSequentialAttestation
    assert e.value.error_args["expectedFrom"] == str(T0 + 3600)


def test_unauthorized_attester(stranger, solar_project):
    _, project_id = solar_project
    with pytest.raises(ContractRevertError) as e:
        stranger.attestations.attest(AttestParams(project_id, [100], Interval.HOURLY, T0, "iot"))
    assert e.value.error_name == ContractErrorCode.UnauthorizedAttester


def test_estimate_surfaces_same_error(stranger, device, solar_project):
    _, project_id = solar_project
    assert device.attestations.estimate_attest_gas(AttestParams(project_id, [1], 60, T0, "iot")) > 50_000
    with pytest.raises(ContractRevertError) as e:
        stranger.attestations.estimate_attest_gas(AttestParams(project_id, [1], 60, T0, "iot"))
    assert e.value.error_name == ContractErrorCode.UnauthorizedAttester


def test_batch_zero_period_and_overwrite(device, solar_project):
    _, project_id = solar_project
    batch = device.attestations.attest_batch(
        [
            AttestParams(project_id, [1000, 1000], Interval.HOURLY, T0, "iot"),
            AttestParams(project_id, [500], Interval.HOURLY, T0 + 7200, "iot"),
        ]
    )
    assert len(batch.uids) == 2
    assert device.read.get_total_generated_energy(project_id) == 2500

    zero = device.attestations.attest_zero_period(ZeroPeriodParams(project_id, Interval.DAILY, method="downtime"))
    assert device.read.get_project_last_timestamp(project_id) == T0 + 3 * 3600 + 86400

    # Replace the daily zero with 24 real hourly readings.
    fixed = device.attestations.overwrite_attestation(
        OverwriteAttestParams(project_id, [100] * 24, Interval.HOURLY, T0 + 3 * 3600, "iot", ref_uid=zero.uid)
    )
    assert device.read.get_replacement_uid(zero.uid) == fixed.uid
    assert device.read.get_total_generated_energy(project_id) == 2500 + 2400

    with pytest.raises(ConfigurationError, match="already replaced"):
        device.attestations.overwrite_attestation(
            OverwriteAttestParams(project_id, [5] * 24, Interval.HOURLY, T0 + 3 * 3600, "iot", ref_uid=zero.uid)
        )
    with pytest.raises(ConfigurationError, match="mismatch"):
        device.attestations.overwrite_attestation(
            OverwriteAttestParams(project_id, [5] * 23, Interval.HOURLY, T0 + 3 * 3600, "iot", ref_uid=fixed.uid)
        )


def test_direct_revocation_is_blocked(device, solar_project):
    _, project_id = solar_project
    res = device.attestations.attest(AttestParams(project_id, [42], Interval.HOURLY, T0, "manual"))
    with pytest.raises(ContractRevertError) as e:
        device.attestations.revoke_attestation(res.uid)
    assert e.value.error_name == ContractErrorCode.DirectRevocationBlocked


def test_consumer_project_and_watcher_totals(owner, device):
    w = owner.watchers.create_watcher("Church Generator Room")
    gen = owner.projects.create_project(w.watcher_id, "Solar array", EnergyType.SOLAR_PV)
    load = owner.projects.create_project(w.watcher_id, "Sanctuary load", EnergyType.CONSUMER)
    owner.attesters.add_watcher_attester(w.watcher_id, device.address)
    device.attestations.attest(AttestParams(gen.project_id, [3000], 60, T0, "iot"))
    device.attestations.attest(AttestParams(load.project_id, [1200], 60, T0, "iot"))
    s = owner.read.get_watcher_stats(w.watcher_id)
    assert (s.total_generated, s.total_consumed) == (3000, 1200)
    owner.attesters.remove_watcher_attester(w.watcher_id, device.address)
    assert not owner.read.is_watcher_attester(w.watcher_id, device.address)


def test_metadata_transfer_and_deregister(owner, stranger, solar_project):
    watcher_id, project_id = solar_project
    owner.projects.set_project_metadata_uri(project_id, "ipfs://project-metadata")
    assert owner.read.get_project_metadata_uri(project_id) == "ipfs://project-metadata"

    other = owner.watchers.create_watcher("Second Site")
    owner.projects.transfer_project(project_id, other.watcher_id)
    assert owner.read.get_project_watcher_id(project_id) == other.watcher_id

    with pytest.raises(ContractRevertError) as e:
        stranger.projects.deregister_project(project_id)
    assert e.value.error_name == ContractErrorCode.UnauthorizedWatcherOwner

    owner.projects.deregister_project(project_id)
    assert not owner.read.is_project_registered(project_id)

    owner.watchers.transfer_watcher_ownership(other.watcher_id, stranger.address)
    assert owner.read.get_watcher(other.watcher_id).owner == stranger.address


def test_batch_attester_management(owner, stranger, device, solar_project):
    _, project_id = solar_project
    owner.attesters.add_attesters(project_id, [stranger.address])
    assert owner.read.is_project_attester(project_id, stranger.address)
    with pytest.raises(ContractRevertError) as e:
        owner.attesters.add_attester(project_id, stranger.address)
    assert e.value.error_name == ContractErrorCode.AttesterAlreadyAuthorized
    owner.attesters.remove_attesters(project_id, [stranger.address, device.address])
    assert not owner.read.is_project_attester(project_id, device.address)


def test_energy_type_admin(admin, owner):
    assert admin.read.get_energy_type_admin() == admin.address
    assert admin.read.get_energy_type_name(1) == "solar_pv"
    admin.energy_types.register_energy_type(14, "agrivoltaic")
    assert admin.read.is_energy_type_registered(14)
    w = owner.watchers.create_watcher("Farm")
    p = owner.projects.create_project(w.watcher_id, "Panels over cassava", 14)
    assert owner.read.get_project_energy_type(p.project_id) == 14
    with pytest.raises(ContractRevertError) as e:
        owner.energy_types.register_energy_type(15, "nope")
    assert e.value.error_name == ContractErrorCode.UnauthorizedEnergyTypeAdmin
    with pytest.raises(ConfigurationError):
        owner.projects.create_project(w.watcher_id, "x", 99)


def test_owner_reads(admin):
    assert admin.read.get_owner() == admin.address
    assert admin.read.get_pending_owner() == "0x0000000000000000000000000000000000000000"
    assert admin.read.get_next_watcher_id() >= 1
