import json
import os
import sys

import pytest
from web3 import HTTPProvider, Web3

sys.path.insert(0, os.path.dirname(__file__))

from energy_attestation import EnergySDK, Network, TxFeeConfig  # noqa: E402

DEPLOYMENT = os.environ.get("EAS_DEPLOYMENT")


def make_sdk(dep, key_index: int) -> EnergySDK:
    w3 = Web3(HTTPProvider(dep["rpc_url"]))
    return EnergySDK(
        w3,
        dep["keys"][key_index],
        Network.AMOY,
        registry_address=dep["registry"],
        schema_uid=dep["schema_uid"],
        eas_address=dep["eas"],
        chain_id=dep["chain_id"],
        tx=TxFeeConfig(min_priority_fee_gwei=1),
    )


@pytest.fixture(scope="session")
def dep():
    return json.load(open(DEPLOYMENT))
